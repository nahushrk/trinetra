#!/bin/bash

is_raspberry_pi() {
    if grep -q "Raspberry Pi" /proc/cpuinfo; then
        return 0
    else
        return 1
    fi
}

# Exit if not running on a Raspberry Pi
if ! is_raspberry_pi; then
    echo "This script is designed to run on a Raspberry Pi only."
    exit 1
fi

APP_DIR=~/trinetra
BASE_DIR=~/trinetra-data
VENV_DIR=$APP_DIR/.venv
SYSTEMD_FILE=/etc/systemd/system/trinetra.service

if [ "$(pwd)" != "$APP_DIR" ]; then
    echo "Error: This script must be run from $APP_DIR"
    exit 1
fi

if ! python3 --version &>/dev/null; then
    echo "Error: Python 3 is not installed."
    exit 1
fi

# Create virtual environment using python3 -m venv
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python 3 virtual environment..."
    python3 -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment."
        exit 1
    fi
else
    echo "Virtual environment already exists."
fi

source "$VENV_DIR/bin/activate"

if [ -f "pyproject.toml" ]; then
    echo "Installing required Python packages using pip..."
    "$VENV_DIR/bin/pip" install .
    if [ $? -ne 0 ]; then
        echo "Error: Failed to install Python packages."
        deactivate
        exit 1
    fi
else
    echo "Error: pyproject.toml not found!"
    deactivate
    exit 1
fi

deactivate

if [ ! -d "$BASE_DIR" ]; then
    echo "Creating Trinetra base directory: $BASE_DIR"
    mkdir -p "$BASE_DIR"
else
    echo "$BASE_DIR already exists."
fi

if [ ! -f "$SYSTEMD_FILE" ]; then
    echo "Creating systemd service file..."
    sudo bash -c "cat > $SYSTEMD_FILE" <<EOL
[Unit]
Description=Trinetra Service
After=network-online.target
Requires=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/trinetra
ExecStart=/home/pi/trinetra/run.sh $VENV_DIR/bin/python /home/pi/trinetra/config.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL
else
    echo "Systemd service file already exists."
fi

echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Enabling Trinetra service..."
sudo systemctl enable trinetra

echo "Starting Trinetra service..."
sudo systemctl start trinetra

echo "Installation complete. Trinetra service is now running."
