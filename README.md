# Ballot Marking Device - E-Voting Prototype

Python-based prototype for a Raspberry Pi Ballot Marking Device (BMD) with USB ballot import, RFID voter flow, VVPAT printing, and encrypted export.

## Current System Overview

- Ballots arrive on USB in encrypted form under a `ballot/` tree.
- EVM decrypts AES key using hardware-bound private key (RPi only).
- Encrypted ballots are decrypted and stored locally in temporary `ballots/` directory.
- Voting runs from local decrypted ballots (not directly from USB).
- Vote logs are exported as AES-GCM encrypted files only.

## Key Features

- Hardware-bound private key unlock via machine identity (`hardware_crypto.py`).
- Encrypted ballot import from USB (`usb_ballot_import.py`).
- Preferential mode support including pair-layout ballots (e.g. `NAFS,David`).
- Preference count configurable per ballot via `number_of_preferences`.
- Challenge flow with challenge QR payload:
    - `[election_id, ballot_id, selected_commitment]`
- Vote logs include `voter_id` and `token_id` from RFID payload.
- Export uses stored AES key and writes encrypted-only output files.
- DS3231 RTC support: system clock sync from I2C RTC at app startup.

## DS3231 RTC Time Sync

If a DS3231 is connected on I2C bus 1 (default address `0x68`), the app now attempts to
sync system time from RTC during startup.

For production boot sync (required for non-root app services), enable the root one-shot
systemd service included in this repo:

```bash
sudo cp evoting-rtc-sync.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable evoting-rtc-sync.service
sudo systemctl start evoting-rtc-sync.service
sudo systemctl status evoting-rtc-sync.service
```

Useful checks on Raspberry Pi:

```bash
sudo i2cdetect -y 1
journalctl -u evoting-rtc-sync.service -b --no-pager
```

Manual RTC set helper:

```bash
source venv/bin/activate
python set_rtc_time.py
```

Set explicit RTC datetime:

```bash
python set_rtc_time.py --time "2026-04-17 14:35:00"
```

Optional flags:

- `--bus 1` (default)
- `--addr 0x68` (default)

Note: Updating Linux system time requires root/CAP_SYS_TIME; regular user services cannot set it.

## Main Files

- `main.py`: app entrypoint.
- `gui_app.py`: voting UI, RFID/session flow, print orchestration.
- `data_handler.py`: ballot parsing, commitment mapping, vote record generation.
- `ballot_manager.py`: unused/used ballot tracking and ballot file selection.
- `usb_ballot_import.py`: decrypt USB ballots and import locally.
- `printer_service.py`: VVPAT/voter/challenge printing and QR generation.
- `export_service.py`: AES-GCM encrypted export to USB.
- `generate_rpi_keys.py`: generate `private.pem`, `public.pem`, and `bmd_key.json`.
- `encrypt_usb_export.py`: standalone JSON-to-AES-GCM export encryption helper.

## Setup

### Prerequisites

- Python 3.x
- tkinter
- `python-escpos`
- `qrcode[pil]`
- `Pillow`
- `cryptography`

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
python main.py
```

## USB Ballot Input Structure (Required)

The voting USB must contain a top-level `ballot` folder.

```text
[USB_ROOT]/
└── ballot/
        ├── aes_key.enc
        ├── election_id_1/
        │   ├── candidates.json
        │   └── ballot/
        │       ├── ballot_1.enc.json
        │       └── ...
        └── election_id_2/
                ├── candidates.json
                └── ballot/
                        └── ...
```

### Import/Decryption Flow

1. Detect USB with `ballot/`.
2. Decrypt AES key from `ballot/aes_key.enc` using `private.pem`.
3. Store decrypted AES key at `ballot/aes_key.dec`.
4. Decrypt ballots and store temporary local files under:
     - `ballots/election_id_1/*.json`
     - `ballots/election_id_2/*.json`

## Preferential Ballot Behavior

- `election_type` matching is case-insensitive.
- Pair-layout ballots are auto-detected and forced into preferential mode.
- `number_of_preferences` in ballot JSON controls how many preference screens are shown.
- For pair-layout commitment mapping, selected tuple (e.g. `NAFS,NAFS`) is matched to its corresponding commitment.

## RFID Payload Formats

Both object and array payloads are supported.

### Object format

```json
{
    "token_id": "SESSION_123",
    "voter_id": "VOTER_1044A",
    "eid_vector": "election_id_1;election_id_2",
    "booth": 1
}
```

### Array format

```json
["SESSION_123", "VOTER_1044A", "election_id_1;election_id_2", 1]
```

## QR Payload Rules (Current)

- Cast receipt QR: selected commitment only.
- Challenge receipt QR: JSON array string:
    - `[election_id, ballot_id, selected_commitment]`
- Ballot ID display/print/QR usage is truncated before first comma.

## Export Encryption (Current)

No signing is performed in export.

- AES key source: `ballot/aes_key.dec`
- Algorithm: AES-GCM-256
- Output files on USB `exports/`:
    - `final_votes_<bmd_id>.enc.json`
    - `final_tokens_<bmd_id>.enc.json`

### BMD ID resolution for filenames

1. `EVOTING_BMD_ID` env var
2. `/etc/evoting/bmd_id`
3. `ballot/aes_key.dec` (`bmd_id`)
4. fallback `UNKNOWN_BMD`

## Key Generation Output

Running:

```bash
python generate_rpi_keys.py
```

creates:

- `private.pem`
- `public.pem`
- `bmd_key.json` in format:

```json
[
    {
        "bmd_id": 1,
        "rsa_public_key_pem": "-----BEGIN PUBLIC KEY-----...",
        "is_active": true,
        "key_version": 1,
        "created_at": "2026-03-19T00:00:00.000Z"
    }
]
```

## Standalone Export Encryption Script

Use `encrypt_usb_export.py` to encrypt JSON/log files with stored AES key:

```bash
python encrypt_usb_export.py /logs/votes.json --out-dir /media/pi/USB/exports --prefix final_votes
python encrypt_usb_export.py /logs/tokens.log --out-dir /media/pi/USB/exports --prefix final_tokens
```
