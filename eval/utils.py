import json
import os
import shutil
from typing import Set

from agents.execution_log import ExecutionLog


def get_completed_task_ids(log_file: str) -> Set[str]:
    if not log_file or not os.path.exists(log_file):
        return set()

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            logs = json.load(f)
            return set(logs.keys())
    except (json.JSONDecodeError, IOError):
        return set()


def setup_eval_directories(
    output_directory: str,
    log_file: str = None,
    resume: bool = False,
) -> None:
    if not resume and os.path.exists(output_directory):
        shutil.rmtree(output_directory)
    os.makedirs(output_directory, exist_ok=True)

    if log_file:
        log_directory = os.path.dirname(log_file)
        if log_directory:
            os.makedirs(log_directory, exist_ok=True)
        # Clear log file if not resuming
        if not resume and os.path.exists(log_file):
            os.remove(log_file)


def save_execution_log(
    log: ExecutionLog,
    log_file: str,
    task_id: str,
    prefix: str = "",
) -> str:
    log_directory = os.path.dirname(log_file)
    log_filename = os.path.basename(log_file)
    log_path = log.save(
        log_directory=log_directory, task_id=task_id, log_filename=log_filename
    )
    if prefix:
        print(f"[{prefix}] Log saved to: {log_path}\n")
    else:
        print(f"Log saved to: {log_path}\n")
    return log_path
