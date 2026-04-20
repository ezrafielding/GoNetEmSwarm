#!/usr/bin/env bash
# Build the gonetem-satellite Docker image.
# This only needs to be run once (or after updating Dockerfile.satellite).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GONETEM_VERSION="$(cat "$SCRIPT_DIR/../gonetem/VERSION")"
IMAGE="gonetem-satellite:latest"

echo "Building $IMAGE (base: mroy31/gonetem-frr:${GONETEM_VERSION}) …"
docker build \
    --build-arg "GONETEM_VERSION=${GONETEM_VERSION}" \
    -f "$SCRIPT_DIR/Dockerfile.satellite" \
    -t "$IMAGE" \
    "$SCRIPT_DIR"
echo "Done: $IMAGE"
