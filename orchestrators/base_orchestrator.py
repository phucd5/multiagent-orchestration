from abc import ABC
from abc import abstractmethod
from typing import Dict
import re

from claude_agent_sdk import create_sdk_mcp_server, tool

from agents.execution_log import ExecutionLog
from orchestrators.subagents_manager import SubagentsManager


class BaseOrchestrator(ABC):
    """
    Abstract base class for all orchestrators.
    Each orchestrator defines a coordination strategy among multiple agents.
    """

    def __init__(
        self,
        name: str,
        debug: bool = False,
        model: str = "claude-haiku-4-5-20251001",
        max_turn: int = 10,
    ):
        self.name = name
        self.debug = debug
        self.model = model
        self.max_turn = max_turn

        # Load environment guidelines for different benchmarks
        self.env_guidelines = {
            "HumanEval": self._load_prompt("orchestrators/prompts/human_eval_env.md"),
            "SWEBenchVerified": self._load_prompt(
                "orchestrators/prompts/swe_bench_env.md"
            ),
            "EndToEnd_Financial": self._load_prompt(
                "orchestrators/prompts/end_to_end_eval/finance_tracker_env.md"
            ),
            "EndToEnd_Spam": self._load_prompt(
                "orchestrators/prompts/end_to_end_eval/spam_classifer_env.md"
            ),
        }

    @abstractmethod
    async def run_human_eval(
        self, task: str, task_id: int, output_directory: str
    ) -> ExecutionLog:
        """
        Run the orchestrator for HumanEval benchmark.

        Args:
            task: The coding task/problem to solve
            task_id: Task ID number (will be formatted as "problem_{task_id}.py")
            output_directory: Directory to output the file to
        """

    @abstractmethod
    async def run_swe_bench_verified(
        self,
        task: str,
        task_id: str,
        output_directory: str,
        container_name: str,
    ) -> ExecutionLog:
        """
        Run the orchestrator for SWE Bench Verified benchmark.

        Args:
            task: The coding task/problem to solve
            task_id: Task ID (e.g., "django__django-13315")
            output_directory: Directory to output the patch file to
            container_name: Name of the Docker container with the repo setup

        Returns:
            ExecutionLog object containing the trace and statistics
        """

    @abstractmethod
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

    def _load_prompt(self, filepath: str) -> str:
        """
        Load a prompt file
        """
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    def _build_prompt(
        self,
        base_prompt: str,
        benchmark_prompts: Dict[str, str],
        benchmark: str,
        **kwargs,
    ) -> str:
        """
        Build a complete prompt by combining base prompt with benchmark-specific instructions.

        Args:
            base_prompt: The base system prompt template
            benchmark_prompts: Dictionary mapping benchmark names to their prompt templates
            benchmark: Name of the benchmark (e.g., "HumanEval")
            **kwargs: Additional parameters to replace in the prompt template

        Returns:
            Complete system prompt with all placeholders replaced
        """
        benchmark_prompt = benchmark_prompts.get(benchmark, "")
        system_prompt = base_prompt

        # Replace <cb_env_guidelines> with the environment guidelines for the benchmark
        env_guideline = self.env_guidelines.get(benchmark, "")
        system_prompt = system_prompt.replace("<cb_env_guidelines>", env_guideline)

        # Extract content between tags from benchmark prompt and replace in system prompt
        # Find all tags like <tag_name>content</tag_name> in the benchmark prompt
        tag_pattern = r"<(\w+)>(.*?)</\1>"
        matches = re.findall(tag_pattern, benchmark_prompt, re.DOTALL)

        for tag_name, content in matches:
            # Replace the placeholder <tag_name> in system prompt with the extracted content
            placeholder = f"<{tag_name}>"
            system_prompt = system_prompt.replace(placeholder, content.strip())

        # Replace any remaining parameter placeholders from kwargs
        for key, value in kwargs.items():
            placeholder = f"<{key}>"
            system_prompt = system_prompt.replace(placeholder, str(value))

        return system_prompt

    def _create_communication_mcp_server(self, manager: SubagentsManager):
        """
        Create an MCP server for agent communication.

        Args:
            manager: The SubagentsManager instance to use for communication

        Returns:
            An MCP server configured with the communicate_with_agent tool
        """

        @tool(
            "communicate_with_agent",
            "Communicate with a team member (other agent)",
            {"agent_id": str, "message": str},
        )
        async def communicate_tool(args: dict) -> dict:
            return await manager.communicate(args["agent_id"], args["message"])

        return create_sdk_mcp_server(
            name="subagents_manager",
            version="1.0.0",
            tools=[
                communicate_tool,
            ],
        )
