from orchestrators.base_orchestrator import BaseOrchestrator
from agents.base_agent import BaseAgent
from agents.execution_log import ExecutionLog


class SingleAgentOrchestrator(BaseOrchestrator):
    """
    Orchestrator for a single agent.
    """

    def __init__(
        self,
        name: str,
        debug: bool = False,
        model: str = "claude-haiku-4-5-20251001",
        max_turn: int = 10,
    ):
        super().__init__(name, debug, model, max_turn)

        self.base_system_prompt = self._load_prompt(
            "orchestrators/prompts/single_agent/sys_prompt.md"
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

    async def run_human_eval(
        self, task: str, task_id: int, output_directory: str
    ) -> ExecutionLog:
        """
        Run the orchestrator for HumanEval benchmark.

        Args:
            task: The coding task/problem to solve
            task_id: Task ID number (will be formatted as "problem_{task_id}.py")
            output_directory: Directory to output the file to

        Returns:
            ExecutionLog object containing the trace and statistics
        """
        system_prompt = self._build_prompt(
            base_prompt=self.base_system_prompt,
            benchmark_prompts=self.benchmark_prompts,
            benchmark="HumanEval",
            output_file_name_param=f"agent_sol_{task_id}.py",
            output_dir_param=output_directory,
            max_turn=self.max_turn,
        )

        agent = BaseAgent(
            agent_id="Agent",
            system_prompt=system_prompt,
            cwd=output_directory,
            max_turns=self.max_turn,
            model=self.model,
            allowed_tools=["Read", "Write", "Bash"],
            debug=self.debug,
        )

        return await agent.execute(task)

    async def run_swe_bench_verified(
        self,
        task: str,
        task_id: str,
        output_directory: str,
        container_name: str,
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

        system_prompt = self._build_prompt(
            base_prompt=self.base_system_prompt,
            benchmark_prompts=self.benchmark_prompts,
            benchmark="SWEBenchVerified",
            output_file_name_param=f"agent_sol_{task_id}.diff",
            output_dir_param=output_directory,
            container_name_param=container_name,
            max_turn=self.max_turn,
        )

        agent = BaseAgent(
            agent_id="Agent",
            system_prompt=system_prompt,
            cwd=output_directory,
            max_turns=self.max_turn,
            model=self.model,
            allowed_tools=["Read", "Write", "Bash"],
            debug=self.debug,
        )

        return await agent.execute(task)

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

        system_prompt = self._build_prompt(
            base_prompt=self.base_system_prompt,
            benchmark_prompts=self.benchmark_prompts,
            benchmark=benchmark,
            output_dir_param=output_directory,
            max_turn=self.max_turn,
        )

        agent = BaseAgent(
            agent_id="Agent",
            system_prompt=system_prompt,
            cwd=output_directory,
            max_turns=self.max_turn,
            model=self.model,
            allowed_tools=["Read", "Write", "Bash"],
            debug=self.debug,
        )

        return await agent.execute(task)
