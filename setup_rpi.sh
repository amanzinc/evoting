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
sudo apt-get install -y python3-tk unclutter git python3-pip python3-venv libjpeg-dev zlib1g-dev libusb-1.0-0-dev python3-pil.imagetk i2c-tools python3-smbus

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

# 5. Make launch wrapper executable
echo "[*] Making start_evoting.sh executable..."
chmod +x "$PROJECT_DIR/start_evoting.sh"

# 6. Configure autologin for the evoting user
# Works for both Bullseye and Bookworm LightDM configurations.
echo "[*] Configuring LightDM autologin for user 'evoting'..."
LDMCONF="/etc/lightdm/lightdm.conf"
if [ -f "$LDMCONF" ]; then
    # Uncomment and set autologin-user in the [Seat:*] section
    sudo sed -i '/\[Seat:\*\]/,/\[/ {
        s/^#*autologin-user=.*/autologin-user=evoting/
        s/^#*autologin-user-timeout=.*/autologin-user-timeout=0/
    }' "$LDMCONF"
    echo "[*] LightDM autologin configured."
else
    echo "[!] lightdm.conf not found; trying raspi-config..."
    sudo raspi-config nonint do_boot_behaviour B4 2>/dev/null || \
        echo "[!] raspi-config also failed — please enable Desktop Autologin manually."
fi

# 7. Disable screen blanking / power saving
echo "[*] Disabling screen blanking..."
sudo raspi-config nonint do_blanking 1 2>/dev/null || true
# Also set via X11 in case raspi-config doesn't cover Wayland
XINITRC_EXTRA="/home/evoting/.Xsessionrc"
cat > "$XINITRC_EXTRA" << 'XSESS'
xset s off
xset -dpms
xset s noblank
XSESS
chown evoting:evoting "$XINITRC_EXTRA" 2>/dev/null || true

# 8. LXDE kiosk autostart (Bullseye + Bookworm-X11)
# Replaces the normal desktop session with just unclutter + our app.
echo "[*] Writing LXDE kiosk autostart..."
LXDE_DIR="/home/evoting/.config/lxsession/LXDE-pi"
mkdir -p "$LXDE_DIR"
cat > "$LXDE_DIR/autostart" << LXSTART
@unclutter -idle 0.5 -root
@$PROJECT_DIR/start_evoting.sh
LXSTART
chown -R evoting:evoting "/home/evoting/.config/lxsession" 2>/dev/null || true

# 9. labwc autostart (Bookworm Wayland — Raspberry Pi OS 64-bit default)
echo "[*] Writing labwc kiosk autostart..."
LABWC_DIR="/home/evoting/.config/labwc"
mkdir -p "$LABWC_DIR"
cat > "$LABWC_DIR/autostart" << 'LBSTART'
#!/bin/bash
unclutter -idle 0.5 -root &
LBSTART
# Append the actual app launch line without single-quote quoting issues
echo "$PROJECT_DIR/start_evoting.sh &" >> "$LABWC_DIR/autostart"
chmod +x "$LABWC_DIR/autostart"
chown -R evoting:evoting "$LABWC_DIR" 2>/dev/null || true

# 10. Install systemd user service
# loginctl enable-linger lets user services start at boot (before login).
echo "[*] Installing and enabling evoting systemd user service..."
SERVICE_DIR="/home/evoting/.config/systemd/user"
mkdir -p "$SERVICE_DIR"
cp "$PROJECT_DIR/evoting.service" "$SERVICE_DIR/evoting.service"
chown -R evoting:evoting "$SERVICE_DIR"

# Enable linger so the user bus starts at boot
sudo loginctl enable-linger evoting

# Enable the service as the evoting user
sudo -u evoting XDG_RUNTIME_DIR="/run/user/$(id -u evoting)" \
    systemctl --user enable evoting.service 2>/dev/null || \
    echo "[!] systemctl --user enable failed; service will be started via autostart instead."

echo "============================================="
echo "   Full Setup Complete!"
echo "============================================="
echo ""
echo "Next steps:"
echo "  1. Reboot:  sudo reboot"
echo "  2. On first boot the provisioning wizard will launch automatically."
echo "  3. Follow the on-screen steps to assign BMD ID and print public key."
echo "  4. On all subsequent boots the voting app starts directly."
echo ""
echo "To view app logs after boot:"
echo "  journalctl --user -u evoting -f"
echo "  # or:  cat /tmp/evoting_app.log"
