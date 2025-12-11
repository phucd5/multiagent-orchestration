from typing import List, Dict
import argparse
import json
import asyncio
import os
import shutil

from orchestrators.base_orchestrator import BaseOrchestrator
from orchestrators.single_agent_orchestrator import SingleAgentOrchestrator
from orchestrators.leader_orchestrator import LeaderOrchestrator
from orchestrators.builder_critic_orchestrator import BuilderCriticOrchestrator
from orchestrators.voting_orchestrator import VotingOrchestrator
from orchestrators.specialists_orchestrator import SpecialistsOrchestrator
from eval.utils import (
    get_completed_task_ids,
    save_execution_log,
)


def load_end_to_end_dataset(
    path: str, limit: int = None, task_filter: str = None
) -> List[Dict]:
    """Load the end-to-end evaluation dataset.

    Args:
        path: Path to the dataset JSON file
        limit: Maximum number of examples to load (None for all)
        task_filter: Filter to specific task(s) by task_id (e.g., "finance_tracker", "spam_classifier")

    Returns:
        List of task dictionaries
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

        # Filter by task if specified
        if task_filter:
            data = [task for task in data if task["task_id"] == task_filter]

        if limit:
            return data[:limit]
        return data


def copy_template_to_output(template_dir: str, output_dir: str):
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    shutil.copytree(template_dir, output_dir)
    print(f"[EndToEnd] Copied template from {template_dir} to {output_dir}")


async def run_single_task(
    orchestrator: BaseOrchestrator,
    task: str,
    task_id: str,
    output_directory: str,
    log_file: str = None,
):
    log = await orchestrator.run_end_to_end_eval(
        task=task, task_id=task_id, output_directory=output_directory
    )

    print()
    log.summary()
    print()

    if log_file:
        save_execution_log(log, log_file, task_id, prefix="EndToEnd")

    return log


def evaluate_end_to_end(
    orchestrator: BaseOrchestrator,
    limit: int,
    dataset: str,
    solutions_directory: str,
    template_directory: str,
    log_file: str = None,
    resume: bool = False,
    specific_tests: List[str] = None,
    task_filter: str = None,
):
    """
    Evaluate the end-to-end dataset using the specified orchestrator.

    Args:
        orchestrator: The orchestrator to use for evaluation
        limit: Maximum number of examples to load (None for all)
        dataset: Path to the dataset JSON file
        solutions_directory: Base path to the solutions directory
        template_directory: Base path to the template directory
        log_file: Path to the log file where logs will be saved
        resume: If True, skip tasks that already have logs
        specific_tests: List of specific test IDs to run
        task_filter: Filter to specific task by task_id
    """
    examples = load_end_to_end_dataset(dataset, limit=limit, task_filter=task_filter)

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
                        f"[EndToEnd] Removed {len(removed)} entries from log: {removed}"
                    )
            except (json.JSONDecodeError, IOError) as e:
                print(f"[EndToEnd] Warning: Could not modify log file: {e}")

    # Create solutions directory if it doesn't exist
    os.makedirs(solutions_directory, exist_ok=True)

    # Setup log file directories
    if log_file:
        log_directory = os.path.dirname(log_file)
        if log_directory:
            os.makedirs(log_directory, exist_ok=True)
        # Clear log file if not resuming
        if not resume and os.path.exists(log_file):
            os.remove(log_file)

    for idx, example in enumerate(examples):
        task_id = example["task_id"]
        task_name = example["task_name"]
        template_dir = example["template_dir"]

        if task_id in completed_ids:
            print(f"\n[Resume] Skipping already completed task: {task_id}")
            continue

        print(f"\n{'='*80}")
        print(f"Running task {idx + 1}/{len(examples)}: {task_name} ({task_id})")
        print(f"{'='*80}\n")

        # Prepare working directory for this task in solutions directory
        task_working_dir = os.path.join(solutions_directory, task_id)
        template_path = os.path.join(template_directory, template_dir)
        copy_template_to_output(template_path, task_working_dir)

        # Load instruction and environment prompts
        instruction_file = example["instruction_file"]
        instruction_path = os.path.join(
            "orchestrators/prompts/end_to_end_eval", instruction_file
        )
        with open(instruction_path, "r", encoding="utf-8") as f:
            instruction_content = f.read()

        # Run the agent
        asyncio.run(
            run_single_task(
                orchestrator=orchestrator,
                task=instruction_content,
                task_id=task_id,
                output_directory=task_working_dir,
                log_file=log_file,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run end-to-end evaluation on projects"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of examples to load (default: all)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="Path to the dataset JSON file",
    )
    parser.add_argument(
        "--solutions_directory",
        type=str,
        required=True,
        help="Base path to the solutions directory",
    )
    parser.add_argument(
        "--template_directory",
        type=str,
        required=True,
        help="Base path to the template directory",
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
        help="Path to the log file to save execution logs",
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
        help="Specific test IDs to run (e.g., --specific finance_tracker spam_classifier)",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        choices=["finance_tracker", "spam_classifier"],
        help="Run a specific task only (finance_tracker or spam_classifier)",
    )
    args = parser.parse_args()

    orchestrator_map = {
        "single_agent": SingleAgentOrchestrator,
        "leader": LeaderOrchestrator,
        "builder_critic": BuilderCriticOrchestrator,
        "voting": VotingOrchestrator,
        "specialists": SpecialistsOrchestrator,
    }

    orchestrator = orchestrator_map[args.orchestrator](
        name=f"{args.orchestrator}_end_to_end",
        debug=args.debug,
        model=args.model,
        max_turn=args.max_turn,
    )

    evaluate_end_to_end(
        orchestrator=orchestrator,
        limit=args.limit,
        dataset=args.dataset,
        solutions_directory=args.solutions_directory,
        template_directory=args.template_directory,
        log_file=args.log_file,
        resume=args.resume,
        specific_tests=args.specific,
        task_filter=args.task,
    )
