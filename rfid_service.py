import time
import sys
import os

try:
    import rfid_crypto
except ImportError:
    rfid_crypto = None

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
        self.connected = False

        self.START_BLOCK = 4
        self.MAX_BLOCK_NO = 255
        self.KEY_DEFAULT = b'\xFF' * 6

        # RF cooldown tracking: after a card halts (auth failure), we must wait
        # before issuing the next read_passive_target so the card's RF capacitor
        # can drain and the card can fully re-initialize.  400 ms is empirically
        # reliable; shorter values cause persistent halt loops.
        self._last_halt_time = 0.0
        self.HALT_RECOVERY_DELAY = 0.40   # seconds

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
        """No-op: RFID encryption uses a shared AES key from rfid_crypto."""
        return True

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
        for attempt in range(1, 6): # Increased to 5 attempts for boot timing
            try:
                self._close_bus()
                # On very early boot, the PN532 takes a moment to boot its I2C interface.
                time.sleep(0.5) 
                
                # On RPi this uses board.SCL/SDA.
                self.i2c = busio.I2C(board.SCL, board.SDA)
                time.sleep(0.2)
                self.pn532 = PN532_I2C(self.i2c, debug=False)
                time.sleep(0.2)
                self.pn532.SAM_configuration()
                self.connected = True
                print("RFID Reader Connected Successfully.")
                return True
            except Exception as e:
                last_error = e
                print(f"RFID connection attempt {attempt} failed: {e}")
                self._close_bus()
                # Exponential backoff on fail (0.5s, 1.0s, 1.5s, 2.0s...)
                time.sleep(0.5 * attempt)

        print(f"RFID Connection Failed after retries: {last_error}")
        return False

    def is_trailer_block(self, block_no):
        sector_no = self._block_to_sector(block_no)
        sector_first_block, blocks_per_sector = self._sector_layout(sector_no)
        return block_no == (sector_first_block + blocks_per_sector - 1)

    def _auth_block(self, uid, block_no):
        """Authenticate a single block with 3 retries and exponential backoff."""
        delays = [0.05, 0.15, 0.30]   # 50 ms → 150 ms → 300 ms
        for delay in delays:
            try:
                ok = self.pn532.mifare_classic_authenticate_block(
                    uid, block_no, MIFARE_CMD_AUTH_B, self.KEY_DEFAULT
                )
                if ok:
                    return True
            except Exception:
                pass
            time.sleep(delay)
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

    def write_card_payload(self, payload_text, wait_seconds=20):
        """AES-256-GCM encrypt payload_text and write to card data blocks."""
        encrypted_b64 = rfid_crypto.encrypt_payload(payload_text)
        return self.write_plaintext_card_payload(encrypted_b64, wait_seconds=wait_seconds)

    def write_plaintext_card_payload(self, payload_text, wait_seconds=20):
        """Write a raw (unencrypted) string to card data blocks (null-terminated)."""
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

    def _read_aes_payload(self, uid, max_data_blocks=None):
        """
        Read RFID blocks until null terminator, then AES-256-GCM decrypt.
        Used for both polling officer and voter cards.
        Returns (uid_hex, plaintext_str), ("error", message), or None.
        """
        block_no = self.START_BLOCK
        raw_bytes = bytearray()
        blocks_read = 0
        last_authed_sector = -1

        while block_no <= self.MAX_BLOCK_NO:
            if max_data_blocks is not None and blocks_read >= max_data_blocks:
                break

            while self.is_trailer_block(block_no):
                block_no += 1
            if block_no > self.MAX_BLOCK_NO:
                break

            current_sector = self._block_to_sector(block_no)
            if current_sector != last_authed_sector:
                if not self._auth_block(uid, block_no):
                    self._last_halt_time = time.monotonic()
                    print(f"Auth failed for block {block_no}. Card is likely halted. Aborting this scan.")
                    return ("error", "Auth timeout.\nHold card longer.")
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

            blocks_read += 1
            if b'\x00' in data:
                raw_bytes.extend(data.split(b'\x00')[0])
                break
            else:
                raw_bytes.extend(data)

            block_no += 1

        if not raw_bytes:
            return None

        b64_text = raw_bytes.decode('ascii', errors='ignore').strip()
        if not b64_text:
            return None

        print(f"DEBUG: Read raw b64 from RFID ({blocks_read} blocks): {repr(b64_text)}")

        try:
            plaintext = rfid_crypto.decrypt_payload(b64_text)
        except Exception as e:
            print(f"RFID AES decryption failed: {e}")
            # Force a cooldown so the same unprovisioned card isn't hammered.
            self._last_halt_time = time.monotonic()
            return ("error", "Card not provisioned")

        return (uid.hex(), plaintext)

    def _read_plain_payload(self, uid, max_data_blocks=10):
        """Read a polling-officer card (AES-256-GCM encrypted)."""
        result = self._read_aes_payload(uid, max_data_blocks=max_data_blocks)
        if result and result[0] != "error":
            print(f"✅ Officer card read success: {result[1]}")
        return result

    def _read_encrypted_payload(self, uid):
        """Read a voter card (AES-256-GCM encrypted)."""
        result = self._read_aes_payload(uid)
        if result and result[0] != "error":
            import json
            try:
                token_data = json.loads(result[1])
                print("\n✅ Voter card read success! Data:")
                print("-----------------------------")
                for k, v in token_data.items():
                    print(f"{k}: {v}")
                print("-----------------------------\n")
            except Exception:
                print(f"✅ Voter card read success (raw): {result[1]}")
        return result

    def _read_auto_payload(self, uid, min_required_sectors, min_required_blocks):
        """Legacy auto-detect mode. Delegates to AES decryption."""
        return self._read_aes_payload(uid)

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def read_card(self, mode='auto', min_required_sectors=None, min_required_blocks=None):
        """
        Read an RFID card and return its payload.

        Parameters
        ----------
        mode : str
            'plain'     – Polling officer card. AES-256-GCM encrypted, limited read.
            'encrypted' – Voter card. AES-256-GCM encrypted, full card read.
            'auto'      – Legacy: same as 'encrypted'. Use explicit modes for new callers.

        Returns
        -------
        (uid_hex, payload_str) on success, or None on failure / card not present.
        """
        if not self.connected:
            return None

        # ── RF Halt-Recovery Cooldown ─────────────────────────────────────────
        # After a MIFARE Classic card halts (auth failure) the card's on-board
        # capacitor must drain before the card can re-initialise.  Calling
        # read_passive_target too soon keeps detecting the same halted card UID
        # and auth will always fail again.  We enforce a minimum gap here.
        elapsed_since_halt = time.monotonic() - self._last_halt_time
        if elapsed_since_halt < self.HALT_RECOVERY_DELAY:
            remaining = self.HALT_RECOVERY_DELAY - elapsed_since_halt
            time.sleep(remaining)

        try:
            raw_uid = self.pn532.read_passive_target(timeout=0.5)
            uid = self._normalize_uid(raw_uid)
            if uid is None:
                return None

            print(f"Card Detected: {list(uid)}")

            if mode == 'plain':
                res = self._read_plain_payload(uid, max_data_blocks=12)
            elif mode == 'encrypted':
                res = self._read_encrypted_payload(uid)
            else:
                # 'auto' mode fallback
                res = self._read_auto_payload(uid, min_required_sectors, min_required_blocks)

            if res is None:
                # Return None (not an ERROR tuple) so that scan loops treat this
                # the same as "no card yet" and simply retry after a short sleep.
                return None
            return res

        except Exception as e:
            print(f"Error reading card: {e}")
            # Recover from transient PN532/I2C glitches by forcing reconnect.
            if "NoneType" in str(e) or "unexpected command" in str(e).lower():
                self.connected = False
                self.pn532 = None
            return None



