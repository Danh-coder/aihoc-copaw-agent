#!/usr/bin/env bash
# Deploy QwenPaw: build Docker image then start containers.
# Run from repo root: bash scripts/deploy.sh [IMAGE_TAG]
# Example: bash scripts/deploy.sh agentscope/qwenpaw:latest
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

IMAGE_TAG="${1:-agentscope/qwenpaw:latest}"

echo "[deploy] Step 1: Building Docker image: $IMAGE_TAG"
bash scripts/docker_build.sh "$IMAGE_TAG"

echo "[deploy] Step 2: Starting containers with docker compose"
docker compose -f docker-compose-with-zalo.yml up -d

echo "[deploy] Done. QwenPaw is running."
