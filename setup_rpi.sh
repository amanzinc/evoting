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

echo "[*] Installing dependencies..."
sudo apt-get install -y python3-tk unclutter git python3-pip python3-venv libjpeg-dev zlib1g-dev libusb-1.0-0-dev python3-pil.imagetk

# 2. Setup Virtual Environment and Install Python Packages
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="$PROJECT_DIR/venv"

echo "[*] Creating virtual environment (with system site packages)..."
python3 -m venv --system-site-packages "$VENV_DIR"

echo "[*] Installing Python libraries..."
# Install project requirements into venv
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# 3. Configure Printer Permissions
echo "[*] Adding user to 'lp' and 'dialout' groups for printer and serial access..."
sudo usermod -a -G lp $USER
sudo usermod -a -G dialout $USER

echo "============================================="
echo "   Setup Complete!"
echo "============================================="
echo "Please reboot your Raspberry Pi for changes to take effect:"
echo "  sudo reboot"
