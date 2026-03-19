# USB Ballot Import System

## Overview

The e-voting system now supports a new encrypted ballot structure on USB drives designed for secure ballot delivery and verification.

### New USB Structure

```
ballot/
├── aes_key.enc                    # RSA-encrypted AES key (shared across all elections)
├── election_id_1/
│   ├── candidates.json            # Election configuration
│   └── ballot/
│       ├── ballot_1.enc.json      # Encrypted ballots (AES-256-GCM)
│       ├── ballot_2.enc.json
│       └── ...
├── election_id_2/
│   ├── candidates.json
│   └── ballot/
│       ├── ballot_1.enc.json
│       ├── ballot_2.enc.json
│       └── ...
└── ...
```

## Key Components

### 1. AES Key Encryption (`aes_key.enc`)

This file contains a single AES-256 key encrypted with RSA-OAEP-SHA256:

```json
{
  "bmd_id": "1",
  "encrypted_aes_key": "base64_encoded_rsa_encrypted_key",
  "algorithm": "RSA-OAEP-SHA256"
}
```

**Decryption Process:**
- Uses the EVM's private RSA key
- Private key access is protected by hardware-bound passphrase (RPi machine ID)
- Only works on the actual RPi hardware

### 2. Ballot Encryption (`ballot_*.enc.json`)

Each ballot is encrypted with AES-256-GCM:

```json
{
  "algorithm": "RSA-OAEP+AES-GCM-256",
  "nonce": "base64_encoded_iv",
  "num_chunks": 1,
  "chunks": ["base64_encoded_encrypted_data"]
}
```

**Decryption Process:**
1. Extract nonce (IV) and ciphertext
2. Last 16 bytes of ciphertext = GCM authentication tag
3. Decrypt using AES-256-GCM
4. Parse resulting JSON

## Usage

### On RPi (Production)

```bash
# Run the import script on the EVM
python usb_ballot_import.py /media/pi/USB/ballot

# Output:
# ============================================================
# USB BALLOT IMPORT STARTING
# ============================================================
# [1/3] Decrypting AES key from USB...
# ✓ AES key decrypted successfully (32 bytes)
# [2/3] Storing AES key locally...
# ✓ AES key stored locally at ballot/aes_key.dec
# [3/3] Importing ballot elections...
# Found 2 elections on USB
#   ✓ election_id_1: 20 ballots imported
#   ✓ election_id_2: 20 ballots imported
# ============================================================
# IMPORT COMPLETE: 40 total ballots imported
# ============================================================
```

**What happens:**
1. Private key is unlocked using RPi's hardware passphrase
2. AES key is decrypted from `aes_key.enc`
3. AES key is stored locally at `ballot/aes_key.dec`
4. All ballots are decrypted using the AES key
5. Decrypted ballots are imported to `elections/election_id_*/ballots/`

### On Development PC (Demo Mode)

For testing without RPi hardware, provide a pre-decrypted AES key:

```bash
python usb_ballot_import.py ballot --demo --aes-key <base64_aes_key>
```

**Workflow:**
- Demo mode skips RSA decryption (which requires RPi hardware)
- Use provided AES key directly for ballot decryption
- Useful for testing the ballot decryption logic offline

## File Storage

After import, ballots are stored locally in:

```
elections/
├── election_id_1/
│   ├── candidates.json
│   └── ballots/
│       ├── ballot_1.json          # Decrypted ballots
│       ├── ballot_2.json
│       └── ...
└── election_id_2/
    ├── candidates.json
    └── ballots/
        └── ...
```

## Security Flow

### USB Preparation (Off-line, on BMD)

1. Generate random AES-256 key
2. Encrypt AES key with EVM's public RSA key
3. Store in `aes_key.enc`
4. Encrypt all ballots with AES key
5. Store as `ballot_*.enc.json`
6. Copy `ballot/` folder to USB

### EVM Import (RPi, Production)

1. Receive USB with encrypted ballots
2. Unlock private RSA key using hardware passphrase (tied to RPi machine ID)
3. Decrypt AES key
4. Store AES key securely locally
5. Decrypt all ballots
6. Import into local ballot store

## Implementation Details

### Hardware-Bound Security

The private RSA key is protected by a passphrase derived from the RPi's unique hardware ID:

```python
# Only works on the actual RPi:
machine_id = get_machine_id()  # From /etc/machine-id or CPU serial
passphrase = hardware_crypto.get_hardware_passphrase()  # SHA256(machine_id)
private_key = load_pem_private_key(key_data, password=passphrase)
```

**Security implications:**
- Private key cannot be accessed on a different machine
- Each RPi has a unique hardware-bound passphrase
- Prevents key theft/unauthorized access even if USB is lost

### Ballot Import Class

The `USBBallotImporter` class handles the entire workflow:

```python
from usb_ballot_import import USBBallotImporter

# On RPi (production)
importer = USBBallotImporter(demo_mode=False)
summary = importer.import_usb_ballots(
    usb_ballot_path="/media/pi/USB/ballot",
    elections_base_dir="elections"
)

# On PC (demo)
importer = USBBallotImporter(
    demo_mode=True,
    demo_aes_key_b64="your_base64_key"
)
summary = importer.import_usb_ballots(
    usb_ballot_path="ballot",
    elections_base_dir="elections"
)
```

## Backward Compatibility

The system still supports the old ballot structure (with legacy election IDs like E1, E3):

- `BallotManager.get_unused_ballot()` supports both namings
- Ballots can be plain JSON or RSA-encrypted chunks
- The import system focuses on the new AES-GCM encrypted format

## File Locations

- **Importer script:** `usb_ballot_import.py`
- **Updated ballot manager:** `ballot_manager.py`
- **Imported ballots:** `elections/election_id_*/{candidates.json, ballots/}`
- **Stored AES key:** `ballot/aes_key.dec`

## Error Handling

### Private Key Errors (RPi)

```
⚠ HARDWARE BIND ERROR: Private key locked to RPi hardware identity.
This script must run on the actual EVM (Raspberry Pi).
For development, use demo_mode=True with a pre-provided AES key.
```

### Missing Files

```
FileNotFoundError: aes_key.enc not found at <path>
```

Ensure the USB structure matches the expected layout.

### Decryption Failures

```
Failed to decrypt AES key: [specific error]
Failed to decrypt ballot: [specific error]
```

Check:
- AES key file integrity
- RSA private key accessibility
- Ballot file format and corruption

## Testing

### Create Test Ballots

Use the existing `encrypt_ballots.py` or `encrypt_ballots_rsa.py` to generate encrypted test data.

### Verify Import

After import, check:

```bash
ls -la elections/election_id_1/ballots/
# Should show ballot_1.json, ballot_2.json, etc. (decrypted)
```

Parse a decrypted ballot:

```bash
python -c "import json; print(json.load(open('elections/election_id_1/ballots/ballot_1.json')))"
```

## Next Steps

1. **On BMD:** Generate encrypted ballots and store on USB
2. **On RPi:** Run `usb_ballot_import.py` to decrypt and import
3. **In GUI:** Select election from imported list
4. **Voting:** System loads ballots from imported collection

