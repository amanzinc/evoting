import threading
import time
import sys
import os

try:
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives import serialization
    import hardware_crypto
except ImportError:
    pass

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
    def __init__(self, key_path="private.pem"):
        self.pn532 = None
        self.key_path = key_path
        self.private_key = None
        self.connected = False
        self.lock = threading.Lock()

        self.START_BLOCK = 4
        self.MAX_BLOCK_NO = 255
        self.MIN_REQUIRED_SECTORS = 24
        self.KEY_DEFAULT = b'\xFF' * 6

    def _block_to_sector(self, block_no):
        # MIFARE Classic 4K: sectors 0-31 have 4 blocks, sectors 32-39 have 16 blocks.
        if block_no < 128:
            return block_no // 4
        return 32 + ((block_no - 128) // 16)

    def _sector_layout(self, sector_no):
        if sector_no < 32:
            return sector_no * 4, 4
        return 128 + (sector_no - 32) * 16, 16

    def load_key(self):
        if not os.path.exists(self.key_path):
            print(f"Key file {self.key_path} not found.")
            return False
            
        try:
            passphrase = hardware_crypto.get_hardware_passphrase()
            with open(self.key_path, "rb") as kf:
                self.private_key = serialization.load_pem_private_key(
                    kf.read(),
                    password=passphrase
                )
            return True
        except Exception as e:
            print(f"Error loading private key: {e}")
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
        sector_no = self._block_to_sector(block_no)
        sector_first_block, blocks_per_sector = self._sector_layout(sector_no)
        return block_no == (sector_first_block + blocks_per_sector - 1)

    def read_card(self, mode='encrypted', **kwargs):
        with self.lock:
            return self._read_card_internal(mode=mode, **kwargs)

    def _read_card_internal(self, mode='encrypted', **kwargs):
        """
        Blocking call (with internal timeout loop) to read a card.
        Returns: (uid_string, decrypted_token_string) or None
        """
        if not self.connected:
            # If not connected, we can't read.
            return None

        try:
            # Check for card
            try:
                uid = self.pn532.read_passive_target(timeout=0.5)
            except Exception as e:
                uid = None
            if uid is None:
                return None
            
            # Card Found
            print(f"Card Detected: {list(uid)}")
            
            # Read Data
            block_no = self.START_BLOCK
            raw_bytes = bytearray()
            read_sectors = set()
            payload_complete = False

            while block_no <= self.MAX_BLOCK_NO:
                while self.is_trailer_block(block_no):
                    block_no += 1

                if block_no > self.MAX_BLOCK_NO:
                    break
                
                try:
                    auth = self.pn532.mifare_classic_authenticate_block(
                        uid, block_no, MIFARE_CMD_AUTH_B, self.KEY_DEFAULT
                    )
                except Exception as e:
                    # Ignore single block auth failures
                    auth = False
                
                if not auth:
                    block_no += 1
                    continue
                    
                try:
                    data = self.pn532.mifare_classic_read_block(block_no)      
                except Exception as ignore_e:
                    data = None

                if data is None:
                    block_no += 1
                    continue

                read_sectors.add(self._block_to_sector(block_no))

                if not payload_complete:
                    if b'\x00' in data:
                        raw_bytes.extend(data.split(b'\x00')[0])
                        payload_complete = True
                    else:
                        raw_bytes.extend(data)

                # Enforce reading at least N sectors before allowing decrypt for voter cards

                if payload_complete:
                    break

                block_no += 1

            if not raw_bytes:
                return None

            if mode == 'plain':
                raw_text = raw_bytes.decode('utf-8', errors='ignore').strip()
                if raw_text:
                    return (uid.hex(), raw_text)
                return None

            # Decrypt
            if not self.private_key:
                if not self.load_key():
                    return None

            try:

                import base64

                raw_text = raw_bytes.decode('utf-8', errors='replace')

                # Detect plain-text (officer) cards early — they won't be base64
                try:
                    encrypted_bytes = base64.b64decode(raw_text, validate=True)
                except Exception:
                    # Not a base64-encoded voter card; skip silently in encrypted mode
                    return None

                key_size = self.private_key.key_size // 8  # e.g. 256 for RSA-2048

                if len(encrypted_bytes) == 0 or len(encrypted_bytes) % key_size != 0:
                    print(f"Decryption skipped: unexpected ciphertext length {len(encrypted_bytes)} (key_size={key_size})")
                    return None

                oaep_padding = padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )

                # Support single-chunk and multi-chunk RSA payloads
                decrypted_parts = []
                for i in range(0, len(encrypted_bytes), key_size):
                    chunk = encrypted_bytes[i:i + key_size]
                    decrypted_parts.append(self.private_key.decrypt(chunk, oaep_padding))

                decrypted = b"".join(decrypted_parts).decode("utf-8")

            except Exception as e:

                print(f"Decryption failed: {e}")

                return None

            try:
                import json
                token_data = json.loads(decrypted)
                print("\n? Card Read Success! Data:")
                print("-----------------------------")
                for k, v in token_data.items():
                    print(f"{k}: {v}")
                print("-----------------------------\n")
            except Exception:
                # Fallback for non-JSON data
                print(f"? Card Read Success! Token Payload (String): {decrypted}")

            return (uid.hex(), decrypted)

        except Exception as e:
            # Tell us what caused the outer loop to abort!
            print(f"Read aborted completely: {e}")
            return None
