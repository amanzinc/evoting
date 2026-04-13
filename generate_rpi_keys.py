import os
import json
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from hardware_crypto import get_hardware_passphrase


def _resolve_bmd_id(default_value=1):
    """Resolve BMD ID from env var, then bmd_config.json, then fallback default."""
    raw = os.environ.get("EVOTING_BMD_ID", "").strip()
    if raw:
        try:
            return int(raw)
        except Exception:
            pass
    # Fallback: read from bmd_config.json written by the provisioner
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bmd_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return int(data.get("bmd_id", default_value))
        except Exception:
            pass
    return default_value


def _resolve_key_version(default_value=1):
    """Resolve key version from env or fallback default."""
    raw = os.environ.get("EVOTING_KEY_VERSION", str(default_value)).strip()
    try:
        return int(raw)
    except Exception:
        return default_value


def _iso_utc_now():
    """UTC timestamp in ISO-8601 with milliseconds and Z suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def generate_keys():
    print("Generating 2048-bit RSA Hardware-Bound Keys...")

    # Always save keys alongside this script, regardless of current working dir.
    _script_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. Generate Private Key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # 2. Get the unique hardware passphrase
    passphrase = get_hardware_passphrase()
    print("Locked with Hardware Identity.")

    # 3. Serialize Private Key (Encrypted with Passphrase)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase)
    )

    with open(os.path.join(_script_dir, 'private.pem'), 'wb') as f:
        f.write(private_pem)

    # 4. Serialize Public Key (Unencrypted)
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    with open(os.path.join(_script_dir, 'public.pem'), 'wb') as f:
        f.write(public_pem)

    # 5. Generate bmd_key.json for key distribution workflows.
    bmd_key_payload = [
        {
            "bmd_id": _resolve_bmd_id(1),
            "rsa_public_key_pem": public_pem.decode("utf-8"),
            "is_active": True,
            "key_version": _resolve_key_version(1),
            "created_at": _iso_utc_now()
        }
    ]

    with open(os.path.join(_script_dir, 'bmd_key.json'), 'w', encoding='utf-8') as f:
        json.dump(bmd_key_payload, f, indent=2)

    print("Success! Generated 'public.pem', 'private.pem', and 'bmd_key.json'.")
    print("Give 'public.pem' to the Election Admin to encrypt ballots.")
    print("Keep 'private.pem' on this exact Raspberry Pi.")

if __name__ == "__main__":
    generate_keys()
