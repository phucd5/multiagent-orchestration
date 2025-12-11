import random
import json
from collections import defaultdict

from datasets import load_dataset

if __name__ == "__main__":
    random.seed(42)
    output_path = "swe_verified.json"

    # Load dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Verified")
    test = list(ds["test"])

    # Organize by difficulty
    buckets = defaultdict(list)
    for item in test:
        buckets[item["difficulty"]].append(item)

    # Proportional sampling to get exactly 100
    sample_sizes = {
        "15 min - 1 hour": 25,
        "<15 min fix": 25,
    }

    # no image available
    excluded_ids = {
        "django__django-15732",
        "sympy__sympy-23950",
        "sphinx-doc__sphinx-7757",
        "django__django-12155",
        "pytest-dev__pytest-5787",
        "sphinx-doc__sphinx-9258",
        "django__django-17029",
        "django__django-13417",
        "django__django-16642",
        "django__django-14404",
    }

    sampled = []
    for diff, items in buckets.items():
        n = sample_sizes.get(diff, 0)
        if n >= len(items):
            chosen = items
        else:
            chosen = random.sample(items, n)

        # Replace excluded items with other items from the same bucket
        chosen_ids = {item["instance_id"] for item in chosen}
        remaining = [
            item
            for item in items
            if item["instance_id"] not in chosen_ids
            and item["instance_id"] not in excluded_ids
        ]

        final_chosen = []
        for item in chosen:
            if item["instance_id"] in excluded_ids:
                if remaining:
                    replacement = remaining.pop(0)
                    final_chosen.append(replacement)
                # If no replacement available, skip the excluded item
            else:
                final_chosen.append(item)

        sampled.extend(final_chosen)

    # Add consistent ids SWE/0, SWE/1, ...
    final = []
    for i, item in enumerate(sampled):
        new_item = dict(item)
        new_item["_id"] = f"SWE/{i}"
        final.append(new_item)

    # Save
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2)

    print(f"Saved {len(final)} items to {output_path}")
