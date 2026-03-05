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

### USB Drive Structure
The EVM requires a USB drive to be inserted before voting can begin. The USB drive must contain the following structure:

```text
[USB_ROOT]/
├── server_key.pem                 # (Required) Server's public RSA key for exporting votes
└── elections/                     # (Required) Directory containing all election data
    ├── E1/                        # (Example) Election ID Folder
    │   ├── candidates.json        # The roster/candidates for this specific election
    │   └── ballots/               # Pre-generated, encrypted individual ballot JSON files
    │       ├── 0AC024CB.json
    │       └── 1BFF34B3.json
    └── E2/                        # (Example) Another Election ID Folder
        ├── candidates.json
        └── ballots/
            └── ...
```
*Note: Upon export ending the election, the EVM will create an `exports/` folder on this USB drive containing `votes.json.enc`.*

### RFID Card Format (Decrypted Payload)
When a voter scans their RFID card, the `rfid_service` decrypts the payload using the EVM's private hardware key. The EVM expects this decrypted payload to be a valid JSON string with the following structure:

```json
{
  "token_id": "UNIQUE_SESSION_123",
  "voter_id": "VOTER_1044A",
  "eid_vector": "E1;E2",
  "booth": 1,
  "issued_at": "2026-03-05T12:00:00.000000"
}
```
*   **`token_id`**: A unique string identifying the voter's session. Used to prevent double-voting. Logged in `votes.json`.
*   **`voter_id`**: The official ID or entry number of the voter (formerly `entry_number`). Logged in `votes.json`.
*   **`eid_vector`**: A semicolon-separated string of Election IDs (matching the folder names on the USB drive) that the voter is eligible to vote in. The EVM will iterate through these elections sequentially.
*   **`booth`**: Integer defining the polling booth.
*   **`issued_at`**: ISO-formatted timestamp of when the token was generated.

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
