import platform
import uuid
import hashlib
import os

def get_mac_address():
    """Gets the MAC Address of the current machine."""
    try:
        # uuid.getnode() returns the MAC address. 
        # If all interfaces are down, it returns a random 48-bit number, so be careful.
        mac_num = uuid.getnode()
        mac_str = ':'.join(('%012X' % mac_num)[i:i+2] for i in range(0, 12, 2))
        return mac_str
    except Exception as e:
        print(f"Failed to get MAC address: {e}")
        return "UNKNOWN_MAC"

def get_cpu_serial():
    """Extracts the unique hardware serial from /proc/cpuinfo (Raspberry Pi only)."""
    if platform.system() != "Linux":
        # On Windows/Mac (e.g. for local testing), return a mock serial
        return "DEV_MACHINE_SERIAL_001"
        
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    # E.g. Serial          : 0000000000123456
                    parts = line.split(':')
                    if len(parts) == 2:
                        return parts[1].strip()
        return "NO_SERIAL_FOUND"
    except Exception as e:
        print(f"Failed to get CPU serial: {e}")
        return "ERROR_READING_SERIAL"

def get_hardware_passphrase():
    """
    Derives a deterministic, strong passphrase from the physical device's MAC and CPU serial.
    This passphrase will unlock the private.pem file.
    """
    mac = get_mac_address()
    serial = get_cpu_serial()
    
    # Combine them
    raw_identity = f"EVM_SECURE_{mac}_{serial}"
    
    # Hash it to ensure a consistent, strong passphrase length
    passphrase = hashlib.sha256(raw_identity.encode('utf-8')).hexdigest()
    return passphrase.encode('utf-8')

if __name__ == "__main__":
    print(f"MAC Address: {get_mac_address()}")
    print(f"CPU Serial: {get_cpu_serial()}")
    print(f"Derived Passphrase (SHA256): {get_hardware_passphrase().decode('utf-8')}")
