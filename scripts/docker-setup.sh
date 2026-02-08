#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
BASE_DIR_RAW="$(
    sed -nE 's/^x-trinetra-host-base-dir:[[:space:]]*&trinetra_host_base_dir[[:space:]]+(.+)$/\1/p' \
        "$COMPOSE_FILE" | head -n 1
)"
BASE_DIR_RAW="${BASE_DIR_RAW%\"}"
BASE_DIR_RAW="${BASE_DIR_RAW#\"}"
BASE_DIR_RAW="${BASE_DIR_RAW%\'}"
BASE_DIR_RAW="${BASE_DIR_RAW#\'}"

if [[ -z "$BASE_DIR_RAW" ]]; then
    BASE_DIR_RAW="./trinetra-data"
    echo "Warning: could not read x-trinetra-host-base-dir from docker-compose.yml, using $BASE_DIR_RAW"
fi

if [[ "$BASE_DIR_RAW" = /* ]]; then
    BASE_DIR="$BASE_DIR_RAW"
else
    BASE_DIR="$ROOT_DIR/$BASE_DIR_RAW"
fi
MODELS_DIR="$BASE_DIR/models"
GCODES_DIR="$BASE_DIR/gcodes"
SYSTEM_DIR="$BASE_DIR/system"
CONFIG_TEMPLATE="$ROOT_DIR/config.docker.yaml"
CONFIG_FILE="$SYSTEM_DIR/config.yaml"

if ! command -v docker >/dev/null 2>&1; then
    echo "Error: docker is not installed or not on PATH."
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
else
    echo "Error: docker compose (plugin or binary) is required."
    exit 1
fi

mkdir -p "$MODELS_DIR" "$GCODES_DIR" "$SYSTEM_DIR"

if [[ ! -f "$CONFIG_FILE" ]]; then
    cp "$CONFIG_TEMPLATE" "$CONFIG_FILE"
fi

echo "Docker directories are ready:"
echo "  Base   : $BASE_DIR"
echo "  Models : $MODELS_DIR"
echo "  G-codes: $GCODES_DIR"
echo "  System : $SYSTEM_DIR"
echo "Config file:"
echo "  $CONFIG_FILE"

if [[ "${1:-}" == "--up" ]]; then
    echo "Starting Trinetra with Docker Compose..."
    "${COMPOSE_CMD[@]}" -f "$ROOT_DIR/docker-compose.yml" up -d --build
    echo "Trinetra is starting. Open http://localhost:${TRINETRA_PORT:-8969}"
fi
