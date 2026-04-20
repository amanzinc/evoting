#!/bin/bash
# setup_rpi.sh
# Automated setup for the Ballot Marking Device (BMD) on Raspberry Pi.
# Run with: sudo bash setup_rpi.sh
#
# What this script does:
#   1. Installs system packages
#   2. Creates Python venv and installs requirements
#   3. Configures printer/USB/I2C permissions
#   4. Disables USB automount popups
#   5. Configures LightDM autologin for current user
#   6. Disables screen blanking
#   7. Writes LXDE + labwc kiosk autostart (belt-and-suspenders backup)
#   8. Installs evoting.service as a SYSTEM-level systemd service
#      (most reliable: fires on every boot after graphical.target)

set -e

# ── Detect running user ───────────────────────────────────────────────────────
# When run with sudo, SUDO_USER is the real user; fall back to current user.
APP_USER="${SUDO_USER:-$USER}"
if [ -z "$APP_USER" ] || [ "$APP_USER" = "root" ]; then
    echo "[!] Could not determine the desktop user. Set APP_USER manually."
    echo "    e.g.: sudo APP_USER=pi bash setup_rpi.sh"
    exit 1
fi
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
APP_UID="$(id -u "$APP_USER")"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python"

echo "============================================="
echo "   Ballot Marking Device — RPi Setup"
echo "============================================="
echo "  User       : $APP_USER (uid $APP_UID)"
echo "  Home       : $APP_HOME"
echo "  Project    : $PROJECT_DIR"
echo "  Venv       : $VENV_PYTHON"
echo "============================================="

if [ "$(id -u)" -ne 0 ]; then
    echo "[!] This script must be run with sudo."
    exit 1
fi

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/8] Installing system packages..."
apt-get update -q
apt-get install -y \
    python3-tk python3-pip python3-venv \
    unclutter git \
    libjpeg-dev zlib1g-dev libusb-1.0-0-dev \
    python3-pil.imagetk i2c-tools python3-smbus

# ── 2. Python venv ────────────────────────────────────────────────────────────
echo "[2/8] Setting up Python virtual environment..."
sudo -u "$APP_USER" python3 -m venv --system-site-packages "$VENV_DIR"
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --quiet -r "$PROJECT_DIR/requirements.txt"

# ── 3. Permissions ───────────────────────────────────────────────────────────
echo "[3/8] Configuring printer / USB / I2C permissions..."
usermod -a -G lp,dialout,i2c "$APP_USER"
raspi-config nonint do_i2c 0 2>/dev/null || true

cat > /etc/udev/rules.d/99-escpos.rules << 'UDEV'
# Generic POS Printers
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", ATTRS{idProduct}=="0202", MODE="0664", GROUP="lp"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0416", ATTRS{idProduct}=="5011", MODE="0664", GROUP="lp"
# STMicroelectronics POS80
SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5743", MODE="0664", GROUP="lp"
UDEV
udevadm control --reload-rules
udevadm trigger

# ── 4. Disable USB automount popups ──────────────────────────────────────────
echo "[4/8] Disabling USB automount popups..."
rm -f "$APP_HOME/.config/pcmanfm/LXDE-pi/pcmanfm.conf"
GLOBAL_CONF="/etc/xdg/pcmanfm/LXDE-pi/pcmanfm.conf"
if [ -f "$GLOBAL_CONF" ]; then
    sed -i 's/mount_on_startup=1/mount_on_startup=0/g' "$GLOBAL_CONF"
    sed -i 's/mount_removable=1/mount_removable=0/g' "$GLOBAL_CONF"
    sed -i 's/autorun=1/autorun=0/g' "$GLOBAL_CONF"
fi
if command -v gsettings >/dev/null 2>&1; then
    gsettings set org.pcmanfm.lxde-pi.volume mount-on-startup false 2>/dev/null || true
    gsettings set org.pcmanfm.lxde-pi.volume mount-removable false 2>/dev/null || true
    gsettings set org.pcmanfm.lxde-pi.volume autorun false 2>/dev/null || true
fi

# ── 5. LightDM autologin ──────────────────────────────────────────────────────
echo "[5/8] Configuring autologin for user '$APP_USER'..."
LDMCONF="/etc/lightdm/lightdm.conf"
if [ -f "$LDMCONF" ]; then
    sed -i "/\[Seat:\*\]/,/\[/ {
        s/^#*autologin-user=.*/autologin-user=$APP_USER/
        s/^#*autologin-user-timeout=.*/autologin-user-timeout=0/
    }" "$LDMCONF"
    echo "    LightDM autologin set."
else
    raspi-config nonint do_boot_behaviour B4 2>/dev/null || \
        echo "[!] raspi-config failed — enable Desktop Autologin manually."
fi

# ── 6. Screen blanking ────────────────────────────────────────────────────────
echo "[6/8] Disabling screen blanking..."
raspi-config nonint do_blanking 1 2>/dev/null || true
cat > "$APP_HOME/.Xsessionrc" << 'XSESS'
xset s off
xset -dpms
xset s noblank
XSESS
chown "$APP_USER:$APP_USER" "$APP_HOME/.Xsessionrc"

# ── 7. Desktop autostart (backup in case systemd service doesn't fire) ────────
echo "[7/8] Writing desktop autostart entries..."
chmod +x "$PROJECT_DIR/start_evoting.sh"

# LXDE (Bullseye / Bookworm-X11)
LXDE_DIR="$APP_HOME/.config/lxsession/LXDE-pi"
mkdir -p "$LXDE_DIR"
cat > "$LXDE_DIR/autostart" << LXSTART
@unclutter -idle 0.5 -root
@$PROJECT_DIR/start_evoting.sh
LXSTART
chown -R "$APP_USER:$APP_USER" "$APP_HOME/.config/lxsession"

# labwc (Bookworm Wayland)
LABWC_DIR="$APP_HOME/.config/labwc"
mkdir -p "$LABWC_DIR"
cat > "$LABWC_DIR/autostart" << 'LBSTART'
#!/bin/bash
unclutter -idle 0.5 -root &
LBSTART
echo "$PROJECT_DIR/start_evoting.sh &" >> "$LABWC_DIR/autostart"
chmod +x "$LABWC_DIR/autostart"
chown -R "$APP_USER:$APP_USER" "$LABWC_DIR"

# XDG autostart (universal fallback)
XDG_DIR="$APP_HOME/.config/autostart"
mkdir -p "$XDG_DIR"
cat > "$XDG_DIR/evoting.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=EVoting BMD
Exec=$PROJECT_DIR/start_evoting.sh
X-GNOME-Autostart-enabled=true
Hidden=false
NoDisplay=false
Comment=Ballot Marking Device
DESKTOP
chown -R "$APP_USER:$APP_USER" "$XDG_DIR"

# ── 8. System-level systemd service (primary autostart) ──────────────────────
echo "[8/8] Installing evoting system service..."

# Substitute placeholders in the service template.
SERVICE_DEST="/etc/systemd/system/evoting.service"
sed \
    -e "s|__EVOTING_USER__|$APP_USER|g" \
    -e "s|__EVOTING_DIR__|$PROJECT_DIR|g" \
    -e "s|__EVOTING_PYTHON__|$VENV_PYTHON|g" \
    -e "s|__EVOTING_HOME__|$APP_HOME|g" \
    -e "s|__EVOTING_UID__|$APP_UID|g" \
    "$PROJECT_DIR/evoting.service" > "$SERVICE_DEST"

systemctl daemon-reload
systemctl enable evoting.service
echo "    evoting.service enabled."

# RTC sync service
if [ -f "$PROJECT_DIR/evoting-rtc-sync.service" ]; then
    cp "$PROJECT_DIR/evoting-rtc-sync.service" /etc/systemd/system/evoting-rtc-sync.service
    systemctl daemon-reload
    systemctl enable evoting-rtc-sync.service
    echo "    evoting-rtc-sync.service enabled."
fi

echo ""
echo "============================================="
echo "   Setup Complete!"
echo "============================================="
echo ""
echo "  Service status : sudo systemctl status evoting"
echo "  Live logs      : sudo journalctl -u evoting -f"
echo "  Start now      : sudo systemctl start evoting"
echo ""
echo "  Reboot to verify autostart: sudo reboot"
echo ""
