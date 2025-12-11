import argparse
import json
import sys
import subprocess
from pathlib import Path
from enum import Enum
from typing import List, Dict, Optional


EPOCH_IMAGE_PREFIX = "ghcr.io/epoch-research/swe-bench.eval.x86_64"
CONTAINER_WORKSPACE = "/testbed"


class TestStatus(str, Enum):
    """Test result status.

    PASSED: Solution passed all test cases (FAIL_TO_PASS and PASS_TO_PASS)
    INCORRECT: Solution failed FAIL_TO_PASS tests (wrong logic/assertion error)
    BACKWARDS_FAILURE: Solution failed PASS_TO_PASS tests (regression)
    ERROR: Solution raised an exception during execution
    """

    PASSED = "passed"
    INCORRECT = "incorrect"
    BACKWARDS_FAILURE = "backwards_failure"
    ERROR = "error"


def load_swe_bench_dataset(dataset_path: str) -> List[Dict]:
    with open(dataset_path, "r", encoding="utf-8") as f:
        return json.load(f)


def start_container(instance_id: str, container_name: str) -> Optional[str]:
    image = f"{EPOCH_IMAGE_PREFIX}.{instance_id}"

    # Remove existing container with same name if exists
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
        check=False,
    )

    # Start new container
    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--platform",
            "linux/amd64",
            "--name",
            container_name,
            "-w",
            CONTAINER_WORKSPACE,
            image,
            "tail",
            "-f",
            "/dev/null",  # Keep container running
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        print(f"[RunSweBenchTests] Failed to start container: {result.stderr}")
        return None

    container_id = result.stdout.strip()
    print(
        f"[RunSweBenchTests] Started container: {container_name} ({container_id[:12]})"
    )
    return container_id


def stop_container(container_name: str):
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
        check=False,
    )
    print(f"[RunSweBenchTests] Stopped container: {container_name}")


def copy_solution_to_container(solution_file: Path, container_name: str) -> bool:
    dest_path = f"{container_name}:{CONTAINER_WORKSPACE}/{solution_file.name}"
    result = subprocess.run(
        ["docker", "cp", str(solution_file), dest_path],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"[RunSweBenchTests] Failed to copy solution: {result.stderr}")
        return False
    return True


def apply_patch(solution_file: Path, container_name: str) -> bool:
    """Apply a patch file with fallback strategies.

    First tries git apply with lenient whitespace handling.
    Falls back to using patch command if git apply fails.
    """
    # Strategy 1: git apply with whitespace fixes
    cmd = f"cd {CONTAINER_WORKSPACE} && git apply --whitespace=fix --ignore-whitespace {solution_file.name}"
    result = subprocess.run(
        ["docker", "exec", container_name, "bash", "-lc", cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True

    # Strategy 2: Try standard patch command (more lenient)
    cmd = f"cd {CONTAINER_WORKSPACE} && patch -p1 < {solution_file.name}"
    result = subprocess.run(
        ["docker", "exec", container_name, "bash", "-lc", cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print("[RunSweBenchTests] Patch applied successfully using 'patch' command")
        return True

    # Both strategies failed
    error_msg = result.stderr or result.stdout or "Unknown error"
    print(f"[RunSweBenchTests] Failed to apply patch: {error_msg}")
    print(f"[RunSweBenchTests] Patch file: {solution_file}")
    return False


def apply_test_patch(test_patch: str, container_name: str) -> bool:
    if not test_patch:
        return True

    cmd = f"cd {CONTAINER_WORKSPACE} && git apply -"
    result = subprocess.run(
        ["docker", "exec", "-i", container_name, "bash", "-lc", cmd],
        input=test_patch,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"[RunSweBenchTests] Failed to apply test patch: {result.stderr}")
        return False
    return True


def run_tests(
    container_name: str, repo: str, tests: List[str]
) -> tuple[bool, str, str]:
    if not tests:
        return True, "", ""

    # Build test command based on repo type
    if repo == "django/django":
        test_cmd = (
            f"cd {CONTAINER_WORKSPACE} && python tests/runtests.py {' '.join(tests)}"
        )
    else:
        test_cmd = f"cd {CONTAINER_WORKSPACE} && pytest -xvs {' '.join(tests)}"

    result = subprocess.run(
        ["docker", "exec", container_name, "bash", "-lc", test_cmd],
        capture_output=True,
        text=True,
        check=False,
    )

    return result.returncode == 0, result.stdout, result.stderr


def parse_test_list(test_str: str) -> List[str]:
    try:
        return json.loads(test_str)
    except json.JSONDecodeError:
        return []


def run_single_test(test_entry: Dict, solution_file: Optional[Path]) -> Dict:
    instance_id = test_entry["instance_id"]
    repo = test_entry["repo"]
    test_patch = test_entry.get("test_patch", "")
    container_name = f"swebench-test-{instance_id}"

    fail_to_pass = parse_test_list(test_entry.get("FAIL_TO_PASS", "[]"))
    pass_to_pass = parse_test_list(test_entry.get("PASS_TO_PASS", "[]"))

    result = {
        "status": TestStatus.ERROR,
        "error_type": None,
        "error_message": None,
        "fail_to_pass_passed": False,
        "pass_to_pass_passed": False,
        "fail_to_pass_output": "",
        "pass_to_pass_output": "",
        "solution_applied": False,
        "test_patch_applied": False,
    }

    try:
        # Start container
        container_id = start_container(instance_id, container_name)
        if not container_id:
            result["error_type"] = "container_start_error"
            result["error_message"] = "Failed to start Docker container"
            return result

        # Apply test patch first (from dataset) - this sets up the test files
        if test_patch:
            if not apply_test_patch(test_patch, container_name):
                result["error_type"] = "test_patch_error"
                result["error_message"] = "Failed to apply test patch from dataset"
                return result
            result["test_patch_applied"] = True
            print("[RunSweBenchTests] Test patch applied successfully")

        # Apply solution patch only if solution file exists
        if solution_file is not None and solution_file.exists():
            # Copy solution file to container
            if not copy_solution_to_container(solution_file, container_name):
                result["error_type"] = "copy_error"
                result["error_message"] = "Failed to copy solution file to container"
                return result

            # Apply patch
            if not apply_patch(solution_file, container_name):
                result["error_type"] = "patch_error"
                result["error_message"] = "Failed to apply solution patch"
                return result

            result["solution_applied"] = True
            print("[RunSweBenchTests] Solution patch applied successfully")
        else:
            print("[RunSweBenchTests] No solution file - running tests without patch")

        # Run FAIL_TO_PASS tests
        f2p_success, f2p_stdout, f2p_stderr = run_tests(
            container_name, repo, fail_to_pass
        )
        result["fail_to_pass_passed"] = f2p_success
        result["fail_to_pass_output"] = f2p_stdout + f2p_stderr

        # Run PASS_TO_PASS tests
        p2p_success, p2p_stdout, p2p_stderr = run_tests(
            container_name, repo, pass_to_pass
        )
        result["pass_to_pass_passed"] = p2p_success
        result["pass_to_pass_output"] = p2p_stdout + p2p_stderr

        # Determine overall status
        if f2p_success and p2p_success:
            result["status"] = TestStatus.PASSED
        elif not f2p_success:
            result["status"] = TestStatus.INCORRECT
            result["error_type"] = "test_failure"
            result["error_message"] = "FAIL_TO_PASS tests failed"
        else:  # f2p_success but not p2p_success
            result["status"] = TestStatus.BACKWARDS_FAILURE
            result["error_type"] = "regression"
            result["error_message"] = "PASS_TO_PASS tests failed (regression)"

    except Exception as e:
        result["error_type"] = type(e).__name__
        result["error_message"] = str(e)

    finally:
        stop_container(container_name)

    return result


def run_evaluation(
    tests_dir: Path,
    solutions_dir: Path,
    output_file: Path,
    specific_tests: Optional[List[str]] = None,
):
    """
    Run Full Evaluation for SWE-Bench-Verified
    Args:
        tests_dir: Path to the SWE-Bench Verified dataset JSON file
        solutions_dir: Path to directory containing solution diff files
        output_file: Path to output JSON file for results
        specific_tests: List of specific test IDs to run
    """
    # Load the dataset
    dataset = load_swe_bench_dataset(str(tests_dir))

    if not dataset:
        print(f"Error: No test entries found in {tests_dir}")
        sys.exit(1)

    # Filter to specific tests if provided
    if specific_tests:
        # Convert numeric IDs to SWE/X format (e.g., "0" -> "SWE/0")
        specific_set = set(f"SWE/{test_id}" for test_id in specific_tests)
        dataset = [entry for entry in dataset if entry.get("_id", "") in specific_set]
        if not dataset:
            print(f"Error: No matching test entries found for IDs: {specific_tests}")
            sys.exit(1)
        print(f"Running {len(dataset)} specific tests: {list(specific_set)}")
    else:
        print(f"Found {len(dataset)} test entries in dataset")

    print("Running tests...\n")

    # Track results
    results = []
    passed_count = 0
    incorrect_count = 0
    backwards_failure_count = 0
    error_count = 0
    evaluated_count = 0

    for test_entry in dataset:
        test_id = test_entry.get("_id", "")
        # Extract just the number from _id (e.g., "SWE/1" -> "1")
        test_num = test_id.split("/")[-1]
        instance_id = test_entry.get("instance_id", "")
        solution_file = solutions_dir / f"agent_sol_{test_num}.diff"

        evaluated_count += 1
        print(f"\n{'='*60}")
        print(f"Testing {test_id}: {instance_id}")
        print(f"{'='*60}")

        # Pass solution_file if it exists, otherwise None
        solution_to_use = solution_file if solution_file.exists() else None
        result = run_single_test(test_entry, solution_to_use)

        result_entry = {
            "task_id": test_id,
            "instance_id": instance_id,
            "repo": test_entry.get("repo", ""),
            "solution_file": str(solution_file) if solution_to_use else None,
            "test_patch_applied": result["test_patch_applied"],
            "solution_applied": result["solution_applied"],
            "status": result["status"],
            "error_type": result["error_type"],
            "error_message": result["error_message"],
            "fail_to_pass_passed": result["fail_to_pass_passed"],
            "pass_to_pass_passed": result["pass_to_pass_passed"],
        }

        results.append(result_entry)

        # Update counts
        if result["status"] == TestStatus.PASSED:
            passed_count += 1
            print(f"[PASS] Test {test_id}")
        elif result["status"] == TestStatus.INCORRECT:
            incorrect_count += 1
            print(f"[INCORRECT] Test {test_id}: {result['error_message']}")
        elif result["status"] == TestStatus.BACKWARDS_FAILURE:
            backwards_failure_count += 1
            print(f"[BACKWARDS_FAILURE] Test {test_id}: {result['error_message']}")
        else:  # TestStatus.ERROR
            error_count += 1
            print(
                f"[ERROR] Test {test_id}: {result['error_type']} - {result['error_message']}"
            )

    # Calculate statistics
    total_evaluated = evaluated_count
    failed_count = incorrect_count + backwards_failure_count + error_count
    pass_rate = (passed_count / total_evaluated * 100) if total_evaluated > 0 else 0
    incorrect_rate = (
        (incorrect_count / total_evaluated * 100) if total_evaluated > 0 else 0
    )
    backwards_failure_rate = (
        (backwards_failure_count / total_evaluated * 100) if total_evaluated > 0 else 0
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
            "backwards_failure": backwards_failure_count,
            "error": error_count,
            "incorrect_rate": round(incorrect_rate, 4),
            "backwards_failure_rate": round(backwards_failure_rate, 4),
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
    print(f"Total evaluated: {total_evaluated}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {failed_count}")
    print(f"Pass rate: {pass_rate:.2f}%")
    print()
    print("Extra Stats:")
    print(f"Incorrect: {incorrect_count} (FAIL_TO_PASS tests failed)")
    print(f"Backwards Failure: {backwards_failure_count} (PASS_TO_PASS tests failed)")
    print(f"Error: {error_count} (exceptions)")
    print(f"Incorrect rate: {incorrect_rate:.2f}%")
    print(f"Backwards failure rate: {backwards_failure_rate:.2f}%")
    print(f"Error rate: {error_rate:.2f}%")
    print("=" * 60)
    print(f"\nResults saved to: {output_file}")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run SWE-Bench Verified tests against agent solutions"
    )
    parser.add_argument(
        "--tests_dir",
        type=str,
        required=True,
        help="Path to the SWE-Bench Verified dataset JSON file",
    )
    parser.add_argument(
        "--solutions_dir",
        type=str,
        required=True,
        help="Path to directory containing solution diff files",
    )
    parser.add_argument(
        "--output_file",
        type=str,
        required=True,
        help="Path to output JSON file for results",
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

    if not tests_dir.exists():
        print(f"Error: Dataset file not found: {tests_dir}")
        sys.exit(1)

    if not solutions_dir.exists():
        print(f"Error: Solutions directory not found: {solutions_dir}")
        sys.exit(1)

    sys.exit(run_evaluation(tests_dir, solutions_dir, output_file, args.specific))
