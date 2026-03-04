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
        passphrase = hardware_crypto.get_hardware_passphrase()
        
        with open(self.key_path, "rb") as key_file:
            self.private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=passphrase if isinstance(passphrase, bytes) else passphrase.encode('utf-8')
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

    def hybrid_encrypt_file(self, source_path, server_key_path="server_key.pem"):
        """
        Encrypts a file of any size using Hybrid Encryption:
        1. Generates a random AES key (Fernet).
        2. Encrypts the large file with AES.
        3. Encrypts the AES key itself with the Server's RSA Public Key.
        """
        if not os.path.exists(server_key_path):
            raise FileNotFoundError(f"Server public key not found at {server_key_path}")
            
        # 1. Load Server's Public RSA Key
        with open(server_key_path, "rb") as key_file:
            server_public_key = serialization.load_pem_public_key(key_file.read())
            
        print(f"Encrypting {source_path} using Hybrid Encryption (AES + RSA)...")
            
        # 2. Generate random AES (Fernet) key
        from cryptography.fernet import Fernet
        aes_key = Fernet.generate_key()
        fernet = Fernet(aes_key)
        
        # 3. Encrypt the actual file data with AES
        with open(source_path, "rb") as f:
            plaintext_data = f.read()
            
        encrypted_data = fernet.encrypt(plaintext_data)
        
        enc_file_path = source_path + ".enc"
        with open(enc_file_path, "wb") as f:
            f.write(encrypted_data)
            
        # 4. Encrypt the AES key with the Server's Public RSA Key
        encrypted_aes_key = server_public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        enc_key_path = source_path + ".key.enc"
        with open(enc_key_path, "wb") as f:
            f.write(encrypted_aes_key)
            
        print(f"Generated encrypted payload: {enc_file_path}")
        print(f"Generated encrypted AES key: {enc_key_path}")
        return enc_file_path, enc_key_path

    def export_election_data(self, source_log_dir, usb_mount_point):
        """
        Signs the critical log files, encrypts them, and copies them to the USB drive.
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
        
        # 1. Sign and Encrypt Votes Log
        if os.path.exists(votes_log):
            # A. Sign the *plaintext* data so the server can verify it hasn't been tampered with
            sig_path = self.sign_file(votes_log)
            
            # B. Encrypt the file using the server's public key (Hybrid Encryption)
            enc_file_path, enc_key_path = self.hybrid_encrypt_file(votes_log)
            
            # C. Copy the resulting encrypted files and signature to USB
            dest_votes_enc = os.path.join(export_dir, "votes.json.enc")
            dest_votes_key = os.path.join(export_dir, "votes.json.key.enc")
            dest_sig = os.path.join(export_dir, "votes.json.sig")
            
            shutil.copy2(enc_file_path, dest_votes_enc)
            shutil.copy2(enc_key_path, dest_votes_key)
            shutil.copy2(sig_path, dest_sig)
            
            # Cleanup local temporary encrypted files 
            os.remove(enc_file_path)
            os.remove(enc_key_path)
            
            exported_files.extend([dest_votes_enc, dest_votes_key, dest_sig])
            print(f"Exported: Encrypted votes.json, Encrypted Key, and Signature")
            
        # 2. Export Tokens Log (Optional to encrypt, but let's just copy for now depending on threat model)
        if os.path.exists(tokens_log):
            dest_tokens = os.path.join(export_dir, "tokens.log")
            shutil.copy2(tokens_log, dest_tokens)
            exported_files.append(dest_tokens)
            print(f"Exported: tokens.log")
            
        if not exported_files:
            raise Exception("No log files found to export.")
            
        print(f"Successfully exported {len(exported_files)} files to {export_dir}")
        return export_dir
