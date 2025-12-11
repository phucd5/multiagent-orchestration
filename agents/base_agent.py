from typing import List, Optional, Dict, Any
from claude_agent_sdk import (
    query,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    AgentDefinition,
    ToolUseBlock,
    ToolResultBlock,
    ResultMessage,
)
from agents.execution_log import ExecutionLog


class BaseAgent:
    """
    BaseAgent class for each agent to implement.
    Supports both single-agent execution and multi-agent orchestration.
    """

    def __init__(
        self,
        agent_id: str,
        system_prompt: str,
        cwd: str,
        sub_agents: Optional[Dict[str, AgentDefinition]] = None,
        max_turns: int = 10,
        model: str = "claude-haiku-4-5-20251001",
        disallowed_tools: Optional[List[str]] = None,
        allowed_tools: Optional[List[str]] = None,
        mcp_servers: Optional[Dict[str, Any]] = None,
        debug: bool = False,
    ):
        """
        Initialize a new agent.

        Args:
            agent_id: Unique identifier for this agent
            system_prompt: System prompt for the agent
            cwd: Current working directory for the agent
            sub_agents: Optional dictionary of sub-agents
            max_turns: Maximum number of conversation turns (default: 10)
            model: Claude model to use (default: claude-haiku-4-5-20251001)
            allowed_tools: List of tools the agent can use (default: all tools)
            mcp_servers: MCP servers to connect to
            debug: Enable debug mode to print messages (default: False)
        """
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.cwd = cwd
        self.max_turns = max_turns
        self.model = model
        self.allowed_tools = allowed_tools or []
        self.disallowed_tools = disallowed_tools or []
        self.sub_agents = sub_agents
        self.mcp_servers = mcp_servers
        self.debug = debug

    async def execute(self, prompt: str) -> ExecutionLog:
        """
        Execute a task given a prompt and return the execution log.
        Uses the query() function for one-shot execution.

        Args:
            prompt: The task/prompt to execute by the agent

        Returns:
            ExecutionLog object containing the trace and statistics
        """
        options = ClaudeAgentOptions(
            system_prompt=self.system_prompt,
            max_turns=self.max_turns,
            model=self.model,
            allowed_tools=self.allowed_tools,
            disallowed_tools=self.disallowed_tools,
            permission_mode="acceptEdits",
            agents=self.sub_agents if self.sub_agents is not None else None,
            mcp_servers=self.mcp_servers if self.mcp_servers is not None else None,
            cwd=self.cwd,
        )

        log = ExecutionLog(debug=self.debug)

        # Set system prompt and user query in the log
        log.set_system_prompt(self.system_prompt)
        log.set_user_query(prompt)

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                # Start turn only if we don't have an active turn
                # Multiple AssistantMessages belong to the same turn
                if not log.has_active_turn():
                    log.start_turn(agent_id=self.agent_id)

                for block in message.content:
                    if isinstance(block, TextBlock):
                        log.add_assistant_message(block.text)
                    elif isinstance(block, ToolUseBlock):
                        log.add_tool_use(block.name, block.input)

            # Handle UserMessage with ToolResultBlock - capture tool results and end turn
            elif hasattr(message, "content") and isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        result_content = (
                            block.content
                            if isinstance(block.content, str)
                            else str(block.content)
                        )
                        log.add_tool_result(
                            result_content,
                            is_error=block.is_error if block.is_error else False,
                        )
                log.end_turn()

            # Capture final statistics
            elif isinstance(message, ResultMessage):
                if log.has_active_turn():
                    log.end_turn()

                log.set_stats(
                    num_turns=message.num_turns,
                    duration_ms=message.duration_ms,
                    duration_api_ms=message.duration_api_ms,
                    total_cost_usd=message.total_cost_usd,
                )

        return log

    def as_client(self) -> ClaudeSDKClient:
        """
        Create a ClaudeSDKClient for persistent communication.

        Returns:
            Configured ClaudeSDKClient instance (not yet connected)
        """
        options = ClaudeAgentOptions(
            system_prompt=self.system_prompt,
            max_turns=self.max_turns,
            model=self.model,
            allowed_tools=self.allowed_tools if self.allowed_tools else None,
            mcp_servers=self.mcp_servers if self.mcp_servers else None,
            cwd=self.cwd,
        )
        return ClaudeSDKClient(options=options)
