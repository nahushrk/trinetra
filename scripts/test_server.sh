#!/bin/bash

set -euo pipefail

PORT=8969
CONFIG=config_dev.yaml
RUN_SCRIPT=run.sh
PYTHON_BIN=".venv/bin/python"

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

echo "============================== Testing server endpoints ====================="

# Test home page
echo "Testing home page..."
if curl -f -s -o /dev/null -w "%{http_code}" http://localhost:$PORT/; then
  echo "✓ Home page loaded successfully"
  
  # Check if home page has at least one item using the API endpoint
  HOME_PAGE_DATA=$(curl -s http://localhost:$PORT/api/stl_files)
  FOLDER_COUNT=$(echo "$HOME_PAGE_DATA" | jq '.pagination.total_folders // 0')
  if [ "$FOLDER_COUNT" -gt 0 ]; then
    echo "✓ Home page has $FOLDER_COUNT folder(s)"
  else
    echo "✗ Home page has no folders"
  fi
else
  echo "✗ Home page failed to load"
  curl -v http://localhost:$PORT/ 2>&1 || true
fi

# Test gcode files page
echo "Testing gcode files page..."
if curl -f -s -o /dev/null -w "%{http_code}" http://localhost:$PORT/gcode_files; then
  echo "✓ Gcode files page loaded successfully"
  
  # Check if gcode page has at least one item using the API endpoint
  GCODE_PAGE_DATA=$(curl -s http://localhost:$PORT/api/gcode_files)
  FILE_COUNT=$(echo "$GCODE_PAGE_DATA" | jq '.pagination.total_files // 0')
  if [ "$FILE_COUNT" -gt 0 ]; then
    echo "✓ Gcode files page has $FILE_COUNT file(s)"
  else
    echo "✗ Gcode files page has no files"
  fi
else
  echo "✗ Gcode files page failed to load"
  curl -v http://localhost:$PORT/gcode_files 2>&1 || true
fi

# Test search on home page
echo "Testing search on home page with term 'box'..."
SEARCH_RESPONSE=$(curl -s "http://localhost:$PORT/search?q=box")
SEARCH_RESULT_COUNT=$(echo "$SEARCH_RESPONSE" | jq '.metadata.matches // 0')
if [ "$SEARCH_RESULT_COUNT" -gt 0 ]; then
  echo "✓ Home page search returned $SEARCH_RESULT_COUNT result(s)"
else
  echo "✗ Home page search returned no results"
fi

# Test search on gcode page
echo "Testing search on gcode page with term 'box'..."
GCODE_SEARCH_RESPONSE=$(curl -s "http://localhost:$PORT/search_gcode?q=box")
GCODE_SEARCH_RESULT_COUNT=$(echo "$GCODE_SEARCH_RESPONSE" | jq '.metadata.matches // 0')
if [ "$GCODE_SEARCH_RESULT_COUNT" -gt 0 ]; then
  echo "✓ Gcode page search returned $GCODE_SEARCH_RESULT_COUNT result(s)"
else
  echo "✗ Gcode page search returned no results"
fi

# Test stats page
echo "Testing stats page..."
if curl -f -s -o /dev/null -w "%{http_code}" http://localhost:$PORT/stats; then
  echo "✓ Stats page loaded successfully"
else
  echo "✗ Stats page failed to load"
  curl -v http://localhost:$PORT/stats 2>&1 || true
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