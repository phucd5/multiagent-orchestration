import argparse
import json
from pathlib import Path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract test cases from the HumanEval dataset and save them as individual files."
    )
    parser.add_argument(
        "--dataset_path",
        type=str,
        required=True,
        help="Path to the dataset file (e.g., HumanEval.jsonl)",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        required=True,
        help="Directory where test files will be saved",
    )

    args = parser.parse_args()

    jsonl_path = Path(args.dataset_path)
    output_dir = Path(args.output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line.strip())

            task_id = data["task_id"]
            test_code = data["test"]

            task_number = task_id.split("/")[-1]

            filename = f"sol_{task_number}.py"
            output_path = output_dir / filename

            # Write test code to file
            with open(output_path, "w", encoding="utf-8") as test_file:
                test_file.write(test_code)

            print(f"Created: {filename}")

    print(f"\nAll test files have been generated in: {output_dir}")
