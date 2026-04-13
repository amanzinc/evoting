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

# Log output to a rolling file in /tmp so it doesn't fill the SD card
exec "$VENV_PYTHON" "$SCRIPT_DIR/main.py" >> /tmp/evoting_app.log 2>&1
