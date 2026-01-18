# Raspberry Pi Setup Guide for Ballot Marking Device

This guide details how to set up a Raspberry Pi as a dedicated voting terminal (kiosk).

## 1. Automated Setup (Recommended)

We have provided a script to automate the dependency installation and configuration.

1.  **Clone the repository**:
    ```bash
    cd ~
    git clone https://github.com/amanzinc/evoting.git
    cd evoting
    ```

2.  **Run the Setup Script**:
    ```bash
    chmod +x setup_rpi.sh
    ./setup_rpi.sh
    ```

3.  **Reboot**:
    ```bash
    sudo reboot
    ```

---

## 2. Manual Setup (Alternative)

If you prefer to configure things manually, follow these steps.

### A. Hardware Requirements

- **Raspberry Pi**: Model 3B+, 4, or 5 is recommended.
- **Display**: Touchscreen (official 7" or HDMI) or standard monitor + mouse.
- **MicroSD Card**: 8GB+ with Raspberry Pi OS (Desktop).

### B. Initial OS Setup

1.  Flash **Raspberry Pi OS with Desktop**.
2.  Boot up and complete the wizard.
3.  Update: `sudo apt update && sudo apt full-upgrade -y`

### C. Install Dependencies

You need Python 3's Tkinter library and `unclutter` (to hide the mouse cursor).

```bash
sudo apt install python3-tk unclutter git -y
```

### D. Install the Application

```bash
cd ~
git clone https://github.com/amanzinc/evoting.git
cd evoting
```

*Note: If you have your own fork or local files, copy them to `~/evoting`.*

## 3. Configure Kiosk Mode (Manual)

To make the application launch automatically on boot and prevent screen sleeping.

### A. Disable Screen Blanking (Sleep Mode)

1.  Open `raspi-config`:
    ```bash
    sudo raspi-config
    ```
2.  Navigate to **Display Options** > **Screen Blanking** and select **No**.
3.  Finish and Reboot if prompted.

### B. Configure Autostart (LXDE / X11)

This method works for the standard Raspberry Pi OS (X11 backend).

1.  Create/Edit the autostart file:
    ```bash
    mkdir -p ~/.config/lxsession/LXDE-pi
    nano ~/.config/lxsession/LXDE-pi/autostart
    ```

2.  **Replace** the content (or append to the end) with the following. This ensures the screensaver is off, the mouse is hidden, and the app starts.

    ```bash
    @lxpanel --profile LXDE-pi
    @pcmanfm --desktop --profile LXDE-pi
    
    # Disable Screensaver and Power Management
    @xset s noblank
    @xset s off
    @xset -dpms
    
    # Hide Mouse Cursor (idle for 0.5 seconds)
    @unclutter -idle 0.5
    
    # Start the Voting App
    @python3 /home/pi/evoting/ui_prototype.py
    ```

    *(Note: Adjust `/home/pi/` if your username is different)*

3.  **Save and Exit**: Press `Ctrl+X`, then `Y`, then `Enter`.

## 4. Optional: Hardware Specifics

### Screen Rotation
If your touchscreen is mounted vertically or upside down:
1.  Edit `config.txt`:
    ```bash
    sudo nano /boot/config.txt
    ```
2.  Add or modify `display_rotate` (0=Normal, 1=90, 2=180, 3=270):
    ```
    display_rotate=2
    ```
    *(For some newer drivers, you may need to use Screen Configuration tool in the Desktop menu instead)*.

### Read-Only Filesystem (Advanced)
For a true production kiosk, you may want to enable the Overlay File System to prevent SD card corruption on power loss.
1.  Run `sudo raspi-config`
2.  Go to **Performance Options** > **Overlay File System**.
3.  Enable it. **Warning**: Any votes recorded to `votes.log` will disappear on reboot unless you mount the log directory to a separate writable partition or USB drive!
    *   *For this prototype, keep Overlay FS **OFF** to preserve `votes.log`.*

## 5. Testing

Reboot your Pi:
```bash
sudo reboot
```

The system should boot up, load the desktop briefly, and then immediately launch the Voting App in full screen.
