#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${TRINETRA_MODELS_DIR:-$ROOT_DIR/trinetra-data/3dfiles}"
GCODES_DIR="${TRINETRA_GCODES_DIR:-$ROOT_DIR/printer_data/gcodes}"
DB_DIR="${TRINETRA_DB_DIR:-$ROOT_DIR/trinetra-data/db}"

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

mkdir -p "$MODELS_DIR" "$GCODES_DIR" "$DB_DIR"

echo "Docker directories are ready:"
echo "  Models : $MODELS_DIR"
echo "  G-codes: $GCODES_DIR"
echo "  DB     : $DB_DIR"

if [[ "${1:-}" == "--up" ]]; then
    echo "Starting Trinetra with Docker Compose..."
    "${COMPOSE_CMD[@]}" -f "$ROOT_DIR/docker-compose.yml" up -d --build
    echo "Trinetra is starting. Open http://localhost:${TRINETRA_PORT:-8969}"
fi
