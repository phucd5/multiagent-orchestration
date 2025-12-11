#!/usr/bin/env bash

BASE_IMAGE="ghcr.io/epoch-research/swe-bench.eval.x86_64"

if [ -z "$1" ]; then
    echo "Usage: $0 /path/to/json"
    exit 1
fi

JSON_PATH="$1"

if [ ! -f "$JSON_PATH" ]; then
    echo "File not found: $JSON_PATH"
    exit 1
fi

echo "Checking images listed in: $JSON_PATH"
echo ""

# Read JSON into array (macOS-safe)
INSTANCES=()
while IFS= read -r id; do
    INSTANCES+=("$id")
done < <(jq -r '.[].instance_id' "$JSON_PATH")

TOTAL=${#INSTANCES[@]}
MISSING=()
FOUND=0

for INSTANCE in "${INSTANCES[@]}"; do
    IMAGE="$BASE_IMAGE.$INSTANCE"
    if docker image inspect "$IMAGE" >/dev/null 2>&1; then
        echo "OK: $INSTANCE"
        FOUND=$((FOUND + 1))
    else
        echo "Missing: $INSTANCE"
        MISSING+=("$INSTANCE")
    fi
done

echo ""
echo "=== Summary ==="
echo "Total images expected:  $TOTAL"
echo "Found locally:          $FOUND"
echo "Missing:                ${#MISSING[@]}"

if [ ${#MISSING[@]} -gt 0 ]; then
    echo ""
    echo "Missing instance IDs:"
    for id in "${MISSING[@]}"; do
        echo " - $id"
    done
fi
