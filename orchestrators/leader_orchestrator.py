from typing import Dict, List

from claude_agent_sdk import (
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    ResultMessage,
)

from orchestrators.base_orchestrator import BaseOrchestrator
from orchestrators.subagents_manager import SubagentsManager
from agents.base_agent import BaseAgent
from agents.execution_log import ExecutionLog


class LeaderOrchestrator(BaseOrchestrator):
    """
    Orchestrator for the leader agent that manages 3 SWE specialists.
    """

    def __init__(
        self,
        name: str,
        debug: bool = True,
        model: str = "claude-haiku-4-5-20251001",
        max_turn: int = 15,
    ):
        super().__init__(name, debug, model, max_turn)

        self.base_leader_prompt = self._load_prompt(
            "orchestrators/prompts/leader/sys_prompt_leader.md"
        )
        self.base_agent_prompt = self._load_prompt(
            "orchestrators/prompts/leader/sys_prompt_agent.md"
        )

        self.benchmark_prompts = {
            "HumanEval": self._load_prompt("orchestrators/prompts/human_eval_inst.md"),
            "SWEBenchVerified": self._load_prompt(
                "orchestrators/prompts/swe_bench_verified_inst.md"
            ),
            "EndToEnd_Financial": self._load_prompt(
                "orchestrators/prompts/end_to_end_eval/finance_tracker_inst.md"
            ),
            "EndToEnd_Spam": self._load_prompt(
                "orchestrators/prompts/end_to_end_eval/spam_classifer_inst.md"
            ),
        }
        self.swe_agents = {}

    async def run_human_eval(
        self, task: str, task_id: int, output_directory: str
    ) -> ExecutionLog:
        """
        Run the orchestrator for HumanEval benchmark.

        Args:
            task: The coding task/problem to solve
            task_id: Task ID number (will be formatted as "agent_sol_{task_id}.py")
            output_directory: Directory to output the file to

        Returns:
            ExecutionLog object containing the trace and statistics
        """
        self.swe_agents = self._create_swe_agents(output_directory, "HumanEval")

        leader_prompt = self._build_prompt(
            base_prompt=self.base_leader_prompt,
            benchmark_prompts=self.benchmark_prompts,
            benchmark="HumanEval",
            count_param=str(len(self._get_agent_names())),
            agent_ids_param=", ".join(self._get_agent_names()),
            output_dir_param=output_directory,
            output_file_name_param=f"agent_sol_{task_id}.py",
            max_turn=self.max_turn,
        )

        return await self._execute_with_leader(task, leader_prompt, output_directory)

    async def run_swe_bench_verified(
        self, task: str, task_id: str, output_directory: str, container_name: str
    ) -> ExecutionLog:
        """
        Run the orchestrator for SWE-Bench Verified benchmark.

        Args:
            task: The coding task/problem to solve (includes problem statement and test info)
            task_id: Task ID (e.g., "django__django-13315")
            output_directory: Directory to output the patch file to
            container_name: Name of the Docker container with the repo setup

        Returns:
            ExecutionLog object containing the trace and statistics
        """
        self.swe_agents = self._create_swe_agents(
            output_directory, "SWEBenchVerified", container_name
        )

        leader_prompt = self._build_prompt(
            base_prompt=self.base_leader_prompt,
            benchmark_prompts=self.benchmark_prompts,
            benchmark="SWEBenchVerified",
            count_param=str(len(self._get_agent_names())),
            agent_ids_param=", ".join(self._get_agent_names()),
            output_dir_param=output_directory,
            output_file_name_param=f"agent_sol_{task_id}.diff",
            container_name_param=container_name,
            max_turn=self.max_turn,
        )

        return await self._execute_with_leader(task, leader_prompt, output_directory)

    async def run_end_to_end_eval(
        self, task: str, task_id: str, output_directory: str
    ) -> ExecutionLog:
        """
        Run the orchestrator for end-to-end evaluation.

        Args:
            task: The coding task/problem to solve
            task_id: Task ID (e.g., "finance_tracker", "spam_classifier")
            output_directory: Directory containing the project template and for outputs

        Returns:
            ExecutionLog object containing the trace and statistics
        """
        # Determine which benchmark to use based on task_id
        if "finance" in task_id.lower():
            benchmark = "EndToEnd_Financial"
        elif "spam" in task_id.lower():
            benchmark = "EndToEnd_Spam"
        else:
            raise ValueError(f"Unknown task_id: {task_id}")

        self.swe_agents = self._create_swe_agents(output_directory, benchmark)

        leader_prompt = self._build_prompt(
            base_prompt=self.base_leader_prompt,
            benchmark_prompts=self.benchmark_prompts,
            benchmark=benchmark,
            count_param=str(len(self._get_agent_names())),
            agent_ids_param=", ".join(self._get_agent_names()),
            output_dir_param=output_directory,
            max_turn=self.max_turn,
        )

        return await self._execute_with_leader(task, leader_prompt, output_directory)

    async def _execute_with_leader(
        self, task: str, leader_prompt: str, output_directory: str
    ) -> ExecutionLog:
        """
        Execute a task using the leader agent and subagents.

        Args:
            task: The task to execute
            leader_prompt: The system prompt for the leader agent
            output_directory: Working directory for the agents

        Returns:
            ExecutionLog object containing the trace and statistics
        """
        manager = SubagentsManager(subagents=self.swe_agents)
        mcp_server = self._create_communication_mcp_server(manager)

        leader = self._create_leader_agent(leader_prompt, output_directory, mcp_server)

        log = ExecutionLog(debug=self.debug)
        log.set_system_prompt(leader_prompt)
        log.set_user_query(task)

        manager.set_execution_log(log)

        # Spawn subagents
        await manager.spawn()

        try:
            async with leader.as_client() as client:
                await client.query(task)

                async for message in client.receive_response():
                    self._process_message(message, log)
        finally:
            await manager.shutdown()

        return log

    def _create_leader_agent(
        self, system_prompt: str, cwd: str, mcp_server
    ) -> BaseAgent:
        """Create the leader agent with communication tools only."""
        return BaseAgent(
            agent_id="Leader",
            system_prompt=system_prompt,
            cwd=cwd,
            max_turns=self.max_turn,
            model=self.model,
            disallowed_tools=["Read", "Write", "Bash"],
            allowed_tools=["mcp__subagents_manager__communicate_with_agent"],
            mcp_servers={"subagents_manager": mcp_server},
            debug=self.debug,
        )

    def _process_message(self, message, log: ExecutionLog) -> None:
        """Process a message from the leader agent and update the log."""
        if isinstance(message, AssistantMessage):
            if not log.has_active_turn():
                log.start_turn(agent_id="Leader")

            for block in message.content:
                if isinstance(block, TextBlock):
                    log.add_assistant_message(block.text)
                elif isinstance(block, ToolUseBlock):
                    log.add_tool_use(block.name, block.input)

            if log.has_active_turn():
                log.end_turn()

        elif hasattr(message, "content") and isinstance(message.content, list):
            if not log.has_active_turn():
                log.start_turn(agent_id="Leader")

            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    log.add_tool_result(
                        block.content,
                        is_error=block.is_error if block.is_error else False,
                    )
            log.end_turn()

        elif isinstance(message, ResultMessage):
            if log.has_active_turn():
                log.end_turn()

            log.set_stats(
                num_turns=message.num_turns,
                duration_ms=message.duration_ms,
                duration_api_ms=message.duration_api_ms,
                total_cost_usd=message.total_cost_usd,
            )

    def _create_swe_agents(
        self, cwd: str, benchmark: str, container_name: str = None
    ) -> Dict[str, BaseAgent]:
        """
        Create SWE Agents

        Args:
            cwd: Working directory for the agents
            benchmark: Name of the benchmark (e.g., "HumanEval", "SWEBenchVerified")
            container_name: Optional Docker container name for SWE-Bench benchmarks
        """
        swe_agents = {}

        # Build the agent prompt with env guidelines for the benchmark
        prompt_kwargs = {"max_turn": self.max_turn, "output_dir_param": cwd}
        if container_name:
            prompt_kwargs["container_name_param"] = container_name

        agent_prompt = self._build_prompt(
            base_prompt=self.base_agent_prompt,
            benchmark_prompts={},
            benchmark=benchmark,
            **prompt_kwargs,
        )

        for i in range(1, 4):
            agent_id = f"swe_{i}"
            swe_agents[agent_id] = BaseAgent(
                agent_id=agent_id,
                system_prompt=agent_prompt,
                cwd=cwd,
                max_turns=self.max_turn,
                model=self.model,
                allowed_tools=["Read", "Write", "Bash"],
                debug=self.debug,
            )

        return swe_agents

    def _update_swe_agents_cwd(self, cwd: str):
        """Update the cwd for all SWE agents."""
        for agent in self.swe_agents.values():
            agent.cwd = cwd

    def _get_agent_names(self) -> List[str]:
        return list(self.swe_agents.keys())
