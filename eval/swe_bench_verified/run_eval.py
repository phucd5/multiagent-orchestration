from textwrap import dedent
from typing import List, Dict
import argparse
import json
import asyncio
import sys
import subprocess
import os

from orchestrators.base_orchestrator import BaseOrchestrator
from orchestrators.single_agent_orchestrator import SingleAgentOrchestrator
from orchestrators.leader_orchestrator import LeaderOrchestrator
from orchestrators.voting_orchestrator import VotingOrchestrator
from orchestrators.specialists_orchestrator import SpecialistsOrchestrator
from orchestrators.builder_critic_orchestrator import BuilderCriticOrchestrator
from eval.swe_bench_verified.docker_sandbox import DockerSandbox, CONTAINER_WORKSPACE
from eval.utils import (
    get_completed_task_ids,
    setup_eval_directories,
    save_execution_log,
)


def load_swe_bench_verified_dataset(path: str, limit: int = 5) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data[:limit]


async def run_single_task(
    orchestrator: BaseOrchestrator,
    task: str,
    task_id: str,
    sandbox: DockerSandbox,
    output_directory: str,
    log_file: str = None,
):
    log = await orchestrator.run_swe_bench_verified(
        task=task,
        task_id=task_id,
        output_directory=output_directory,
        container_name=sandbox.container_name,
    )

    print()
    log.summary()
    print()

    if log_file:
        save_execution_log(log, log_file, task_id, prefix="SweBenchVerified")

    return log


def evaluate_swe_bench_verified(
    orchestrator: BaseOrchestrator,
    limit: int,
    dataset: str,
    output_directory: str,
    log_file: str = None,
    resume: bool = False,
    specific_tests: List[str] = None,
):
    """
    Evaluate the SWE-Bench Verified dataset using the specified orchestrator.
    Args:
        orchestrator: The orchestrator to use for evaluation
        limit: Maximum number of examples to load
        dataset: Path to the dataset
        output_directory: Path to the output directory
        log_file: Path to the log file where logs will be saved
        resume: If True, skip tasks that already have logs
        specific_tests: List of specific test IDs to run
    """
    examples = load_swe_bench_verified_dataset(dataset, limit=limit)

    # Get completed task IDs if resuming
    completed_ids = set()
    if resume:
        completed_ids = get_completed_task_ids(log_file)
        if completed_ids:
            print(
                f"[Resume] Found {len(completed_ids)} completed tasks: {completed_ids}"
            )

    # If specific tests are requested, remove them from completed_ids and log file
    if specific_tests:
        specific_set = set(specific_tests)
        print(f"[Specific] Running specific tests: {specific_set}")

        # Remove from completed_ids so they will be re-run
        completed_ids -= specific_set

        # Remove from log file if it exists
        if log_file and os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    logs = json.load(f)

                # Remove specific test entries
                removed = []
                for test_id in specific_tests:
                    if test_id in logs:
                        del logs[test_id]
                        removed.append(test_id)

                if removed:
                    # Write back the modified log
                    with open(log_file, "w", encoding="utf-8") as f:
                        json.dump(logs, f, indent=2)
                    print(
                        f"[Specific] Removed {len(removed)} entries from log: {removed}"
                    )
            except (json.JSONDecodeError, IOError) as e:
                print(f"[Specific] Warning: Could not modify log file: {e}")

    setup_eval_directories(output_directory, log_file, resume)

    for idx, example in enumerate(examples):
        instance_id = example["instance_id"]
        task_num = example["_id"].split("/")[-1]
        repo = example["repo"]
        problem_statement = example["problem_statement"]
        hints_text = example["hints_text"]

        # Skip if already completed and resuming
        if task_num in completed_ids:
            print(f"\n[Resume] Skipping already completed task: {instance_id}")
            continue

        print(f"\n{'='*80}")
        print(f"Running task {idx + 1}/{len(examples)}: {instance_id}")
        print(f"Repository: {repo}")
        print(f"{'='*80}\n")

        # Start Docker sandbox
        # Include orchestrator name in container name to allow parallel runs
        sandbox = DockerSandbox(
            container_name=f"swebench-{orchestrator.name}-{instance_id}",
            instance_id=instance_id,
        )
        try:
            sandbox.start()

            # Build the prompt for the agent
            prompt = dedent(
                f"""
            Repository: {repo}
            Working Directory: {CONTAINER_WORKSPACE}

            Problem To Fix:
            {problem_statement}
            Maintainer's Hint to help you fix the problem: 
            {hints_text}
            """
            ).strip()

            # Run the agent
            asyncio.run(
                run_single_task(
                    orchestrator=orchestrator,
                    task=prompt,
                    task_id=task_num,
                    sandbox=sandbox,
                    output_directory=output_directory,
                    log_file=log_file,
                )
            )

        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            print(f"[SweBenchVerified] Error running task {instance_id}: {e}")
            sys.exit(1)
        finally:
            sandbox.stop()  # clean up the container


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SWE-Bench Verified evaluation")
    parser.add_argument(
        "--limit", type=int, default=5, help="Maximum number of examples to load"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="Path to the dataset",
    )
    parser.add_argument(
        "--output_directory",
        type=str,
        required=True,
        help="Path to the output directory",
    )
    parser.add_argument(
        "--orchestrator",
        type=str,
        required=True,
        choices=["single_agent", "leader", "builder_critic", "voting", "specialists"],
        help="Orchestrator to use",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode to print messages in real-time",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="claude-haiku-4-5-20251001",
        help="Claude model to use (default: claude-haiku-4-5-20251001)",
    )
    parser.add_argument(
        "--max_turn",
        type=int,
        required=True,
        help="Maximum number of conversation turns",
    )
    parser.add_argument(
        "--log_file",
        type=str,
        default=None,
        help="Path to the log file to save execution logs (optional)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing logs, skipping already completed tasks",
    )
    parser.add_argument(
        "--specific",
        type=str,
        nargs="+",
        default=None,
        help="Specific test IDs to run (e.g., --specific 0 1 2 3). Removes these from log if present.",
    )
    args = parser.parse_args()

    orchestrator_map = {
        "single_agent": SingleAgentOrchestrator,
        "leader": LeaderOrchestrator,
        "voting": VotingOrchestrator,
        "specialists": SpecialistsOrchestrator,
        "builder_critic": BuilderCriticOrchestrator,
    }

    orchestrator = orchestrator_map[args.orchestrator](
        name=f"{args.orchestrator}_swe_bench_verified",
        debug=args.debug,
        model=args.model,
        max_turn=args.max_turn,
    )

    evaluate_swe_bench_verified(
        orchestrator=orchestrator,
        limit=args.limit,
        dataset=args.dataset,
        output_directory=args.output_directory,
        log_file=args.log_file,
        resume=args.resume,
        specific_tests=args.specific,
    )
