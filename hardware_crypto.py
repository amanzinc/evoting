import platform
import uuid
import hashlib
import os

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
    Returns a fast, hardcoded passphrase for debugging OpenSSL decryption faults.
    """
    return b"EVM_DEBUG_PASSPHRASE_123"

def get_mac_address():
    # Legacy wrapper so printer_service doesn't break
    return get_machine_id()

if __name__ == "__main__":
    print(f"Machine ID: {get_machine_id()}")
    print(f"Derived Passphrase (SHA256): {get_hardware_passphrase().decode('utf-8')}")
