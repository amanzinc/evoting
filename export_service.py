import os
import json
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import hardware_crypto

class ExportService:
    def __init__(self, key_path="private.pem", aes_key_storage_path=None, usb_mount_point=None):
        self.key_path = key_path
        self.aes_key_storage_path = aes_key_storage_path
        self.usb_mount_point = usb_mount_point
        self.private_key = None

    def _find_ballot_folder(self, usb_root):
        if not usb_root or not os.path.isdir(usb_root):
            return None

        ballot_variants = [
            d for d in os.listdir(usb_root)
            if d.startswith("ballot_") and os.path.isdir(os.path.join(usb_root, d))
        ]
        if ballot_variants:
            return os.path.join(usb_root, sorted(ballot_variants)[0])

        legacy_path = os.path.join(usb_root, "ballot")
        if os.path.isdir(legacy_path):
            return legacy_path

        return None

    def _resolve_aes_key_storage_path(self):
        if self.aes_key_storage_path and os.path.exists(self.aes_key_storage_path):
            return self.aes_key_storage_path

        env_key_path = os.environ.get("EVOTING_AES_KEY_PATH", "").strip()
        if env_key_path and os.path.exists(env_key_path):
            return env_key_path

        ballot_root = self._find_ballot_folder(self.usb_mount_point)
        if ballot_root:
            usb_key_path = os.path.join(ballot_root, "aes_key.dec")
            if os.path.exists(usb_key_path):
                return usb_key_path

        legacy_local = os.path.join("ballot", "aes_key.dec")
        if os.path.exists(legacy_local):
            return legacy_local

        return None

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

    def _load_stored_aes_key(self):
        """Load previously decrypted ballot AES key from USB/env/local fallback."""
        key_path = self._resolve_aes_key_storage_path()
        if not key_path:
            raise FileNotFoundError(
                "Stored AES key not found. Set EVOTING_AES_KEY_PATH or import ballots from USB."
            )

        with open(key_path, "r", encoding="utf-8") as f:
            key_data = json.load(f)

        key_b64 = key_data.get("aes_key_b64")
        if not key_b64:
            raise ValueError(f"Invalid AES key file at {key_path}: missing aes_key_b64")

        aes_key = base64.b64decode(key_b64)
        if len(aes_key) != 32:
            raise ValueError(f"Invalid AES key length {len(aes_key)} bytes; expected 32")
        return aes_key

    def _sanitize_bmd_id(self, bmd_id):
        """Sanitize BMD ID for safe filesystem naming."""
        raw = str(bmd_id or "UNKNOWN_BMD").strip()
        safe = []
        for ch in raw:
            if ch.isalnum() or ch in ("-", "_"):
                safe.append(ch)
            else:
                safe.append("_")
        return "".join(safe) or "UNKNOWN_BMD"

    def _resolve_bmd_id(self):
        """
        Resolve BMD ID on RPi using this order:
        1. EVOTING_BMD_ID env var
        2. /etc/evoting/bmd_id file
        3. AES key metadata (bmd_id) from resolved key path
        4. UNKNOWN_BMD fallback
        """
        env_bmd = os.environ.get("EVOTING_BMD_ID", "").strip()
        if env_bmd:
            return self._sanitize_bmd_id(env_bmd)

        bmd_file = "/etc/evoting/bmd_id"
        if os.path.exists(bmd_file):
            try:
                with open(bmd_file, "r", encoding="utf-8") as f:
                    file_bmd = f.read().strip()
                if file_bmd:
                    return self._sanitize_bmd_id(file_bmd)
            except Exception:
                pass

        key_path = self._resolve_aes_key_storage_path()
        if key_path and os.path.exists(key_path):
            try:
                with open(key_path, "r", encoding="utf-8") as f:
                    key_data = json.load(f)
                key_bmd = str(key_data.get("bmd_id", "")).strip()
                if key_bmd:
                    return self._sanitize_bmd_id(key_bmd)
            except Exception:
                pass

        return "UNKNOWN_BMD"

    def encrypt_file_with_stored_aes(self, source_path, dest_path, aes_key):
        """
        Encrypt file with stored AES-256 key using AESGCM.
        Output is a JSON envelope (no plaintext transferred to USB).
        """
        with open(source_path, "rb") as f:
            plaintext = f.read()

        nonce = os.urandom(12)
        aesgcm = AESGCM(aes_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)

        payload = {
            "algorithm": "AES-GCM-256",
            "source_name": os.path.basename(source_path),
            "nonce": base64.b64encode(nonce).decode("utf-8"),
            "ciphertext": base64.b64encode(ciphertext).decode("utf-8")
        }

        with open(dest_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def export_election_data(self, source_log_dir, usb_mount_point):
        """
        Encrypt critical log files using stored AES-GCM-256 key before writing to USB.

        No plaintext files are transferred to USB.
        Returns the path to the export directory on the USB drive.
        """
        if not usb_mount_point or not os.path.exists(usb_mount_point):
            raise Exception("USB Drive not found or not mounted.")

        self.usb_mount_point = usb_mount_point
            
        export_dir = os.path.join(usb_mount_point, "exports")
        os.makedirs(export_dir, exist_ok=True)

        bmd_id = self._resolve_bmd_id()
        print(f"Using BMD ID for export naming: {bmd_id}")
        
        # Files to export — fall back to most-recent archive subdir if missing
        votes_log  = os.path.join(source_log_dir, "votes.json")
        tokens_log = os.path.join(source_log_dir, "tokens.log")

        def _find_in_archive(filename):
            """Return the path to filename in the most-recent timestamped archive subdir."""
            try:
                subdirs = sorted([
                    os.path.join(source_log_dir, d)
                    for d in os.listdir(source_log_dir)
                    if os.path.isdir(os.path.join(source_log_dir, d))
                ], reverse=True)
                for sd in subdirs:
                    candidate = os.path.join(sd, filename)
                    if os.path.exists(candidate):
                        return candidate
            except Exception:
                pass
            return None

        if not os.path.exists(votes_log):
            fallback = _find_in_archive("votes.json")
            if fallback:
                print(f"votes.json not at primary path; using archive copy: {fallback}")
                votes_log = fallback

        if not os.path.exists(tokens_log):
            fallback = _find_in_archive("tokens.log")
            if fallback:
                print(f"tokens.log not at primary path; using archive copy: {fallback}")
                tokens_log = fallback

        # Load stored AES key from ballot import stage.
        aes_key = self._load_stored_aes_key()
        
        exported_files = []
        
        # 1. Encrypt votes log
        if os.path.exists(votes_log):
            dest_votes_enc = os.path.join(export_dir, f"final_votes_{bmd_id}.enc.json")
            self.encrypt_file_with_stored_aes(votes_log, dest_votes_enc, aes_key)
            exported_files.append(dest_votes_enc)
            print("Exported: Encrypted votes.json")

        # 2. Encrypt tokens log
        if os.path.exists(tokens_log):
            dest_tokens_enc = os.path.join(export_dir, f"final_tokens_{bmd_id}.enc.json")
            self.encrypt_file_with_stored_aes(tokens_log, dest_tokens_enc, aes_key)
            exported_files.append(dest_tokens_enc)
            print("Exported: Encrypted tokens.log")
            
        if not exported_files:
            raise Exception("No log files found to export.")

        print(f"Successfully exported {len(exported_files)} files to {export_dir}")

        # Duplicate the encrypted export to the LOGS partition (SD card) as a backup.
        # Failures here are non-fatal — the USB export already succeeded.
        try:
            import shutil
            import datetime as _dt
            ts = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            sd_backup_dir = os.path.join(source_log_dir, "exports", ts)
            os.makedirs(sd_backup_dir, exist_ok=True)
            for fpath in exported_files:
                shutil.copy2(fpath, sd_backup_dir)
            print(f"SD card backup written to {sd_backup_dir}")
        except Exception as _be:
            print(f"Warning: SD card backup failed (non-fatal): {_be}")

        return export_dir
