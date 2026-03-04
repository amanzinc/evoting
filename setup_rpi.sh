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

echo "[*] Creating udev rules for raw USB printer access..."
cat << EOF | sudo tee /etc/udev/rules.d/99-escpos.rules
# Generic POS Printers
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", ATTRS{idProduct}=="0202", MODE="0664", GROUP="lp"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0416", ATTRS{idProduct}=="5011", MODE="0664", GROUP="lp"
# STMicroelectronics POS80
SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5743", MODE="0664", GROUP="lp"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger

# 4. Disable USB Automount Popups (PCManFM / Wayfire)
echo "[*] Disabling 'Show options for removable media' GUI popup..."

# Remove potentially corrupted local config so it regenerates from global
if [ -f "$HOME/.config/pcmanfm/LXDE-pi/pcmanfm.conf" ]; then
    rm "$HOME/.config/pcmanfm/LXDE-pi/pcmanfm.conf"
fi

# Apply to global configuration safely using sed
# This is the exact equivalent of:
# File Manager -> Edit > Preferences > Volume Management > Uncheck "Show available options for removable media when they are inserted"
GLOBAL_CONF="/etc/xdg/pcmanfm/LXDE-pi/pcmanfm.conf"
if [ -f "$GLOBAL_CONF" ]; then
    sudo sed -i 's/mount_on_startup=1/mount_on_startup=0/g' "$GLOBAL_CONF"
    sudo sed -i 's/mount_removable=1/mount_removable=0/g' "$GLOBAL_CONF"
    sudo sed -i 's/autorun=1/autorun=0/g' "$GLOBAL_CONF"
fi

# For newer Bookworm OS (Wayland / Wayfire), disable pcmanfm-qt automounts via dconf/gsettings if applicable
if command -v gsettings >/dev/null 2>&1; then
    gsettings set org.pcmanfm.lxde-pi.volume mount-on-startup false 2>/dev/null || true
    gsettings set org.pcmanfm.lxde-pi.volume mount-removable false 2>/dev/null || true
    gsettings set org.pcmanfm.lxde-pi.volume autorun false 2>/dev/null || true
fi

echo "============================================="
echo "   Setup Complete!"
echo "============================================="
echo "Please reboot your Raspberry Pi for changes to take effect:"
echo "  sudo reboot"
