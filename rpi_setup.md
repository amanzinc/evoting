# Raspberry Pi Setup Guide for Ballot Marking Device

This guide details how to set up a Raspberry Pi for the Ballot Marking Device.

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

3.  **Generate Hardware-Bound RSA Keys**:
    Once dependencies are installed, you must generate the lock for this specific Raspberry Pi.
    ```bash
    source venv/bin/activate
    python generate_rpi_keys.py
    ```
    *This will generate `public.pem` (copy this to your PC to encrypt ballots) and `private.pem` (locked to this Pi's MAC/CPU).*

4.  **Reboot**:
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
0
### C. Install Dependencies

You need Python 3's Tkinter library, `python3-venv` for the virtual environment, and `unclutter` (to hide the mouse cursor).

```bash
sudo apt install python3-tk python3-venv unclutter git -y
```

### D. Install the Application

```bash
cd ~
git clone https://github.com/amanzinc/evoting.git
cd evoting
```

*Note: If you have your own fork or local files, copy them to `~/evoting`.*

### E. Setup Virtual Environment & Python Packages

Once the repository is downloaded, you need to create a virtual environment and install the required Python libraries via pip.

```bash
cd ~/evoting
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt
```

*Note: The `--system-site-packages` flag is required so the virtual environment can interact directly with system-level libraries like `python3-tk` and `python3-pil.imagetk` installed via apt.*

### F. Configure User Permissions
To ensure the application has permission to directly communicate with USB printers, add your user to the appropriate groups:

```bash
sudo usermod -a -G lp $USER
sudo usermod -a -G dialout $USER
```
*(You will need to reboot or log out and log back in for group changes to take effect).*

You also need to allow raw USB access to the printer for `python-escpos`:
```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5743", MODE="0664", GROUP="lp"' | sudo tee /etc/udev/rules.d/99-escpos.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### G. USB-to-Parallel Thermal Printers
If your 58 mm thermal printer appears on the Pi as something like `ICS Advent Parallel Adaptor`, the operating system is detecting the USB-to-parallel bridge rather than the printer brand. That is still usable as long as the printer speaks ESC/POS over the adapter.

1. Confirm the adapter is detected:
    ```bash
    lsusb
    dmesg | grep -i -E 'lp|usblp|parallel|usb'
    ls -l /dev/usb/lp* /dev/lp* 2>/dev/null
    ```
2. If no `lp` device appears, load the printer driver and re-check:
    ```bash
    sudo modprobe usblp
    ls -l /dev/usb/lp* /dev/lp* 2>/dev/null
    ```
3. Set the app to use the raw device file directly. Replace the path with whichever device exists on your Pi:
    ```bash
    export EVOTING_PRINTER_DEVICE=/dev/lp0
    export EVOTING_PRINTER_PROFILE=default
    ```
4. Test the printer directly from the Pi without adding any extra project files:
    ```bash
    cd ~/evoting
    source venv/bin/activate
    python - <<'PY'
from escpos.printer import File

p = File('/dev/lp0', profile='default')
p.text('EVOTING PRINTER TEST\n')
p.text('Raw /dev/lp0 path OK\n\n\n')
p.cut(mode='FULL')
PY
    ```
5. If your printer is actually on `/dev/usb/lp0`, change the path in both `EVOTING_PRINTER_DEVICE` and the Python snippet.
6. If text prints but cutting or formatting is wrong, keep the same device path and try a different profile value supported by `python-escpos`.

The app now checks `EVOTING_PRINTER_DEVICE` first, then falls back to `/dev/usb/lp0` through `/dev/usb/lp5` and `/dev/lp0` through `/dev/lp5`.

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
For a true production deployment, you may want to enable the Overlay File System to prevent SD card corruption on power loss.
1.  Run `sudo raspi-config`
2.  Go to **Performance Options** > **Overlay File System**.
3.  Enable it. **Warning**: Any votes recorded to `votes.log` will disappear on reboot unless you mount the log directory to a separate writable partition or USB drive!
    *   *For this prototype, keep Overlay FS **OFF** to preserve `votes.log`.*

## 5. Running the Application

After installation (whether automated or manual), you should use the virtual environment to run the app.

1.  **Activate Virtual Environment**:
    ```bash
    cd ~/evoting
    source venv/bin/activate
    ```
2.  **Hide the Mouse Cursor** (Optional, for kiosk feel):
    ```bash
    unclutter -idle 0.5 &
    ```
3.  **Run the App**:
    ```bash
    python main.py
    ```
