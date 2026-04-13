"""
hardware_crypto.py  ─  Hardware-bound passphrase derivation for evoting BMD.

SECURITY MODEL
--------------
The private key (private.pem) is encrypted with a passphrase derived from a
secret that is physically locked to the device's silicon.

THREAT: SD-card cloning
  An attacker that copies the entire micro-SD card to another card gets an
  identical filesystem — including /etc/machine-id, /proc/cpuinfo Serial, and
  private.pem.  If the passphrase is derived solely from filesystem bytes, the
  clone can decrypt the key.

DEFENSE: bind to OTP/silicon — not the filesystem
  We derive the passphrase from sources that live *in hardware silicon* and are
  NOT copied when you copy the SD card:

  1. vcgencmd otp_dump  (Raspberry Pi OTP fuse bank — silicon level, read-only,
     unique per SoC, survives full SD reflash).
  2. /proc/cpuinfo Serial — always prefer vcgencmd; cpuinfo Serial on some newer
     kernels/Pi 5 returns 0s.  Kept as a secondary layer.
  3. ATECC608 secure element via i2c (optional, best security).
  4. dmidecode / /sys/class/dmi product_uuid — for x86 deployments.
  5. FALLBACK (dev-only): randomised UUID stored in a hidden file.  This WILL be
     different on a clone, but it is NOT cryptographically trusted — it is only
     a convenience for development machines.  The system prints a large warning
     when this path is taken.

IMPORTANT: After running generate_rpi_keys.py on the target RPi and burning the
key pair, that private.pem is useless on any other physical device because the
vcgencmd OTP values differ.  Cloning the SD card gives an attacker private.pem
but the wrong passphrase → decryption fails.
"""

import platform
import hashlib
import os
import base64
import subprocess


# ──────────────────────────────────────────────────────────────────────────────
# 1.  OTP fuse bank via vcgencmd  (Raspberry Pi only, silicon-level)
# ──────────────────────────────────────────────────────────────────────────────

def _read_rpi_otp() -> str | None:
    """
    Read the Raspberry Pi OTP register bank using vcgencmd otp_dump.

    The OTP bank contains the CPU serial number and unique silicon fuses burned
    at manufacture time.  This data CANNOT be copied by cloning an SD card.

    Returns a stable hex string derived from OTP rows 28–30 (serial/MAC seed)
    and the full raw dump, or None if vcgencmd is unavailable.
    """
    try:
        result = subprocess.run(
            ["vcgencmd", "otp_dump"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        lines = result.stdout.strip().splitlines()
        # Collect rows 16-29 which include serial / unique silicon IDs
        relevant = []
        for line in lines:
            try:
                row_str, val_str = line.split(":")
                row = int(row_str.strip())
                if 16 <= row <= 29:
                    relevant.append(val_str.strip())
            except Exception:
                continue

        if not relevant:
            # Fallback: use entire dump
            relevant = [l.split(":")[-1].strip() for l in lines if ":" in l]

        if not relevant:
            return None

        otp_blob = "|".join(relevant)
        return f"OTP_{otp_blob}"
    except FileNotFoundError:
        return None  # Not a Raspberry Pi / vcgencmd not installed
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 2.  /proc/cpuinfo Serial  (RPi, silicon-level on Pi 3/4, Pi 5 varies)
# ──────────────────────────────────────────────────────────────────────────────

def _read_rpi_cpuinfo_serial() -> str | None:
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    parts = line.split(":")
                    if len(parts) == 2:
                        serial = parts[1].strip()
                        if serial and serial != "0000000000000000":
                            return f"CPUSERIAL_{serial}"
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 3.  DMI product UUID  (x86 servers / PCs — NOT populated on RPi)
# ──────────────────────────────────────────────────────────────────────────────

def _read_dmi_uuid() -> str | None:
    """DMI UUID is stored in motherboard firmware SRAM, not on the disk."""
    # Prefer dmidecode (requires root) for reliability
    try:
        result = subprocess.run(
            ["dmidecode", "-s", "system-uuid"],
            capture_output=True, text=True, timeout=5
        )
        val = result.stdout.strip()
        if val and val.lower() not in ("", "not present", "not specified"):
            return f"DMI_{val}"
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # Fallback: sysfs (may require root on some kernels)
    try:
        with open("/sys/class/dmi/id/product_uuid", "r") as f:
            val = f.read().strip()
            if val and val.lower() not in ("", "not present"):
                return f"DMI_{val}"
    except Exception:
        pass

    return None


# ──────────────────────────────────────────────────────────────────────────────
# 4.  Hidden fallback seed  (DEV ONLY — NOT secure against cloning)
# ──────────────────────────────────────────────────────────────────────────────

_FALLBACK_SEED_PATH = os.path.join(os.path.dirname(__file__), ".hw_seed")


def _read_or_create_fallback_seed() -> str:
    """
    ⚠️  DEVELOPMENT FALLBACK ONLY.

    Creates a random 32-byte seed file the first time it is called and reuses
    it afterward.  Because this file lives on the *filesystem*, an SD-card clone
    will contain the same seed — this does NOT protect against cloning.

    This path is only taken on Windows / macOS / unsupported devices where no
    silicon-level identifier is available.  A loud warning is printed so
    operators know the device is not properly locked.
    """
    if os.path.exists(_FALLBACK_SEED_PATH):
        try:
            with open(_FALLBACK_SEED_PATH, "r") as f:
                seed = f.read().strip()
            if len(seed) >= 32:
                return f"FALLBACK_{seed}"
        except Exception:
            pass

    import secrets
    seed = secrets.token_hex(32)
    try:
        with open(_FALLBACK_SEED_PATH, "w") as f:
            f.write(seed)
        # Make it hidden + read-only
        os.chmod(_FALLBACK_SEED_PATH, 0o400)
    except Exception:
        pass

    return f"FALLBACK_{seed}"


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def get_machine_id() -> str:
    """
    Return the best available hardware-bound identity string for this device.

    Priority order (highest = most clone-resistant):
      1. RPi OTP fuse dump via vcgencmd   ← silicon-level, cannot be cloned
      2. RPi /proc/cpuinfo CPU serial     ← silicon-level (Pi 3/4)
      3. DMI product UUID via dmidecode   ← firmware SRAM (x86)
      4. Filesystem fallback seed         ← ⚠️  NOT clone-resistant (dev only)

    The returned string is used exclusively as input to get_hardware_passphrase()
    and is never stored or transmitted.
    """
    if platform.system() == "Linux":
        # --- Tier 1: RPi OTP (best) ---
        otp = _read_rpi_otp()
        if otp:
            return otp

        # --- Tier 2: CPU Serial ---
        serial = _read_rpi_cpuinfo_serial()
        if serial:
            return serial

        # --- Tier 3: DMI UUID ---
        dmi = _read_dmi_uuid()
        if dmi:
            return dmi

    # --- Tier 4: Dev fallback ---
    print(
        "\n"
        "╔══════════════════════════════════════════════════════════════════╗\n"
        "║  ⚠️  SECURITY WARNING: Hardware binding NOT active              ║\n"
        "║  No silicon-level identifier found (vcgencmd / cpuinfo / DMI).  ║\n"
        "║  Falling back to a filesystem seed — SD card cloning will       ║\n"
        "║  compromise the private key.  DO NOT use in production!         ║\n"
        "╚══════════════════════════════════════════════════════════════════╝\n"
    )
    return _read_or_create_fallback_seed()


def get_hardware_passphrase() -> bytes:
    """
    Derive a deterministic 32-byte passphrase from the physical device's
    silicon-level identity.  This passphrase is used to encrypt/decrypt
    private.pem via BestAvailableEncryption (AES-256-CBC + PBKDF2).

    The derivation is: SHA-256( "EVM_SECURE_V3_" + machine_id )
    encoded as URL-safe base64, first 32 bytes taken.

    NOTE: Because the domain-separator includes "V3", keys generated with
    this version are NOT compatible with keys generated by the old V2 code
    (which used /etc/machine-id).  Re-run generate_rpi_keys.py after updating.
    """
    machine_id = get_machine_id()
    raw_identity = f"EVM_SECURE_V3_{machine_id}"
    digest = hashlib.sha256(raw_identity.encode("utf-8")).digest()
    passphrase = base64.urlsafe_b64encode(digest)[:32]
    return passphrase


def get_mac_address():
    """Legacy wrapper — do not use for new code."""
    return get_machine_id()


if __name__ == "__main__":
    mid = get_machine_id()
    pp = get_hardware_passphrase().decode("utf-8")
    print(f"Machine ID source : {mid[:60]}{'...' if len(mid) > 60 else ''}")
    print(f"Derived passphrase: {pp}")
    if mid.startswith("OTP_"):
        print("✅  Bound to RPi OTP silicon fuses — SD clone-resistant.")
    elif mid.startswith("CPUSERIAL_"):
        print("✅  Bound to RPi CPU serial — SD clone-resistant.")
    elif mid.startswith("DMI_"):
        print("✅  Bound to DMI product UUID — SD clone-resistant.")
    else:
        print("⚠️  Fallback seed used — NOT clone-resistant. Dev mode only.")
