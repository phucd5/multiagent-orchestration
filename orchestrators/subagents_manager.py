from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage, ToolUseBlock
from claude_agent_sdk import ClaudeSDKClient

from agents.base_agent import BaseAgent
from agents.execution_log import ExecutionLog


class SubagentsManager:
    """
    Orchestrator for the subagents manager.
    """

    def __init__(self, subagents: Dict[str, BaseAgent]):
        self.subagents = subagents
        self.conversation_counts = {agent_id: 0 for agent_id in subagents.keys()}
        self.connections: Dict[str, ClaudeSDKClient] = {}
        self.active = False
        self.execution_log: Optional[ExecutionLog] = None

    def set_execution_log(self, log: ExecutionLog):
        self.execution_log = log

    async def spawn(self) -> dict[str, Any]:
        """Spawn the subagents"""
        if self.active:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "ERROR: Subagents already spawned",
                    }
                ],
                "is_error": True,
            }

        for agent_id, agent in self.subagents.items():
            self.connections[agent_id] = agent.as_client()
            await self.connections[agent_id].connect()

        self.active = True
        return {
            "content": [{"type": "text", "text": "SUCCESS: Subagents spawned"}],
            "is_error": False,
        }

    async def communicate(self, agent_id: str, message: str) -> dict[str, Any]:
        """Communicate with a subagent"""
        if not self.active:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "ERROR: Subagents not spawned. Call spawn() first.",
                    }
                ],
                "is_error": True,
            }

        if agent_id not in self.connections:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"ERROR: Subagent '{agent_id}' not found. Available: {list(self.connections.keys())}",
                    }
                ],
                "is_error": True,
            }
        self.conversation_counts[agent_id] += 1

        # send the message to the subagent
        await self.connections[agent_id].query(message)

        responses = []

        # collect responses
        async for msg in self.connections[agent_id].receive_response():
            if isinstance(msg, AssistantMessage):
                # Log subagent turn if execution log is set
                if self.execution_log:
                    if not self.execution_log.has_active_turn():
                        self.execution_log.start_turn(agent_id=agent_id)

                for block in msg.content:
                    if isinstance(block, TextBlock):
                        responses.append(block.text)
                        # Log the assistant message
                        if self.execution_log:
                            self.execution_log.add_assistant_message(block.text)
                    elif isinstance(block, ToolUseBlock):
                        # Log tool use
                        if self.execution_log:
                            self.execution_log.add_tool_use(block.name, block.input)
            elif isinstance(msg, ResultMessage):
                # End the turn and capture stats for this subagent
                if self.execution_log:
                    if self.execution_log.has_active_turn():
                        self.execution_log.end_turn()
                    # Store per-agent stats
                    self.execution_log.set_stats(
                        num_turns=msg.num_turns,
                        duration_ms=msg.duration_ms,
                        duration_api_ms=msg.duration_api_ms,
                        total_cost_usd=msg.total_cost_usd,
                        agent_id=agent_id,
                    )

        response_text = "\n".join(responses) if responses else "[No response]"
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"[{agent_id.upper()} responded]\n\n{response_text}",
                }
            ]
        }

    async def shutdown(self) -> dict[str, Any]:
        """Shutdown the subagents"""
        if not self.active:
            return {
                "content": [{"type": "text", "text": "ERROR: Subagents not spawned"}],
                "is_error": True,
            }

        # Disconnect all subagent connections, catching any errors
        for _, connection in self.connections.items():
            try:
                await connection.disconnect()
            except (Exception, BaseException):
                # Ignore errors during disconnect - connection may already be closed
                # or there may be cancel scope issues from anyio
                pass

        self.connections.clear()
        self.active = False
        return {
            "content": [{"type": "text", "text": "SUCCESS: Subagents shutdown"}],
            "is_error": False,
        }

    @asynccontextmanager
    async def lifespan(self):
        """Context manager for subagent lifecycle management"""
        await self.spawn()
        try:
            yield self
        finally:
            # Always shutdown, even if there's an exception or cancellation
            if self.active:
                # Disconnect each connection sequentially to ensure clean shutdown
                for connection in list(self.connections.values()):
                    try:
                        await connection.disconnect()
                    except Exception:
                        pass
                self.connections.clear()
                self.active = False
