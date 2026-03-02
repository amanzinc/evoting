import time
import sys
import board
import busio
from adafruit_pn532.i2c import PN532_I2C
from adafruit_pn532.adafruit_pn532 import MIFARE_CMD_AUTH_B
import RPi.GPIO as GPIO # if error, might need to adjust or remove

def write_rfid():
    # 1. Connect
    print("Connecting to PN532...")
    i2c = busio.I2C(board.SCL, board.SDA)
    pn532 = PN532_I2C(i2c, debug=False)
    pn532.SAM_configuration()
    print("Connected.")

    # 2. Setup Data
    payload = "UpBRu7R1ZJx7qBg3He/zqu7JF0bftH4FahTMKwNhvRGWlU9xE59BegiD9OrL+LKHs+Ex5dCBwOhvUJAHLTQG1wAQFIiDHVSBVLDH4XFKUOHZ7GE+5BiWBwzMznQSNrgLyV+JdJLmXyEK/AHFa+9KtFBXZQnarJKLEQ3SoS8D56QXRe2IvmYsnzTZhJpTXUjapxwZegjsHfb/o+JhrE38GsaXRC5HD9C7mMogTWAh1/YNV+9jM8cQS9PcZQbzQTCj6xrf1Q1APyuWg3fVEt3UZ0n/jYlNnDdxBptFDNo0pG0OCEaLcIn9iqVoK1bOct8u/PXXsZgxK6wbacdG84KXTw=="
    payload_bytes = payload.encode('utf-8')
    
    # 3. Wait for Card
    print("Place card on reader to write...")
    uid = None
    while uid is None:
        uid = pn532.read_passive_target(timeout=0.5)
    print(f"Card Detected: {[hex(i) for i in uid]}")

    KEY_DEFAULT = b'\xFF' * 6
    START_BLOCK = 4
    
    # Calculate blocks needed
    chunks = [payload_bytes[i:i+16] for i in range(0, len(payload_bytes), 16)]
    
    # Pad last chunk if needed
    if len(chunks[-1]) < 16:
        chunks[-1] += b'\x00' * (16 - len(chunks[-1]))
    
    # Add an empty block at the end to act as termination (b'\x00') if perfectly fits
    if len(chunks[-1]) == 16:
        chunks.append(b'\x00' * 16)
        
    block_no = START_BLOCK
    chunk_idx = 0
    
    while chunk_idx < len(chunks):
        # Skip trailer blocks
        if (block_no + 1) % 4 == 0:
            block_no += 1
            continue
            
        # Authenticate
        auth = pn532.mifare_classic_authenticate_block(
            uid, block_no, MIFARE_CMD_AUTH_B, KEY_DEFAULT
        )
        
        if not auth:
            print(f"Auth failed on block {block_no}")
            return False
            
        # Write
        print(f"Writing block {block_no} (chunk {chunk_idx + 1}/{len(chunks)})...")
        try:
            # We specifically want to write 16 raw bytes
            success = pn532.mifare_classic_write_block(block_no, chunks[chunk_idx])
            if not success:
               print(f"Failed writing to block {block_no}.")
               return False
        except Exception as e:
            print(f"Write Exception on block {block_no}: {e}")
            return False
            
        block_no += 1
        chunk_idx += 1
        
    print("Write Successful!")
    return True

if __name__ == "__main__":
    write_rfid()
