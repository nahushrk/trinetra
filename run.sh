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

# Run the server using run.py with the specified config file
$PYTHON_RUNTIME run.py --config $CONFIG_FILE
