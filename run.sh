#!/bin/bash

# Check if Python runtime argument is provided
if [ -z "$1" ]; then
    echo "Usage: $0 /path/to/python [/path/to/config.yaml]"
    exit 1
fi

# Assign the first argument as the PYTHON_RUNTIME.
# Config is optional and falls back to CONFIG_FILE env var, then ./config.yaml.
PYTHON_RUNTIME=$1
CONFIG_FILE=${2:-${CONFIG_FILE:-config.yaml}}
LOG_FILE=${TRINETRA_LOG_FILE:-trinetra.log}

echo "Loading from config: "$CONFIG_FILE

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: config file not found: $CONFIG_FILE"
    exit 1
fi

# Extract log level from config file
LOG_LEVEL=$(grep "log_level:" "$CONFIG_FILE" | cut -d':' -f2 | tr -d ' "')
if [ -z "$LOG_LEVEL" ]; then
    echo "Warning: log_level not found in config file, using 'info' as default"
    LOG_LEVEL="info"
fi

# Run Gunicorn using the specified Python runtime and config file
"$PYTHON_RUNTIME" -m gunicorn \
  -w 1 --threads 2 \
  -b 0.0.0.0:8969 app:app \
  --log-level "$LOG_LEVEL" \
  --env "CONFIG_FILE=$CONFIG_FILE" \
  --log-file "$LOG_FILE"
