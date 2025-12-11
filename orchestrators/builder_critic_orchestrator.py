from typing import Dict

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


class BuilderCriticOrchestrator(BaseOrchestrator):
    """
    Orchestrator for the builder-critic pattern.
    """

    def __init__(
        self,
        name: str,
        debug: bool = True,
        model: str = "claude-haiku-4-5-20251001",
        max_turn: int = 15,
    ):
        super().__init__(name, debug, model, max_turn)

        self.base_builder_prompt = self._load_prompt(
            "orchestrators/prompts/builder_critic/sys_prompt_builder.md"
        )
        self.base_critic_prompt = self._load_prompt(
            "orchestrators/prompts/builder_critic/sys_prompt_critic.md"
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
        self.critic_agent = {}

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
        self.critic_agent = self._create_critic_agent(output_directory, "HumanEval")

        builder_prompt = self._build_prompt(
            base_prompt=self.base_builder_prompt,
            benchmark_prompts=self.benchmark_prompts,
            benchmark="HumanEval",
            agent_ids_param="critic",
            output_dir_param=output_directory,
            output_file_name_param=f"agent_sol_{task_id}.py",
            max_turn=self.max_turn,
        )

        return await self._execute_with_builder(task, builder_prompt, output_directory)

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
        self.critic_agent = self._create_critic_agent(
            output_directory, "SWEBenchVerified", container_name
        )

        builder_prompt = self._build_prompt(
            base_prompt=self.base_builder_prompt,
            benchmark_prompts=self.benchmark_prompts,
            benchmark="SWEBenchVerified",
            agent_ids_param="critic",
            output_dir_param=output_directory,
            output_file_name_param=f"agent_sol_{task_id}.diff",
            container_name_param=container_name,
            max_turn=self.max_turn,
        )

        return await self._execute_with_builder(task, builder_prompt, output_directory)

    async def run_end_to_end_eval(
        self, task: str, task_id: str, output_directory: str
    ) -> ExecutionLog:
        """
        Run the orchestrator for end-to-end project evaluation.

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

        self.critic_agent = self._create_critic_agent(output_directory, benchmark)

        builder_prompt = self._build_prompt(
            base_prompt=self.base_builder_prompt,
            benchmark_prompts=self.benchmark_prompts,
            benchmark=benchmark,
            agent_ids_param="critic",
            output_dir_param=output_directory,
            max_turn=self.max_turn,
        )

        return await self._execute_with_builder(task, builder_prompt, output_directory)

    async def _execute_with_builder(
        self, task: str, builder_prompt: str, output_directory: str
    ) -> ExecutionLog:
        """
        Execute a task using the builder agent and critic subagent.

        Args:
            task: The task to execute
            builder_prompt: The system prompt for the builder agent
            output_directory: Working directory for the agents

        Returns:
            ExecutionLog object containing the trace and statistics
        """
        manager = SubagentsManager(subagents=self.critic_agent)
        mcp_server = self._create_communication_mcp_server(manager)

        builder = self._create_builder_agent(
            builder_prompt, output_directory, mcp_server
        )

        log = ExecutionLog(debug=self.debug)
        log.set_system_prompt(builder_prompt)
        log.set_user_query(task)

        manager.set_execution_log(log)

        # Spawn subagents (critic)
        await manager.spawn()

        try:
            async with builder.as_client() as client:
                await client.query(task)

                async for message in client.receive_response():
                    self._process_message(message, log)
        finally:
            await manager.shutdown()

        return log

    def _create_builder_agent(
        self, system_prompt: str, cwd: str, mcp_server
    ) -> BaseAgent:
        """Create the builder agent with all tools including communication."""
        return BaseAgent(
            agent_id="Builder",
            system_prompt=system_prompt,
            cwd=cwd,
            max_turns=self.max_turn,
            model=self.model,
            allowed_tools=[
                "Read",
                "Write",
                "Bash",
                "mcp__subagents_manager__communicate_with_agent",
            ],
            mcp_servers={"subagents_manager": mcp_server},
            debug=self.debug,
        )

    def _process_message(self, message, log: ExecutionLog) -> None:
        """Process a message from the builder agent and update the log."""
        if isinstance(message, AssistantMessage):
            if not log.has_active_turn():
                log.start_turn(agent_id="Builder")

            for block in message.content:
                if isinstance(block, TextBlock):
                    log.add_assistant_message(block.text)
                elif isinstance(block, ToolUseBlock):
                    log.add_tool_use(block.name, block.input)

            if log.has_active_turn():
                log.end_turn()

        elif hasattr(message, "content") and isinstance(message.content, list):
            if not log.has_active_turn():
                log.start_turn(agent_id="Builder")

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

    def _create_critic_agent(
        self, cwd: str, benchmark: str, container_name: str = None
    ) -> Dict[str, BaseAgent]:
        """
        Create the critic agent.

        Args:
            cwd: Working directory for the agent
            benchmark: Name of the benchmark (e.g., "HumanEval", "SWEBenchVerified")
            container_name: Optional Docker container name for SWE-Bench benchmarks
        """
        prompt_kwargs = {"max_turn": self.max_turn, "output_dir_param": cwd}
        if container_name:
            prompt_kwargs["container_name_param"] = container_name

        critic_prompt = self._build_prompt(
            base_prompt=self.base_critic_prompt,
            benchmark_prompts={},
            benchmark=benchmark,
            **prompt_kwargs,
        )
        return {
            "critic": BaseAgent(
                agent_id="critic",
                system_prompt=critic_prompt,
                cwd=cwd,
                max_turns=self.max_turn,
                model=self.model,
                allowed_tools=["Read", "Bash"],
                debug=self.debug,
            )
        }
