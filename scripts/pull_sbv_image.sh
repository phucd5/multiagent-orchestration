#!/usr/bin/env bash

BASE_IMAGE="ghcr.io/epoch-research/swe-bench.eval.x86_64"

RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
NC="\033[0m"

if [ -z "$1" ]; then
    echo "Usage: $0 /path/to/json [parallel]"
    exit 1
fi

JSON_PATH="$1"
PARALLEL="${2:-8}"  # default parallelism

if [ ! -f "$JSON_PATH" ]; then
    echo "File not found: $JSON_PATH"
    exit 1
fi

# Load instance IDs into an array (macOS compatible)
INSTANCES=()
while IFS= read -r line; do
    INSTANCES+=("$line")
done < <(jq -r '.[].instance_id' "$JSON_PATH")

TOTAL=${#INSTANCES[@]}
FAILED_IDS=()

echo "Using parallelism: $PARALLEL"
echo "Total images to pull: $TOTAL"

pull_and_test() {
    INSTANCE="$1"
    IMAGE="$BASE_IMAGE.$INSTANCE"
    CONTAINER="test_$INSTANCE"

    echo "Pulling $IMAGE"

    # Pull the image
    if ! docker pull "$IMAGE" >/dev/null 2>&1; then
        echo -e "${RED}Failed pull: $INSTANCE${NC}"
        echo "$INSTANCE" >> failed.tmp
        return
    fi

    # Start container
    docker run --platform linux/amd64 -d --name "$CONTAINER" "$IMAGE" \
        tail -f /dev/null >/dev/null 2>&1

    # Test Python inside container
    if docker exec "$CONTAINER" bash -lc "python -V" >/dev/null 2>&1; then
        echo -e "${GREEN}OK: $INSTANCE${NC}"
    else
        echo -e "${RED}Broken: $INSTANCE${NC}"
        echo "$INSTANCE" >> failed.tmp
    fi

    docker stop "$CONTAINER" >/dev/null 2>&1
    docker rm "$CONTAINER" >/dev/null 2>&1
}

export -f pull_and_test
export BASE_IMAGE RED GREEN NC

# Empty the failure list
> failed.tmp

# Run pulls in parallel
printf "%s\n" "${INSTANCES[@]}" | xargs -n 1 -P "$PARALLEL" bash -c 'pull_and_test "$0"'

# Load failures
if [ -s failed.tmp ]; then
    while IFS= read -r line; do
        FAILED_IDS+=("$line")
    done < failed.tmp
fi

FAILED=${#FAILED_IDS[@]}
SUCCESS=$(( TOTAL - FAILED ))

echo -e "\n${YELLOW}=== Summary ===${NC}"
echo "Total images:      $TOTAL"
echo -e "${GREEN}Successful:         $SUCCESS${NC}"
echo -e "${RED}Failed:             $FAILED${NC}"

if [ "$FAILED" -gt 0 ]; then
    echo -e "\n${RED}Failed instance IDs:${NC}"
    for id in "${FAILED_IDS[@]}"; do
        echo " - $id"
    done
fi

rm -f failed.tmp
