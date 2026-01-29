import time
import sys
import os

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None

# Hardware libraries - Wrapped to prevent crash on Dev machine
try:
    import board
    import busio
    from adafruit_pn532.i2c import PN532_I2C
    from adafruit_pn532.adafruit_pn532 import MIFARE_CMD_AUTH_B
    HARDWARE_AVAILABLE = True
except (ImportError, NotImplementedError, AttributeError):
    HARDWARE_AVAILABLE = False

class RFIDService:
    def __init__(self, key_path="secret.key"):
        self.pn532 = None
        self.key_path = key_path
        self.fernet = None
        self.connected = False
        
        self.START_BLOCK = 4
        self.MAX_BLOCKS = 40
        self.KEY_DEFAULT = b'\xFF' * 6

    def load_key(self):
        if not Fernet:
            print("Cryptography module missing.")
            return False
            
        if not os.path.exists(self.key_path):
            print(f"Key file {self.key_path} not found.")
            return False
            
        try:
            with open(self.key_path, "rb") as f:
                self.fernet = Fernet(f.read())
            return True
        except Exception as e:
            print(f"Error loading key: {e}")
            return False

    def connect(self):
        """Attempts to connect to the PN532 reader."""
        if not HARDWARE_AVAILABLE:
            print("RFID Hardware libraries not available (Dev Mode).")
            return False

        try:
            # On RPi this uses board.SCL/SDA. On Windows this might fail.
            i2c = busio.I2C(board.SCL, board.SDA)
            self.pn532 = PN532_I2C(i2c, debug=False)
            self.pn532.SAM_configuration()
            self.connected = True
            print("RFID Reader Connected Successfully.")
            return True
        except Exception as e:
            print(f"RFID Connection Failed: {e}")
            return False

    def is_trailer_block(self, block_no):
        return (block_no + 1) % 4 == 0

    def read_card(self):
        """
        Blocking call (with internal timeout loop) to read a card.
        Returns: (uid_string, decrypted_token_string) or None
        """
        if not self.connected:
            # If not connected, we can't read.
            return None

        try:
            # Check for card
            uid = self.pn532.read_passive_target(timeout=0.5)
            if uid is None:
                return None
            
            # Card Found
            print(f"Card Detected: {list(uid)}")
            
            # Read Data
            block_no = self.START_BLOCK
            raw_bytes = bytearray()
            
            for _ in range(self.MAX_BLOCKS):
                while self.is_trailer_block(block_no):
                    block_no += 1
                
                auth = self.pn532.mifare_classic_authenticate_block(
                    uid, block_no, MIFARE_CMD_AUTH_B, self.KEY_DEFAULT
                )
                
                if not auth:
                    break
                    
                data = self.pn532.mifare_classic_read_block(block_no)
                if data is None:
                    break
                
                if b'\x00' in data:
                    raw_bytes.extend(data.split(b'\x00')[0])
                    break
                    
                raw_bytes.extend(data)
                block_no += 1
            
            if not raw_bytes:
                return None

            # Decrypt
            if not self.fernet:
                if not self.load_key():
                    return (uid.hex(), "DECRYPTION_FAILED_NO_KEY")

            encrypted_token = raw_bytes.decode("utf-8")
            decrypted = self.fernet.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
            
            print(f"✅ Card Read Success! Token Payload: {decrypted}")
            
            return (uid.hex(), decrypted)

        except Exception as e:
            print(f"Error reading card: {e}")
            return None
