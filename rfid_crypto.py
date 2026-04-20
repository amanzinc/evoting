import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rfid_aes.key")


def _load_key() -> bytes:
    with open(_KEY_FILE, "r") as f:
        return bytes.fromhex(f.read().strip())


# Shared AES-256 key for all RFID card encryption (polling officer + voter).
# Loaded from rfid_aes.key in the project directory.
# Every BMD device and provisioning tool must use the same key file.
RFID_AES_KEY = _load_key()


def encrypt_payload(plaintext: str) -> str:
    """AES-256-GCM encrypt; returns base64(nonce || ciphertext+tag)."""
    nonce = os.urandom(12)
    ct = AESGCM(RFID_AES_KEY).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_payload(b64_data: str) -> str:
    """AES-256-GCM decrypt base64(nonce || ciphertext+tag); returns plaintext."""
    b64_data = "".join(b64_data.split())
    b64_data += "=" * ((4 - len(b64_data) % 4) % 4)
    raw = base64.b64decode(b64_data)
    if len(raw) < 29:  # 12 nonce + 1 plaintext byte minimum + 16 tag
        raise ValueError(f"Payload too short for AES-GCM: {len(raw)} bytes")
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(RFID_AES_KEY).decrypt(nonce, ct, None).decode("utf-8")
