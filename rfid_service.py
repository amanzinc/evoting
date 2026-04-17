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
        self.i2c = None
        self.key_path = key_path
        self.private_key = None
        self.connected = False
        
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

    def _close_bus(self):
        try:
            if self.i2c and hasattr(self.i2c, "deinit"):
                self.i2c.deinit()
        except Exception:
            pass
        self.i2c = None
        self.pn532 = None
        self.connected = False

    def connect(self):
        """Attempts to connect to the PN532 reader."""
        if not HARDWARE_AVAILABLE:
            print("RFID Hardware libraries not available (Dev Mode).")
            return False

        if self.connected and self.pn532 is not None:
            return True

        last_error = None
        for attempt in range(1, 4):
            try:
                self._close_bus()
                # On RPi this uses board.SCL/SDA. On Windows this might fail.
                self.i2c = busio.I2C(board.SCL, board.SDA)
                time.sleep(0.15)
                self.pn532 = PN532_I2C(self.i2c, debug=False)
                time.sleep(0.15)
                self.pn532.SAM_configuration()
                self.connected = True
                print("RFID Reader Connected Successfully.")
                return True
            except Exception as e:
                last_error = e
                self._close_bus()
                time.sleep(0.3 * attempt)

        print(f"RFID Connection Failed after retries: {last_error}")
        return False

    def is_trailer_block(self, block_no):
        sector_no = self._block_to_sector(block_no)
        sector_first_block, blocks_per_sector = self._sector_layout(sector_no)
        return block_no == (sector_first_block + blocks_per_sector - 1)

    def _auth_block(self, uid, block_no):
        try:
            return self.pn532.mifare_classic_authenticate_block(
                uid, block_no, MIFARE_CMD_AUTH_B, self.KEY_DEFAULT
            )
        except Exception:
            return False

    def _iter_data_blocks(self):
        block_no = self.START_BLOCK
        while block_no <= self.MAX_BLOCK_NO:
            if not self.is_trailer_block(block_no):
                yield block_no
            block_no += 1

    def _normalize_uid(self, uid):
        if uid is None:
            return None
        if isinstance(uid, (bytes, bytearray)):
            return bytes(uid)
        if isinstance(uid, (list, tuple)):
            try:
                return bytes(uid)
            except Exception:
                return None
        return None

    def _normalize_block_data(self, data):
        if data is None:
            return None
        if isinstance(data, bytes):
            return data
        if isinstance(data, bytearray):
            return bytes(data)
        if isinstance(data, (list, tuple)):
            try:
                return bytes(data)
            except Exception:
                return None
        return None

    def write_plaintext_card_payload(self, payload_text, wait_seconds=20):
        """Write plain text payload to card data blocks (null-terminated)."""
        if not self.connected:
            if not self.connect():
                raise RuntimeError("RFID reader not connected")

        deadline = time.time() + max(1, int(wait_seconds))
        uid = None
        while time.time() < deadline:
            uid = self.pn532.read_passive_target(timeout=0.5)
            if uid is not None:
                break
            time.sleep(0.1)

        if uid is None:
            raise RuntimeError("No RFID card detected for writing")

        payload_bytes = (payload_text or "").encode("utf-8") + b"\x00"
        chunks = []
        for i in range(0, len(payload_bytes), 16):
            chunk = payload_bytes[i:i + 16]
            if len(chunk) < 16:
                chunk = chunk + (b"\x00" * (16 - len(chunk)))
            chunks.append(chunk)

        data_blocks = list(self._iter_data_blocks())
        if len(chunks) > len(data_blocks):
            raise RuntimeError("Payload too large for RFID card")

        for idx, block_no in enumerate(data_blocks[:len(chunks)]):
            if not self._auth_block(uid, block_no):
                raise RuntimeError(f"Auth failed for block {block_no}")

            ok = self.pn532.mifare_classic_write_block(block_no, chunks[idx])
            if not ok:
                raise RuntimeError(f"Write failed for block {block_no}")

        return uid.hex()

    def read_card(self, min_required_sectors=None):
        """
        Blocking call (with internal timeout loop) to read a card.
        Returns: (uid_string, decrypted_token_string) or None
        """
        if not self.connected:
            # If not connected, we can't read.
            return None

        required_sectors = self.MIN_REQUIRED_SECTORS if min_required_sectors is None else int(min_required_sectors)
        if required_sectors < 1:
            required_sectors = 1

        try:
            # Check for card
            raw_uid = self.pn532.read_passive_target(timeout=0.5)
            uid = self._normalize_uid(raw_uid)
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
                except Exception:
                    block_no += 1
                    continue
                
                if not auth:
                    block_no += 1
                    continue
                    
                try:
                    raw_block = self.pn532.mifare_classic_read_block(block_no)
                except Exception:
                    block_no += 1
                    continue

                data = self._normalize_block_data(raw_block)
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

                # Enforce minimum number of sectors before allowing decrypt.
                if payload_complete and len(read_sectors) >= required_sectors:
                    break

                block_no += 1

            if len(read_sectors) < required_sectors:
                print(
                    f"Card read rejected: only {len(read_sectors)} sectors read; "
                    f"minimum required is {required_sectors}."
                )
                return None

            if not raw_bytes:
                return None

            # Decrypt
            if not self.private_key:
                if not self.load_key():
                    return None

            try:
                import base64
                raw_text = raw_bytes.decode('utf-8').strip()
                encrypted_bytes = base64.b64decode(raw_text)
                
                decrypted_bytes = self.private_key.decrypt(
                    encrypted_bytes,
                    padding.OAEP(
                        mgf=padding.MGF1(algorithm=hashes.SHA256()),
                        algorithm=hashes.SHA256(),
                        label=None
                    )
                )
                decrypted = decrypted_bytes.decode("utf-8")
            except Exception as e:
                print(f"Decryption failed: {e}")
                # Allow controlled plaintext payload cards (e.g. admin trigger card).
                try:
                    plaintext = raw_bytes.decode("utf-8", errors="ignore").strip()
                    if plaintext:
                        print(f"✅ Card Read Success! Plain payload: {plaintext}")
                        return (uid.hex(), plaintext)
                except Exception:
                    pass
                return None
            
            try:
                import json
                token_data = json.loads(decrypted)
                print("\n✅ Card Read Success! Data:")
                print("-----------------------------")
                for k, v in token_data.items():
                    print(f"{k}: {v}")
                print("-----------------------------\n")
            except Exception:
                # Fallback for non-JSON data
                print(f"✅ Card Read Success! Token Payload (String): {decrypted}")

            return (uid.hex(), decrypted)

        except Exception as e:
            print(f"Error reading card: {e}")
            # Recover from transient PN532/I2C glitches by forcing reconnect.
            if "NoneType" in str(e):
                self.connected = False
                self.pn532 = None
            return None
