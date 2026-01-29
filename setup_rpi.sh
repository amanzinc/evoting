#!/bin/bash

# setup_rpi.sh
# Automated setup for the Ballot Marking Device (BMD) on Raspberry Pi
# Run this script on the Raspberry Pi:
# ./setup_rpi.sh

set -e # Exit on error

echo "============================================="
echo "   Ballot Marking Device - RPi Setup Script  "
echo "============================================="

# 1. Update and Install Dependencies
echo "[*] Updating package lists..."
sudo apt-get update

echo "[*] Installing dependencies (python3-tk, unclutter, git, python3-pip)..."
sudo apt-get install -y python3-tk unclutter git python3-pip libjpeg-dev zlib1g-dev libusb-1.0-0-dev

# 2. Install Python Packages
echo "[*] Installing Python libraries (escpos)..."
# Get the absolute path of the current directory (project root)
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Install project requirements
pip3 install -r "$PROJECT_DIR/requirements.txt" --break-system-packages

# Install RFID & Crypto Dependencies explicitly if not in requirements
echo "[*] Installing RFID & Crypto modules..."
pip3 install adafruit-circuitpython-pn532 adafruit-blinka RPi.GPIO cryptography --break-system-packages

# 3. Configure Screen Blanking (Disable Sleep)
echo "[*] Disabling screen blanking (Sleep Mode)..."
# Using raspi-config non-interactive mode
# 0 = enable, 1 = disable. Confusingly, command is 'do_blanking'
if command -v raspi-config >/dev/null 2>&1; then
    sudo raspi-config nonint do_blanking 1
    echo "    - Screen blanking disabled via raspi-config."
else
    echo "    ! raspi-config not found. Skipping system-level blanking config (autostart will handle it)."
fi

# 3. Configure Autostart for Kiosk Mode
echo "[*] Configuring Autostart (Kiosk Mode)..."

AUTOSTART_DIR="$HOME/.config/lxsession/LXDE-pi"
AUTOSTART_FILE="$AUTOSTART_DIR/autostart"

# Ensure directory exists
mkdir -p "$AUTOSTART_DIR"

# Backup existing autostart if it exists and isn't already backed up
if [ -f "$AUTOSTART_FILE" ] && [ ! -f "$AUTOSTART_FILE.bak" ]; then
    cp "$AUTOSTART_FILE" "$AUTOSTART_FILE.bak"
    echo "    - Backed up existing autostart to $AUTOSTART_FILE.bak"
fi

# Get the absolute path of the current directory (project root)
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
APP_SCRIPT="$PROJECT_DIR/main.py"

echo "    - App path detected: $APP_SCRIPT"

# Write new autostart file
cat <<EOF > "$AUTOSTART_FILE"
@lxpanel --profile LXDE-pi
@pcmanfm --desktop --profile LXDE-pi
@xscreensaver -no-splash

# Disable Screensaver and Power Management
@xset s noblank
@xset s off
@xset -dpms

# Hide Mouse Cursor (idle for 0.5 seconds)
@unclutter -idle 0.5

# Start the Voting App
@python3 $APP_SCRIPT
EOF

echo "    - Autostart file updated."

echo "============================================="
echo "   Setup Complete!"
echo "============================================="
echo "Please reboot your Raspberry Pi for changes to take effect:"
echo "  sudo reboot"
