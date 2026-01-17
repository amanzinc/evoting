# Raspberry Pi Setup Instructions

To run the Ballot Marking Device (BMD) prototype on your Raspberry Pi, follow these steps:

## 1. System Requirements
- Raspberry Pi (3, 4, or 5 recommended)
- Raspberry Pi OS (with Desktop)
- Touchscreen display or Monitor + Mouse

## 2. Install Dependencies
Open a terminal and run:
```bash
sudo apt update
sudo apt install python3-tk git -y
```

## 3. Clone and Run
```bash
cd ~
git clone https://github.com/amanzinc/evoting.git
cd evoting
python3 ui_prototype.py
```

## 4. (Optional) Auto-start in Kiosk Mode
To make it launch automatically on boot:
1. Create a service or add to `.bashrc` (if auto-login is enabled).
2. Or use the built-in autostart:
   `nano /home/pi/.config/lxsession/LXDE-pi/autostart`
   Add the line:
   `@python3 /home/pi/evoting/ui_prototype.py`
