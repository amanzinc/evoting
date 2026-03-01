# Ballot Marking Device - E-Voting Prototype

This project is a Python-based prototype for a Ballot Marking Device (BMD), designed to demonstrate a secure, user-friendly, and verifiable electronic voting system compliant with VVPAT standards.

## Project Goals

1.  **Transparency**: Open-source implementation of voting logic.
2.  **Flexibility**: Dynamic candidate loading from external JSON configuration (`candidates.json`).
3.  **Auditability**: Secure text-based logging (`votes.log`) and physical paper trails (VVPAT & Voter Receipt).
4.  **Accessibility**: User interface designed for clarity, supporting both single-choice and preferential (ranked) voting modes.

## Key Features

- **Dynamic Candidate Loading**: Candidates are loaded from `candidates.json`, supporting arbitrary election IDs, candidate numbers, and serial ordering.
- **Hardware-Bound RSA Encryption**: Ballots (`.json`) are securely encrypted into chunks using a 2048-bit RSA Public Key. The EVM decrypts them dynamically during boot using a Private Key that is physically locked to the Raspberry Pi's MAC Address and CPU Serial Number via AES-256. SD card cloning is impossible.
- **Dual Receipt System**:
    - **VVPAT Slip**: Printed first, deposited in the box. Contains Station ID, Ballot ID, Session Time, Name/Number, and dual QR codes (with cryptographic commitments).
    - **Voter Receipt**: Printed second, given to voter. Contains Session Time, Choice, and QR codes.
- **Vote Logging**: Every vote is logged to `votes.json` in a structured JSON Lines format with a precise timestamp, cryptographic commitment hash, and candidate details.
- **Dual Voting Modes**:
    - **Normal Voting**: Standard single-choice selection.
    - **Preferential Voting**: Ranked choice voting (select 1st, 2nd, 3rd preference).
- **Dynamic UI**: 
    - Automatically adjusts layout based on the number of candidates.
    - **NOTA Support**: "None of the Above" (or candidate "NAFS") is automatically handled and displayed distinctively.

## Hardware Support
- **Thermal Printer**: Supports ESC/POS printers (e.g., Epson TM-T88IV) for generating receipts.
- **Raspberry Pi**: Optimized for running on RPi with touchscreens.

## Project Layout

- `main.py`: Entry point for the application.
- `gui_app.py`: Handles the User Interface and voting flow logic.
- `data_handler.py`: Manages file I/O for reading encrypted JSON ballots and appending to `votes.json`.
- `ballot_manager.py`: Connects to SQLite to track used/unused ballots and dynamically loads `.json` payloads from USB.
- `printer_service.py`: Handles interaction with the thermal printer and receipt generation.
- `hardware_crypto.py`: Extracts the physical MAC and CPU identifiers to build the hardware passphrase.
- `generate_rpi_keys.py`: Generates the RSA keypair and locks the private key to the hardware.
- `encrypt_ballots_rsa.py`: Admin script for chunk-encrypting JSON ballots using `public.pem`.
- `votes.json`: Audit log where votes are securely recorded in JSON sequence.

## Setup and Usage

### Prerequisites
- Python 3.x
- `tkinter` (usually included)
- `python-escpos`
- `qrcode`
- `Pillow` (PIL)

### Running the Application

1.  Clone the repository.
2.  Install dependencies:
    ```bash
    pip install python-escpos qrcode[pil]
    ```
3.  Run the application:
    ```bash
    python main.py
    ```

### Configuring Candidates (`candidates.json`)

Update `candidates.json` to change the election roster. The format is a dictionary of candidates.

```json
{
    "election_id": "ST-GEN-2026",
    "hash_string": "...",
    "candidates": {
        "0": {
            "serial_id": 1,
            "candidate_name": "Aman Gupta",
            "candidate_number": "A7K..."
        },
        "1": {
            "serial_id": 2,
            "candidate_name": "NAFS",
            "candidate_number": "0" 
        }
    }
}
```
*Note: A candidate named "NAFS" is automatically treated as NOTA.*

## License
[License Information Here]
