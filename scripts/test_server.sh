#!/bin/bash

set -euo pipefail

PORT=8969
# Find the correct Python binary (prefer .venv, then python3, then python)
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "✗ Could not find a suitable Python interpreter (.venv/bin/python, python3, or python). Aborting test."
  exit 1
fi
CONFIG=config_dev.yaml
RUN_SCRIPT=run.sh

# Pre-check: is anything running on port 8969?
if lsof -i :$PORT -sTCP:LISTEN -t >/dev/null; then
  echo "✗ Pre-check failed: Something is already running on port $PORT. Aborting test."
  lsof -i :$PORT
  exit 1
fi

echo "============================== Testing server startup ====================="
echo "Testing server startup with $PYTHON_BIN and $CONFIG..."

bash $RUN_SCRIPT $PYTHON_BIN $CONFIG &
SERVER_PID=$!

sleep 5

if ps -p $SERVER_PID > /dev/null; then
  echo "✓ Server started successfully (PID $SERVER_PID)"
else
  echo "✗ Server failed to start"
  exit 1
fi

kill $SERVER_PID
sleep 2

# Post-check: is anything still running on port 8969?
if lsof -i :$PORT -sTCP:LISTEN -t >/dev/null; then
  echo "✗ Post-check: Server process(es) still running on port $PORT. Attempting forceful cleanup..."
  lsof -i :$PORT
  # Try to kill all processes on this port
  for pid in $(lsof -i :$PORT -sTCP:LISTEN -t); do
    echo "Killing PID $pid (SIGTERM)"
    kill $pid || true
    sleep 1
    if ps -p $pid > /dev/null; then
      echo "Killing PID $pid (SIGKILL)"
      kill -9 $pid || true
    fi
  done
  sleep 2
  # Final check
  if lsof -i :$PORT -sTCP:LISTEN -t >/dev/null; then
    echo "✗ Could not clean up all server processes on port $PORT. Manual intervention required."
    lsof -i :$PORT
    exit 1
  else
    echo "✓ All server processes on port $PORT cleaned up."
  fi
else
  echo "✓ Server stopped cleanly."
fi

echo "Test-server script completed." 