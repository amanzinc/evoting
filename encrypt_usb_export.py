import argparse
import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def load_stored_aes_key(aes_key_file):
    if not os.path.exists(aes_key_file):
        raise FileNotFoundError(
            f"AES key file not found: {aes_key_file}. "
            "Run ballot import first so ballot/aes_key.dec exists."
        )

    with open(aes_key_file, "r", encoding="utf-8") as f:
        key_data = json.load(f)

    key_b64 = key_data.get("aes_key_b64")
    if not key_b64:
        raise ValueError(f"Invalid AES key file: missing aes_key_b64 in {aes_key_file}")

    aes_key = base64.b64decode(key_b64)
    if len(aes_key) != 32:
        raise ValueError(f"Invalid AES key length {len(aes_key)} bytes. Expected 32 bytes.")

    return aes_key


def sanitize_bmd_id(raw_bmd_id):
    raw = str(raw_bmd_id or "UNKNOWN_BMD").strip()
    safe_chars = []
    for ch in raw:
        if ch.isalnum() or ch in ("-", "_"):
            safe_chars.append(ch)
        else:
            safe_chars.append("_")
    return "".join(safe_chars) or "UNKNOWN_BMD"


def resolve_bmd_id(aes_key_file):
    env_bmd = os.environ.get("EVOTING_BMD_ID", "").strip()
    if env_bmd:
        return sanitize_bmd_id(env_bmd)

    bmd_file = "/etc/evoting/bmd_id"
    if os.path.exists(bmd_file):
        try:
            with open(bmd_file, "r", encoding="utf-8") as f:
                file_bmd = f.read().strip()
            if file_bmd:
                return sanitize_bmd_id(file_bmd)
        except Exception:
            pass

    try:
        with open(aes_key_file, "r", encoding="utf-8") as f:
            key_data = json.load(f)
        key_bmd = str(key_data.get("bmd_id", "")).strip()
        if key_bmd:
            return sanitize_bmd_id(key_bmd)
    except Exception:
        pass

    return "UNKNOWN_BMD"


def encrypt_json_file(input_json, output_file, aes_key):
    with open(input_json, "rb") as f:
        plaintext = f.read()

    nonce = os.urandom(12)
    aesgcm = AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    payload = {
        "algorithm": "AES-GCM-256",
        "source_name": os.path.basename(input_json),
        "nonce": base64.b64encode(nonce).decode("utf-8"),
        "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Encrypt JSON file for USB export using stored AES key"
    )
    parser.add_argument(
        "input_json",
        help="Path to source JSON file (example: /logs/votes.json)",
    )
    parser.add_argument(
        "--aes-key-file",
        default="ballot/aes_key.dec",
        help="Path to stored AES key file (default: ballot/aes_key.dec)",
    )
    parser.add_argument(
        "--out-dir",
        default="exports",
        help="Output directory for encrypted file (default: exports)",
    )
    parser.add_argument(
        "--prefix",
        default="final_votes",
        help="Output filename prefix (default: final_votes)",
    )

    args = parser.parse_args()

    input_path = Path(args.input_json)
    if not input_path.exists():
        raise FileNotFoundError(f"Input JSON file not found: {input_path}")

    aes_key = load_stored_aes_key(args.aes_key_file)
    bmd_id = resolve_bmd_id(args.aes_key_file)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / f"{args.prefix}_{bmd_id}.enc.json"
    encrypt_json_file(str(input_path), str(out_file), aes_key)

    print(f"Encrypted export created: {out_file}")


if __name__ == "__main__":
    main()
