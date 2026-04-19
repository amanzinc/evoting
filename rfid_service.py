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
        self.project_dir = os.path.dirname(os.path.abspath(__file__))
        self.private_key = None
        self.connected = False
        
        self.START_BLOCK = 4
        self.MAX_BLOCK_NO = 255
        self.MIN_REQUIRED_SECTORS = 21   # Voter card spans at least 21 sectors
        self.VOTER_REQUIRED_BLOCKS = 22  # Voter payload is exactly 22 data blocks
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
        key_path = self.key_path
        if not os.path.isabs(key_path):
            key_path = os.path.join(self.project_dir, key_path)

        if not os.path.exists(key_path):
            print(f"Key file {key_path} not found.")
            return False
            
        try:
            passphrase = hardware_crypto.get_hardware_passphrase()
            with open(key_path, "rb") as kf:
                self.private_key = serialization.load_pem_private_key(
                    kf.read(),
                    password=passphrase
                )
            self.key_path = key_path
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

        last_authed_sector = -1
        for idx, block_no in enumerate(data_blocks[:len(chunks)]):
            current_sector = self._block_to_sector(block_no)
            if current_sector != last_authed_sector:
                if not self._auth_block(uid, block_no):
                    raise RuntimeError(f"Auth failed for block {block_no}")
                last_authed_sector = current_sector

            ok = self.pn532.mifare_classic_write_block(block_no, chunks[idx])
            if not ok:
                raise RuntimeError(f"Write failed for block {block_no}")

        return uid.hex()

    # ─────────────────────────────────────────────────────────────
    # Internal block-reading helpers
    # ─────────────────────────────────────────────────────────────

    def _read_plain_payload(self, uid, max_data_blocks=10):
        """
        Read a plain-text (admin/officer) card.
        Reads blocks until a null terminator is found, up to `max_data_blocks`.
        Retries auth failures once to handle transient PN532 glitches.
        No minimum sector requirement. No decryption.
        Returns (uid_hex, raw_text) or None.
        """
        block_no = self.START_BLOCK
        raw_bytes = bytearray()
        blocks_read = 0
        last_authed_sector = -1

        while block_no <= self.MAX_BLOCK_NO and blocks_read < max_data_blocks:
            # Skip trailer blocks
            while self.is_trailer_block(block_no):
                block_no += 1
            if block_no > self.MAX_BLOCK_NO:
                break

            current_sector = self._block_to_sector(block_no)
            if current_sector != last_authed_sector:
                # Retry auth once — transient PN532 I2C glitches can cause false-fail
                auth = False
                for _attempt in range(2):
                    try:
                        auth = self.pn532.mifare_classic_authenticate_block(
                            uid, block_no, MIFARE_CMD_AUTH_B, self.KEY_DEFAULT
                        )
                        if auth:
                            break
                        time.sleep(0.05)
                    except Exception:
                        time.sleep(0.05)

                if not auth:
                    # MIFARE Classic cards halt on auth failure. We must give up on this scan attempt
                    # so the outer loop will call `read_passive_target` again to wake it up!
                    # We can't just `continue` to the next block while the card is halted!
                    print(f"Auth failed for block {block_no}. Card is likely halted. Aborting this scan.")
                    return None


                last_authed_sector = current_sector

            try:
                raw_block = self.pn532.mifare_classic_read_block(block_no)
            except Exception:
                block_no += 1
                continue

            data = self._normalize_block_data(raw_block)
            if data is None:
                block_no += 1
                continue

            # Stop at null terminator — plain payloads are null-terminated
            if b'\x00' in data:
                raw_bytes.extend(data.split(b'\x00')[0])
                break
            else:
                raw_bytes.extend(data)

            blocks_read += 1
            block_no += 1

        if not raw_bytes:
            return None

        raw_text = raw_bytes.decode('utf-8', errors='ignore').strip()
        if not raw_text:
            return None

        print(f"✅ Plain card read success: {raw_text}")
        return (uid.hex(), raw_text)

    def _read_encrypted_payload(self, uid):
        """
        Read an encrypted voter card.
        Reads blocks until a null terminator is found, collecting ALL bytes
        (same stop-on-null approach as the original working code).
        NO sector-count enforcement — RSA decryption is the security guarantee.
        Retries auth once per block to handle transient PN532 glitches.
        Returns (uid_hex, decrypted_json_str) or None.
        """
        block_no = self.START_BLOCK
        raw_bytes = bytearray()
        read_blocks = 0
        last_authed_sector = -1

        while block_no <= self.MAX_BLOCK_NO:
            # Skip trailer blocks
            while self.is_trailer_block(block_no):
                block_no += 1
            if block_no > self.MAX_BLOCK_NO:
                break

            current_sector = self._block_to_sector(block_no)
            if current_sector != last_authed_sector:
                # Retry auth once for transient glitches
                auth = False
                for _attempt in range(2):
                    try:
                        auth = self.pn532.mifare_classic_authenticate_block(
                            uid, block_no, MIFARE_CMD_AUTH_B, self.KEY_DEFAULT
                        )
                        if auth:
                            break
                        time.sleep(0.05)
                    except Exception:
                        time.sleep(0.05)

                if not auth:
                    print(f"Auth failed for block {block_no}. Card is likely halted. Aborting this scan.")
                    return None


                last_authed_sector = current_sector

            try:
                raw_block = self.pn532.mifare_classic_read_block(block_no)
            except Exception:
                block_no += 1
                continue

            data = self._normalize_block_data(raw_block)
            if data is None:
                block_no += 1
                continue

            read_blocks += 1

            # The base64-encoded ciphertext ends with MIFARE null padding.
            # Stop on the first null byte — same approach as original working code.
            if b'\x00' in data:
                raw_bytes.extend(data.split(b'\x00')[0])
                break
            else:
                raw_bytes.extend(data)

            block_no += 1

        if read_blocks < 21:
            print(f"Encrypted card read rejected: Expected at least 21 blocks, got {read_blocks}.")
            return None

        if not raw_bytes:
            print("Encrypted card read: no data collected.")
            return None

        raw_text = raw_bytes.decode('utf-8', errors='ignore').strip()
        print(f"DEBUG: Read raw text from RFID: {repr(raw_text)}")
        if not raw_text:
            return None

        # Load private key if not already loaded
        if not self.private_key:
            if not self.load_key():
                print("Voter card decryption failed: private key not available.")
                return None

        try:
            import base64
            compact = "".join(raw_text.split())

            # Quick sanity check: ciphertext must look like base64 and be long enough
            # for RSA-2048 OAEP output (~344 base64 chars). If it's short/plain text
            # (e.g. officer phrase card scanned on voter loop), return as plain so
            # on_card_scanned can route it to the officer menu.
            base64_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
            if len(compact) < 128 or not all(ch in base64_chars for ch in compact):
                print(f"✅ Plain card on voter loop (not ciphertext): {raw_text}")
                return (uid.hex(), raw_text)

            compact += "=" * ((4 - len(compact) % 4) % 4)
            encrypted_bytes = base64.b64decode(compact)
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
            print(f"Voter card decryption failed: {e}")
            # If decryption failed but we have readable text, return it as plain so
            # the caller (on_card_scanned) can still handle officer phrase cards.
            if raw_text and len(raw_text) < 64:
                print(f"Returning as plain text fallback: {raw_text}")
                return (uid.hex(), raw_text)
            return None

        try:
            import json
            token_data = json.loads(decrypted)
            print("\n✅ Voter card read success! Data:")
            print("-----------------------------")
            for k, v in token_data.items():
                print(f"{k}: {v}")
            print("-----------------------------\n")
        except Exception:
            print(f"✅ Voter card read success (raw): {decrypted}")

        return (uid.hex(), decrypted)

    def _read_auto_payload(self, uid, min_required_sectors, min_required_blocks):
        """
        Legacy auto-detect mode: reads blocks, then decides between plain and
        encrypted via a base64 heuristic. Kept for backward compatibility only.
        """
        required_sectors = self.MIN_REQUIRED_SECTORS if min_required_sectors is None else int(min_required_sectors)
        required_blocks = 1 if min_required_blocks is None else int(min_required_blocks)
        if required_sectors < 1:
            required_sectors = 1
        if required_blocks < 1:
            required_blocks = 1

        block_no = self.START_BLOCK
        raw_bytes = bytearray()
        read_sectors = set()
        read_blocks = 0
        last_authed_sector = -1
        payload_complete = False

        while block_no <= self.MAX_BLOCK_NO:
            while self.is_trailer_block(block_no):
                block_no += 1
            if block_no > self.MAX_BLOCK_NO:
                break

            # Retry auth once for transient glitches, matching other read loops
            auth = False
            for _attempt in range(2):
                try:
                    auth = self.pn532.mifare_classic_authenticate_block(
                        uid, block_no, MIFARE_CMD_AUTH_B, self.KEY_DEFAULT
                    )
                    if auth:
                        break
                    time.sleep(0.05)
                except Exception:
                    time.sleep(0.05)

            if not auth:
                print(f"Auth failed for block {block_no}. Card is likely halted. Aborting this scan.")
                return None

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
            read_blocks += 1

            if not payload_complete:
                if b'\x00' in data:
                    raw_bytes.extend(data.split(b'\x00')[0])
                    payload_complete = True
                else:
                    raw_bytes.extend(data)

            if payload_complete:
                break

            block_no += 1

        if not raw_bytes:
            return None

        raw_text = raw_bytes.decode('utf-8', errors='ignore').strip()
        if not raw_text:
            return None

        # Heuristic: if it looks like base64 ciphertext → try to decrypt
        compact = "".join(raw_text.split())
        base64_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
        looks_like_base64_ciphertext = (
            len(compact) >= 128
            and len(compact) % 4 == 0
            and all(ch in base64_chars for ch in compact)
        )

        if not looks_like_base64_ciphertext:
            print(f"✅ Card Read Success! Plain payload: {raw_text}")
            return (uid.hex(), raw_text)

        if not self.private_key:
            if not self.load_key():
                return None

        try:
            import base64
            encrypted_bytes = base64.b64decode(compact)
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
            # Fallback: return as plain text
            try:
                if raw_text:
                    print(f"✅ Card Read Success! Plain payload (fallback): {raw_text}")
                    return (uid.hex(), raw_text)
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
            print(f"✅ Card Read Success! Token Payload (String): {decrypted}")

        return (uid.hex(), decrypted)

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def read_card(self, mode='auto', min_required_sectors=None, min_required_blocks=None):
        """
        Read an RFID card and return its payload.

        Parameters
        ----------
        mode : str
            'plain'     – Admin/officer card. Plain-text payload, no decryption.
                          Reads until null terminator; no minimum sector requirement.
            'encrypted' – Voter card. RSA-encrypted payload across 22 data blocks.
                          Enforces MIN_REQUIRED_SECTORS and VOTER_REQUIRED_BLOCKS,
                          then decrypts with the hardware-bound private key.
            'auto'      – Legacy heuristic: auto-detect by base64 inspection.
                          Use explicit modes for new callers.

        Returns
        -------
        (uid_hex, payload_str) on success, or None on failure / card not present.
        """
        if not self.connected:
            return None

        try:
            raw_uid = self.pn532.read_passive_target(timeout=0.5)
            uid = self._normalize_uid(raw_uid)
            if uid is None:
                return None

            print(f"Card Detected: {list(uid)}")

            if mode == 'plain':
                return self._read_plain_payload(uid, max_data_blocks=12)
            elif mode == 'encrypted':
                return self._read_encrypted_payload(uid)
            else:
                # 'auto' — legacy backward-compat path
                return self._read_auto_payload(uid, min_required_sectors, min_required_blocks)

        except Exception as e:
            print(f"Error reading card: {e}")
            # Recover from transient PN532/I2C glitches by forcing reconnect.
            if "NoneType" in str(e) or "unexpected command" in str(e).lower():
                self.connected = False
                self.pn532 = None
            return None



