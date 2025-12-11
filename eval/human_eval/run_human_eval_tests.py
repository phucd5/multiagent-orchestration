import argparse
import json
import sys
import importlib.util
import signal
from pathlib import Path
from enum import Enum
from typing import List, Optional

# 5 minute timeout per test
TEST_TIMEOUT_SECONDS = 300


class TimeoutError(Exception):
    """Raised when a test exceeds the time limit."""

    pass


def timeout_handler(signum, frame):
    raise TimeoutError("Test execution timed out")


class TestStatus(str, Enum):
    """Test result status.

    PASSED: Solution passed all test cases
    INCORRECT: Solution failed test case (wrong logic/assertion error)
    ERROR: Solution raised an exception during execution
    TIMEOUT: Solution exceeded time limit
    """

    PASSED = "passed"
    INCORRECT = "incorrect"
    ERROR = "error"
    TIMEOUT = "timeout"


def load_module_from_file(file_path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_entry_points(dataset_path: Path) -> dict:
    entry_points = {}
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            # task_id is like "HumanEval/0", extract the number
            task_num = data["task_id"].split("/")[-1]
            entry_points[task_num] = data["entry_point"]
    return entry_points


def extract_function_from_solution(solution_module, entry_point: str):
    if hasattr(solution_module, entry_point):
        return getattr(solution_module, entry_point)
    return None


def run_test(test_file, solution_file, entry_point: str, timeout_seconds: int = 300):
    """
    Run a single test file against its corresponding solution file.

    Args:
        test_file: Path to the test file (e.g., sol_0.py)
        solution_file: Path to the solution file (e.g., agent_sol_0.py)
        entry_point: Name of the function to extract from solution
        timeout_seconds: Maximum time allowed for test execution (default: 300s)

    Returns:
        dict: Result information with status, error_type, and error_message
    """
    try:
        test_module = load_module_from_file(test_file, f"test_{test_file.stem}")
        solution_module = load_module_from_file(
            solution_file, f"solution_{solution_file.stem}"
        )
        candidate_function = extract_function_from_solution(
            solution_module, entry_point
        )

        if candidate_function is None:
            return {
                "status": TestStatus.ERROR,
                "error_type": "missing_function",
                "error_message": f"Function '{entry_point}' not found in solution file",
            }

        if not hasattr(test_module, "check"):
            print(f"FATAL ERROR: No check function found in test file: {test_file}")
            sys.exit(1)

        # Set up timeout
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_seconds)
        try:
            test_module.check(candidate_function)
        finally:
            signal.alarm(0)  # Disable the alarm
        return {"status": TestStatus.PASSED, "error_type": None, "error_message": None}

    except TimeoutError:
        return {
            "status": TestStatus.TIMEOUT,
            "error_type": "timeout",
            "error_message": f"Test exceeded {TEST_TIMEOUT_SECONDS}s time limit",
        }
    except AssertionError as e:
        return {
            "status": TestStatus.INCORRECT,
            "error_type": "assertion_error",
            "error_message": str(e) if str(e) else "Assertion failed",
        }
    except Exception as e:
        return {
            "status": TestStatus.ERROR,
            "error_type": type(e).__name__,
            "error_message": str(e),
        }


def run_evaluation(
    tests_dir: Path,
    solutions_dir: Path,
    output_file: Path,
    dataset_path: Path,
    specific_tests: Optional[List[str]] = None,
):
    """
    Run evaluation on all test files and generate JSON report.

    Args:
        tests_dir: Path to directory containing test files
        solutions_dir: Path to directory containing solution files
        output_file: Path to output JSON file
        dataset_path: Path to the dataset file containing entry points
        specific_tests: Optional list of specific test IDs to run (e.g., ["0", "1", "2"])
    """
    # Load entry points from dataset
    entry_points = load_entry_points(dataset_path)

    # Get all test files, sorted numerically by problem number
    test_files = sorted(
        [f for f in tests_dir.glob("sol_*.py")],
        key=lambda x: int(x.stem.replace("sol_", "")),
    )

    if not test_files:
        print(f"Error: No test files found in {tests_dir}")
        sys.exit(1)

    # Filter to specific tests if provided
    if specific_tests:
        specific_set = set(specific_tests)
        test_files = [
            f for f in test_files if f.stem.replace("sol_", "") in specific_set
        ]
        if not test_files:
            print(f"Error: No matching test files found for IDs: {specific_tests}")
            sys.exit(1)
        print(f"Running {len(test_files)} specific tests: {specific_tests}")
    else:
        print(f"Found {len(test_files)} test files")

    print("Running tests...\n")

    # Track results
    results = []
    passed_count = 0
    incorrect_count = 0
    error_count = 0
    evaluated_count = 0

    for test_file in test_files:
        test_num = test_file.stem.replace("sol_", "")
        solution_file = solutions_dir / f"agent_sol_{test_num}.py"

        evaluated_count += 1

        # Get entry point for this test
        entry_point = entry_points.get(test_num)
        if entry_point is None:
            result = {
                "status": TestStatus.ERROR,
                "error_type": "missing_entry_point",
                "error_message": f"No entry point found in dataset for test {test_num}",
            }
        # If solution doesn't exist, mark as error
        elif not solution_file.exists():
            result = {
                "status": TestStatus.ERROR,
                "error_type": "missing_solution",
                "error_message": f"Solution file not found: {solution_file}",
            }
        else:
            result = run_test(
                test_file, solution_file, entry_point, TEST_TIMEOUT_SECONDS
            )
        result_entry = {
            "task_id": f"{test_num}",
            "test_file": str(test_file),
            "solution_file": str(solution_file),
            "status": result["status"],
            "error_type": result["error_type"],
            "error_message": result["error_message"],
        }

        results.append(result_entry)

        # Update counts
        if result["status"] == TestStatus.PASSED:
            passed_count += 1
            print(f"[PASS] Test {test_num}")
        elif result["status"] == TestStatus.INCORRECT:
            incorrect_count += 1
            print(f"[INCORRECT] Test {test_num}: {result['error_message']}")
        elif result["status"] == TestStatus.TIMEOUT:
            error_count += 1
            print(f"[TIMEOUT] Test {test_num}: {result['error_message']}")
        else:  # TestStatus.ERROR
            error_count += 1
            print(
                f"[ERROR] Test {test_num}: {result['error_type']} - {result['error_message']}"
            )

    # Calculate statistics
    total_evaluated = evaluated_count
    failed_count = incorrect_count + error_count  # Failed = Incorrect + Error combined
    pass_rate = (passed_count / total_evaluated * 100) if total_evaluated > 0 else 0
    incorrect_rate = (
        (incorrect_count / total_evaluated * 100) if total_evaluated > 0 else 0
    )
    error_rate = (error_count / total_evaluated * 100) if total_evaluated > 0 else 0

    summary = {
        "core_stats": {
            "total": total_evaluated,
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate": round(pass_rate, 4),
        },
        "extra_stats": {
            "incorrect": incorrect_count,
            "error": error_count,
            "incorrect_rate": round(incorrect_rate, 4),
            "error_rate": round(error_rate, 4),
        },
    }

    output_data = {"summary": summary, "results": results}
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("Core Stats:")
    print(f"  Total evaluated:  {total_evaluated}")
    print(f"  Passed:           {passed_count}")
    print(f"  Failed:           {failed_count}")
    print(f"  Pass rate:        {pass_rate:.2f}%")
    print()
    print("Extra Stats:")
    print(f"  Incorrect:        {incorrect_count} (wrong logic)")
    print(f"  Error:            {error_count} (exceptions)")
    print(f"  Incorrect rate:   {incorrect_rate:.2f}%")
    print(f"  Error rate:       {error_rate:.2f}%")
    print("=" * 60)
    print(f"\nResults saved to: {output_file}")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run HumanEval tests against agent solutions"
    )
    parser.add_argument(
        "--tests_dir",
        type=str,
        required=True,
        help="Path to directory containing test files",
    )
    parser.add_argument(
        "--solutions_dir",
        type=str,
        required=True,
        help="Path to directory containing solution files",
    )
    parser.add_argument(
        "--output_file",
        type=str,
        required=True,
        help="Path to output JSON file for results",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="Path to the dataset JSONL file containing entry points",
    )
    parser.add_argument(
        "--specific",
        type=str,
        nargs="+",
        default=None,
        help="Specific test IDs to run (e.g., --specific 0 1 2 3)",
    )

    args = parser.parse_args()

    tests_dir = Path(args.tests_dir)
    solutions_dir = Path(args.solutions_dir)
    output_file = Path(args.output_file)
    dataset_path = Path(args.dataset)

    if not tests_dir.exists() or not solutions_dir.exists():
        print(f"Error: Directories not found: {tests_dir} or {solutions_dir}")
        sys.exit(1)

    if not dataset_path.exists():
        print(f"Error: Dataset file not found: {dataset_path}")
        sys.exit(1)

    sys.exit(
        run_evaluation(
            tests_dir, solutions_dir, output_file, dataset_path, args.specific
        )
    )
