import os
import shutil
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature
import hardware_crypto

class ExportService:
    def __init__(self, key_path="private.pem"):
        self.key_path = key_path
        self.private_key = None

    def _load_private_key(self):
        """Loads and unlocks the private key using the hardware-bound passphrase."""
        if not os.path.exists(self.key_path):
            raise FileNotFoundError(f"Private key not found at {self.key_path}")
            
        # Get hardware-specific passphrase
        passphrase = hardware_crypto.generate_passphrase()
        
        with open(self.key_path, "rb") as key_file:
            self.private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=passphrase.encode('utf-8')
            )

    def sign_file(self, file_path):
        """Generates an RSA signature for the given file."""
        if not self.private_key:
            self._load_private_key()
            
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Source file not found: {file_path}")

        print(f"Generating RSA signature for {file_path}...")
        
        with open(file_path, "rb") as f:
            data = f.read()

        signature = self.private_key.sign(
            data,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        sig_path = file_path + ".sig"
        with open(sig_path, "wb") as f:
            f.write(signature)
            
        print(f"Signature saved to {sig_path}")
        return sig_path

    def export_election_data(self, source_log_dir, usb_mount_point):
        """
        Signs the critical log files and copies them to the USB drive.
        Returns the path to the export directory on the USB drive.
        """
        if not usb_mount_point or not os.path.exists(usb_mount_point):
            raise Exception("USB Drive not found or not mounted.")
            
        export_dir = os.path.join(usb_mount_point, "exports")
        os.makedirs(export_dir, exist_ok=True)
        
        # Files to export
        votes_log = os.path.join(source_log_dir, "votes.json")
        tokens_log = os.path.join(source_log_dir, "tokens.log")
        
        exported_files = []
        
        # 1. Sign and Export Votes Log
        if os.path.exists(votes_log):
            sig_path = self.sign_file(votes_log)
            
            dest_votes = os.path.join(export_dir, "votes.json")
            dest_sig = os.path.join(export_dir, "votes.json.sig")
            
            shutil.copy2(votes_log, dest_votes)
            shutil.copy2(sig_path, dest_sig)
            
            exported_files.extend([dest_votes, dest_sig])
            print(f"Exported: votes.json and signature")
            
        # 2. Export Tokens Log (Optional to sign, but let's just copy for now)
        if os.path.exists(tokens_log):
            dest_tokens = os.path.join(export_dir, "tokens.log")
            shutil.copy2(tokens_log, dest_tokens)
            exported_files.append(dest_tokens)
            print(f"Exported: tokens.log")
            
        if not exported_files:
            raise Exception("No log files found to export.")
            
        print(f"Successfully exported {len(exported_files)} files to {export_dir}")
        return export_dir
