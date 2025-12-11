from typing import List, Dict
import argparse

import json
import asyncio
from orchestrators.base_orchestrator import BaseOrchestrator
from orchestrators.single_agent_orchestrator import SingleAgentOrchestrator
from orchestrators.leader_orchestrator import LeaderOrchestrator
from orchestrators.builder_critic_orchestrator import BuilderCriticOrchestrator
from orchestrators.voting_orchestrator import VotingOrchestrator
from orchestrators.specialists_orchestrator import SpecialistsOrchestrator
from eval.utils import (
    get_completed_task_ids,
    setup_eval_directories,
    save_execution_log,
)


def load_human_eval_dataset(path: str, limit: int = 5) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for i, line in enumerate(f) if i < limit]


async def run_single_task(
    orchestrator: BaseOrchestrator,
    task: str,
    task_id: str,
    output_directory: str,
    log_file: str = None,
):
    log = await orchestrator.run_human_eval(
        task=task, task_id=task_id, output_directory=output_directory
    )

    print()
    log.summary()
    print()

    if log_file:
        save_execution_log(log, log_file, task_id, prefix="HumanEval")

    return log


def evaluate_human_eval(
    orchestrator: BaseOrchestrator,
    limit: int,
    dataset: str,
    output_directory: str,
    log_file: str = None,
    resume: bool = False,
):
    """
    Evaluate the HumanEval dataset using a single agent orchestrator.

    Args:
        limit: Maximum number of examples to load
        dataset: Path to the dataset
        output_directory: Path to the output directory
        log_file: Path to the log file where logs will be saved
        resume: If True, skip tasks that already have logs
    """
    examples = load_human_eval_dataset(dataset, limit=limit)

    # Get completed task IDs if resuming
    completed_ids = set()
    if resume:
        completed_ids = get_completed_task_ids(log_file)
        if completed_ids:
            print(
                f"[Resume] Found {len(completed_ids)} completed tasks: {completed_ids}"
            )

    setup_eval_directories(output_directory, log_file, resume)

    # Run on each example - each task gets its own event loop to avoid
    # cancel scope pollution from anyio
    for example in examples:
        task, task_id = example["prompt"], example["task_id"]
        task_id = task_id.split("/")[-1]

        # Skip if already completed and resuming
        if task_id in completed_ids:
            print(f"\n[Resume] Skipping already completed task: {task_id}")
            continue

        print(f"\n{'='*80}")
        print(f"Running task: {task_id}")
        print(f"{'='*80}\n")

        asyncio.run(
            run_single_task(
                orchestrator=orchestrator,
                task=task,
                task_id=task_id,
                output_directory=output_directory,
                log_file=log_file,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser("Evaluate the HumanEval dataset")
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
    args = parser.parse_args()

    orchestrator_map = {
        "single_agent": SingleAgentOrchestrator,
        "leader": LeaderOrchestrator,
        "builder_critic": BuilderCriticOrchestrator,
        "voting": VotingOrchestrator,
        "specialists": SpecialistsOrchestrator,
    }

    orchestrator = orchestrator_map[args.orchestrator](
        name=f"{args.orchestrator}_human_eval_orchestrator",
        debug=args.debug,
        model=args.model,
        max_turn=args.max_turn,
    )

    evaluate_human_eval(
        orchestrator=orchestrator,
        limit=args.limit,
        dataset=args.dataset,
        output_directory=args.output_directory,
        log_file=args.log_file,
        resume=args.resume,
    )
