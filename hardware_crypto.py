import platform
import uuid
import hashlib
import os
import base64

def get_machine_id():
    """Gets a stable, unique machine identifier on Linux or falls back to UUID node."""
    if platform.system() == "Linux":
        # Systemd Machine ID (Most reliable on latest Ubuntu/Debian/Raspbian)
        if os.path.exists("/etc/machine-id"):
            try:
                with open("/etc/machine-id", "r") as f:
                    content = f.read().strip()
                if content:
                    return f"LINUX_MACHINE_{content}"
            except Exception:
                pass
                
        # DMI Product UUID (PC/Server Linux)
        if os.path.exists("/sys/class/dmi/id/product_uuid"):
            try:
                with open("/sys/class/dmi/id/product_uuid", "r") as f:
                    content = f.read().strip()
                if content:
                    return f"LINUX_DMI_{content}"
            except Exception:
                pass

        # CPU Serial (Older Raspberry Pis)
        if os.path.exists("/proc/cpuinfo"):
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    for line in f:
                        if line.startswith('Serial'):
                            parts = line.split(':')
                            if len(parts) == 2 and parts[1].strip() != "0000000000000000":
                                return f"LINUX_CPU_{parts[1].strip()}"
            except Exception:
                pass
                
    # Fallback for Windows/Mac or if Linux failed all physical checks
    mac_num = uuid.getnode()
    if (mac_num >> 40) & 1:
        return "UNKNOWN_DEV_MACHINE"
        
    mac_str = ':'.join(('%012X' % mac_num)[i:i+2] for i in range(0, 12, 2))
    return f"FALLBACK_MAC_{mac_str}"

def get_hardware_passphrase():
    """
    Derives a deterministic, strong passphrase from the physical device's machine ID.
    This passphrase will unlock the private.pem file.
    """
    machine_id = get_machine_id()
    
    raw_identity = f"EVM_SECURE_V2_{machine_id}"
    
    # Use standard digest, encode as urlsafe base64, and strictly take the first 32 chars
    # This prevents the "unsupported" OpenSSL format exception caused by trailing bytes 
    # or oversized hex strings in some OpenSSL > 3.0 backends.
    digest = hashlib.sha256(raw_identity.encode('utf-8')).digest()
    passphrase = base64.urlsafe_b64encode(digest)[:32] 
    return passphrase

def get_mac_address():
    # Legacy wrapper so printer_service doesn't break
    return get_machine_id()

if __name__ == "__main__":
    print(f"Machine ID: {get_machine_id()}")
    print(f"Derived Passphrase (SHA256): {get_hardware_passphrase().decode('utf-8')}")
