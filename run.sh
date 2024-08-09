#!/bin/bash

# Check if both Python runtime and config file arguments are provided
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: $0 /path/to/python /path/to/config.yaml"
    exit 1
fi

# Assign the first argument as the PYTHON_RUNTIME and the second as CONFIG_FILE
PYTHON_RUNTIME=$1
CONFIG_FILE=$2

echo "Loading from config: "$CONFIG_FILE

# Run Gunicorn using the specified Python runtime and config file
$PYTHON_RUNTIME -m gunicorn \
  -w 1 --threads 2 \
  -b 0.0.0.0:8969 app:app \
  --log-level info \
  --env CONFIG_FILE=$CONFIG_FILE \
  --log-file gunicorn.log
