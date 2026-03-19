"""
USB Ballot Import Service

Handles importing encrypted ballots from USB with the following structure:
- ballot/
  - aes_key.enc (contains RSA-encrypted AES key)
  - election_id_1/
    - ballot/
      - ballot_1.enc.json
      - ballot_2.enc.json
      - ...
  - election_id_2/
    - ballot/
      - ...

The process:
1. Decrypt AES key from aes_key.enc using private RSA key (RPi only)
2. Store AES key locally for reuse
3. Decrypt each ballot using the AES key
4. Import into local elections directory

NOTE: Private key decryption only works on the RPi where the hardware passphrase
is bound to the machine's unique hardware identity. This script is designed to run
on the EVM (Raspberry Pi) during ballot upload/verification workflows.

For development/testing without RPi access, use the demo mode with an unencrypted AES key.
"""

import os
import json
import base64
import shutil
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import hardware_crypto


class USBBallotImporter:
    def __init__(self, private_key_path="private.pem", local_storage_dir="ballot", demo_mode=False, demo_aes_key_b64=None):
        """
        Initialize the USB Ballot Importer.
        
        Args:
            private_key_path: Path to the private RSA key (protected by hardware identity)
                             NOTE: Only works on RPi with hardware-bound passphrase
            local_storage_dir: Directory to store decrypted AES keys and imported ballots
            demo_mode: If True, skip RSA decryption and use pre-provided AES key (for testing)
            demo_aes_key_b64: Base64-encoded AES key for demo mode (must provide if demo_mode=True)
        """
        self.private_key_path = private_key_path
        self.local_storage_dir = local_storage_dir
        self.private_key = None
        self.decrypted_aes_key = None
        self.aes_key_storage_path = os.path.join(local_storage_dir, "aes_key.dec")
        self.demo_mode = demo_mode
        
        # For demo mode, accept a pre-decrypted AES key
        if demo_mode and demo_aes_key_b64:
            self.decrypted_aes_key = base64.b64decode(demo_aes_key_b64)
            print(f"[DEMO MODE] Using provided AES key ({len(self.decrypted_aes_key)} bytes)")
        
        os.makedirs(local_storage_dir, exist_ok=True)

    def _load_private_key(self):
        """
        Load and unlock the private RSA key using hardware identity.
        
        NOTE: This only works on the RPi (EVM hardware) where the hardware passphrase
        is bound to the machine's unique hardware ID.
        """
        if self.private_key:
            return  # Already loaded
        
        if self.demo_mode:
            print("[DEMO MODE] Skipping private key decryption (not available outside RPi)")
            return
            
        if not os.path.exists(self.private_key_path):
            raise FileNotFoundError(f"Private key not found at {self.private_key_path}")
        
        try:
            passphrase = hardware_crypto.get_hardware_passphrase()
            with open(self.private_key_path, "rb") as kf:
                self.private_key = serialization.load_pem_private_key(
                    kf.read(),
                    password=passphrase
                )
            print("✓ Private key unlocked with hardware identity")
        except Exception as e:
            # Check if this is due to password mismatch (indicates non-RPi environment)
            if "Incorrect password" in str(e) or "could not decrypt" in str(e):
                raise Exception(
                    f"\n⚠ HARDWARE BIND ERROR: Private key locked to RPi hardware identity.\n"
                    f"This script must run on the actual EVM (Raspberry Pi).\n"
                    f"Error: {e}\n"
                    f"For development, use demo_mode=True with a pre-provided AES key."
                )
            else:
                raise Exception(f"Failed to unlock private key: {e}")

    def decrypt_aes_key_from_usb(self, usb_ballot_path):
        """
        Decrypt the AES key from the USB aes_key.enc file using RSA.
        
        NOTE: This requires the RPi's private key and hardware passphrase.
        For non-RPi environments, use demo_mode=True.
        
        Args:
            usb_ballot_path: Path to the 'ballot' folder on the USB
            
        Returns:
            bytes: The decrypted AES key (32 bytes for AES-256)
        """
        # Skip if already loaded (e.g., in demo mode)
        if self.decrypted_aes_key:
            return self.decrypted_aes_key
        
        if self.demo_mode:
            raise ValueError(
                "Demo mode enabled but no AES key provided. "
                "Use demo_aes_key_b64 parameter when instantiating USBBallotImporter."
            )
        
        aes_key_enc_path = os.path.join(usb_ballot_path, "aes_key.enc")
        
        if not os.path.exists(aes_key_enc_path):
            raise FileNotFoundError(f"aes_key.enc not found at {aes_key_enc_path}")
        
        # Load the encrypted AES key metadata
        with open(aes_key_enc_path, "r") as f:
            key_data = json.load(f)
        
        encrypted_aes_key_b64 = key_data.get("encrypted_aes_key")
        algorithm = key_data.get("algorithm", "RSA-OAEP-SHA256")
        
        if not encrypted_aes_key_b64:
            raise ValueError("No encrypted_aes_key found in aes_key.enc")
        
        print(f"Decrypting AES key using algorithm: {algorithm}")
        
        # Decode the base64-encoded encrypted key
        encrypted_aes_key = base64.b64decode(encrypted_aes_key_b64)
        
        # Ensure private key is loaded
        self._load_private_key()
        
        # Decrypt the AES key using RSA-OAEP
        try:
            decrypted_aes_key = self.private_key.decrypt(
                encrypted_aes_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            print(f"✓ AES key decrypted successfully ({len(decrypted_aes_key)} bytes)")
            self.decrypted_aes_key = decrypted_aes_key
            return decrypted_aes_key
        except Exception as e:
            raise Exception(f"Failed to decrypt AES key: {e}")

    def store_aes_key_locally(self):
        """Store the decrypted AES key in local storage for future use."""
        if self.decrypted_aes_key is None:
            raise ValueError("No decrypted AES key available. Call decrypt_aes_key_from_usb first.")
        
        # Store as JSON with metadata
        key_storage = {
            "aes_key_b64": base64.b64encode(self.decrypted_aes_key).decode('utf-8'),
            "key_size": len(self.decrypted_aes_key),
            "algorithm": "AES-256-GCM"
        }
        
        with open(self.aes_key_storage_path, "w") as f:
            json.dump(key_storage, f, indent=2)
        
        print(f"✓ AES key stored locally at {self.aes_key_storage_path}")

    def load_stored_aes_key(self):
        """Load the previously stored AES key from local storage."""
        if not os.path.exists(self.aes_key_storage_path):
            raise FileNotFoundError(
                f"Stored AES key not found at {self.aes_key_storage_path}. "
                "Run decrypt_aes_key_from_usb first."
            )
        
        with open(self.aes_key_storage_path, "r") as f:
            key_storage = json.load(f)
        
        self.decrypted_aes_key = base64.b64decode(key_storage["aes_key_b64"])
        print(f"✓ Loaded stored AES key ({len(self.decrypted_aes_key)} bytes)")
        return self.decrypted_aes_key

    def decrypt_ballot_file(self, ballot_enc_path):
        """
        Decrypt a single ballot file using the AES key.
        
        Args:
            ballot_enc_path: Path to the encrypted ballot JSON file
            
        Returns:
            dict: Decrypted ballot data
        """
        if self.decrypted_aes_key is None:
            raise ValueError("AES key not available. Load it first.")
        
        # Read the encrypted ballot JSON
        with open(ballot_enc_path, "r") as f:
            ballot_data = json.load(f)
        
        algorithm = ballot_data.get("algorithm")
        nonce_b64 = ballot_data.get("nonce")
        chunks = ballot_data.get("chunks", [])
        
        if not chunks:
            raise ValueError(f"No encrypted chunks found in {ballot_enc_path}")
        
        # Decode nonce (initialization vector for GCM)
        nonce = base64.b64decode(nonce_b64)
        
        # Concatenate all encrypted chunks
        encrypted_data = b"".join(base64.b64decode(chunk) for chunk in chunks)
        
        # The last 16 bytes are the authentication tag (GCM tag)
        ciphertext = encrypted_data[:-16]
        auth_tag = encrypted_data[-16:]
        
        try:
            # Decrypt using AES-256-GCM
            cipher = Cipher(
                algorithms.AES(self.decrypted_aes_key),
                modes.GCM(nonce, auth_tag)
            )
            decryptor = cipher.decryptor()
            decrypted_ballot = decryptor.update(ciphertext) + decryptor.finalize()
            
            # Parse the JSON
            ballot_json = json.loads(decrypted_ballot.decode('utf-8'))
            return ballot_json
        except Exception as e:
            raise Exception(f"Failed to decrypt ballot: {e}")

    def import_usb_ballots(self, usb_ballot_path, elections_base_dir="elections"):
        """
        Main function to import all ballots from USB.
        
        Process:
        1. Decrypt AES key from aes_key.enc
        2. Store AES key locally
        3. Find all election folders (election_id_1, election_id_2, etc.)
        4. For each election, decrypt and import all ballots
        5. Create election structure in local directory
        
        Args:
            usb_ballot_path: Path to the 'ballot' folder on USB
            elections_base_dir: Local directory to store imported elections
            
        Returns:
            dict: Summary of import results
        """
        summary = {
            "status": "success",
            "elections_imported": [],
            "total_ballots": 0,
            "errors": []
        }
        
        print("\n" + "="*60)
        print("USB BALLOT IMPORT STARTING")
        print("="*60)
        
        try:
            # Step 1: Decrypt AES key
            print("\n[1/3] Decrypting AES key from USB...")
            self.decrypt_aes_key_from_usb(usb_ballot_path)
            
            # Step 2: Store AES key locally
            print("[2/3] Storing AES key locally...")
            self.store_aes_key_locally()
            
            # Step 3: Import elections
            print("[3/3] Importing ballot elections...")
            self._import_elections(usb_ballot_path, elections_base_dir, summary)
            
        except Exception as e:
            summary["status"] = "error"
            summary["errors"].append(str(e))
            print(f"\n✗ Import failed: {e}")
        
        return summary

    def _import_elections(self, usb_ballot_path, elections_base_dir, summary):
        """
        Helper function to recursively import all elections from USB.
        """
        # Find all election folders (election_id_1, election_id_2, etc.)
        election_folders = [
            d for d in os.listdir(usb_ballot_path)
            if d.startswith("election_id_") and os.path.isdir(os.path.join(usb_ballot_path, d))
        ]
        
        if not election_folders:
            raise ValueError(f"No election folders found in {usb_ballot_path}")
        
        print(f"Found {len(election_folders)} elections on USB")
        
        os.makedirs(elections_base_dir, exist_ok=True)
        
        for election_folder in sorted(election_folders):
            election_path = os.path.join(usb_ballot_path, election_folder)
            ballot_folder = os.path.join(election_path, "ballot")
            
            if not os.path.isdir(ballot_folder):
                msg = f"ballot folder not found in {election_path}"
                summary["errors"].append(msg)
                print(f"  ✗ {election_folder}: {msg}")
                continue
            
            # Find candidates.json in the election folder (if it exists)
            candidates_file = os.path.join(election_path, "candidates.json")
            
            # Create local election structure
            local_election_dir = os.path.join(elections_base_dir, election_folder)
            local_ballots_dir = os.path.join(local_election_dir, "ballots")
            os.makedirs(local_ballots_dir, exist_ok=True)
            
            # Copy candidates.json if it exists
            if os.path.exists(candidates_file):
                shutil.copy2(candidates_file, os.path.join(local_election_dir, "candidates.json"))
            
            # Import all ballots for this election
            ballot_files = sorted([
                f for f in os.listdir(ballot_folder)
                if f.endswith(".enc.json")
            ])
            
            ballots_imported = 0
            for ballot_file in ballot_files:
                ballot_enc_path = os.path.join(ballot_folder, ballot_file)
                ballot_name = ballot_file.replace(".enc.json", ".json")
                local_ballot_path = os.path.join(local_ballots_dir, ballot_name)
                
                try:
                    # Decrypt the ballot
                    decrypted_ballot = self.decrypt_ballot_file(ballot_enc_path)
                    
                    # Save the decrypted ballot
                    with open(local_ballot_path, "w") as f:
                        json.dump(decrypted_ballot, f, indent=2)
                    
                    ballots_imported += 1
                except Exception as e:
                    msg = f"Failed to import {ballot_file}: {e}"
                    summary["errors"].append(msg)
                    print(f"    ✗ {ballot_file}: {e}")
            
            summary["elections_imported"].append({
                "election_id": election_folder,
                "ballots_imported": ballots_imported
            })
            summary["total_ballots"] += ballots_imported
            
            print(f"  ✓ {election_folder}: {ballots_imported} ballots imported")
        
        print("\n" + "="*60)
        print(f"IMPORT COMPLETE: {summary['total_ballots']} total ballots imported")
        print("="*60 + "\n")


def main():
    """
    Example usage: Import ballots from USB
    
    USAGE SCENARIOS:
    
    1. ON RPi (EVM Hardware) - Production:
       python usb_ballot_import.py /media/pi/USB/ballot
       
    2. ON Development PC - Demo Mode:
       python usb_ballot_import.py ballot --demo --aes-key <base64_key>
    """
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Import encrypted ballots from USB (RPi or Demo mode)"
    )
    parser.add_argument(
        "usb_ballot_path",
        help="Path to the 'ballot' folder on USB"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Enable demo mode (for testing without RPi hardware)"
    )
    parser.add_argument(
        "--aes-key",
        help="Base64-encoded AES key for demo mode"
    )
    parser.add_argument(
        "--out-dir",
        default="elections",
        help="Output directory for imported ballots (default: elections)"
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.usb_ballot_path):
        print(f"Error: USB ballot path not found: {args.usb_ballot_path}")
        sys.exit(1)
    
    # Create importer
    importer = USBBallotImporter(
        private_key_path="private.pem",
        local_storage_dir="ballot",
        demo_mode=args.demo,
        demo_aes_key_b64=args.aes_key
    )
    
    # Import ballots
    summary = importer.import_usb_ballots(
        usb_ballot_path=args.usb_ballot_path,
        elections_base_dir=args.out_dir
    )
    
    # Print summary
    if summary["status"] == "success":
        print(f"✓ Import successful!")
        print(f"  Elections: {len(summary['elections_imported'])}")
        print(f"  Total ballots: {summary['total_ballots']}")
        for election in summary['elections_imported']:
            print(f"    - {election['election_id']}: {election['ballots_imported']} ballots")
    else:
        print(f"✗ Import failed!")
        for error in summary['errors']:
            print(f"  - {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
