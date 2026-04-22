#!/bin/bash
# start_evoting.sh
# Wrapper called by LXDE/labwc autostart and the systemd user service.
# Ensures the working directory and venv are correct before launching.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"

# Hide the mouse cursor (LXDE may not have run unclutter yet)
if command -v unclutter > /dev/null 2>&1; then
    unclutter -idle 0.5 -root &
fi

# Ensure only one instance of this wrapper runs at a time using a file lock
exec 9>/tmp/evoting_app.lock
if ! flock -n 9; then
    echo "$(date): Another instance of start_evoting.sh is already running. Exiting to prevent hardware conflicts." >> /tmp/evoting_app.log
    exit 1
fi

# Infinite loop to automatically restart the app if it crashes
while true; do
    echo "Starting EVoting App at $(date)" >> /tmp/evoting_app.log
    
    # Run the application
    "$VENV_PYTHON" "$SCRIPT_DIR/main.py" >> /tmp/evoting_app.log 2>&1
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 42 ]; then
        echo "Developer pin entered. Exiting autostart loop." >> /tmp/evoting_app.log
        break
    fi
    
    echo "App exited or crashed. Restarting in 3 seconds..." >> /tmp/evoting_app.log
    sleep 3
done
