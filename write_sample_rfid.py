import time
import sys
import json
import base64
from datetime import datetime

# Hardware libraries
try:
    import board
    import busio
    from adafruit_pn532.i2c import PN532_I2C
    from adafruit_pn532.adafruit_pn532 import MIFARE_CMD_AUTH_B
    import RPi.GPIO as GPIO
except ImportError:
    print("Warning: Hardware libraries not found. Run this on the Raspberry Pi.")

# Crypto libraries
try:
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives import serialization
except ImportError:
    print("Error: cryptography library not installed. Run 'pip install cryptography'")
    sys.exit(1)

def write_sample_rfid():
    print("=========================================")
    print("  RFID Sample Ballot Writer Utility")
    print("=========================================\n")
    
    # 1. Setup Data Payload
    sample_data = {
        "voter_id": "100",
        "eid_vector": "E1;E3", # Semicolon separated list of eligible elections
        "token_id": "69696900000",
        "booth": 1,
        "issued_at": datetime.now().isoformat()
    }
    
    # Convert to minimal JSON string to save space on the RFID card
    raw_payload = json.dumps(sample_data, separators=(',', ':'))
    print("Generated Payload:")
    print(json.dumps(sample_data, indent=2))
    print(f"\nRaw String Length: {len(raw_payload)} bytes")

    # 2. Encrypt with EVM Public Key
    print("\nEncrypting JSON payload with public.pem...")
    try:
        with open("public.pem", "rb") as key_file:
            public_key = serialization.load_pem_public_key(key_file.read())
            
        encrypted_bytes = public_key.encrypt(
            raw_payload.encode('utf-8'),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        # Base64 encode the encrypted binary data so it can be handled safely as text
        payload_base64 = base64.b64encode(encrypted_bytes)
        print(f"Encrypted Base64 Size: {len(payload_base64)} bytes")
        
    except FileNotFoundError:
        print("Error: 'public.pem' not found in the current directory.")
        return False
    except Exception as e:
        print(f"Error encrypting data: {e}")
        return False
    
    # Check if payload fits on standard 1K Mifare card (~700 usable bytes)
    if len(payload_base64) > 700:
        print("WARNING: Encrypted payload is dangerously close to exceeding standard Mifare 1K limits.")
    
    # 3. Connect to Hardware
    print("\nConnecting to PN532 RFID Reader...")
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        pn532 = PN532_I2C(i2c, debug=False)
        pn532.SAM_configuration()
        print("Connected.")
    except Exception as e:
        print(f"Hardware connection failed: {e}")
        print("Make sure you are running this on the Raspberry Pi with I2C enabled.")
        return False
    
    # 4. Wait for Card
    print("\n>>> PLACE SENSOR CARD ON READER TO WRITE <<<")
    uid = None
    while uid is None:
        uid = pn532.read_passive_target(timeout=0.5)
    print(f"Card Detected! UID: {[hex(i) for i in uid]}")

    KEY_DEFAULT = b'\xFF' * 6
    START_BLOCK = 4
    
    # 5. Chunk Data for Mifare standard blocks (16 bytes per block)
    chunks = [payload_base64[i:i+16] for i in range(0, len(payload_base64), 16)]
    
    # End padding for the last chunk
    if len(chunks[-1]) < 16:
        chunks[-1] += b'\x00' * (16 - len(chunks[-1]))
    
    # Add a final empty block to signal EOF to the reader securely
    if len(chunks[-1]) == 16:
        chunks.append(b'\x00' * 16)
        
    block_no = START_BLOCK
    chunk_idx = 0
    
    print(f"\nWriting {len(chunks)} blocks to card...")
    
    # 6. Write Loop
    while chunk_idx < len(chunks):
        # Skip trailer memory blocks (every 4th block stores sector keys)
        if (block_no + 1) % 4 == 0:
            block_no += 1
            continue
            
        # Authenticate with Sector
        auth = pn532.mifare_classic_authenticate_block(
            uid, block_no, MIFARE_CMD_AUTH_B, KEY_DEFAULT
        )
        
        if not auth:
            print(f"Authentication failed on block {block_no}. Is the card formatted correctly?")
            return False
            
        # Write 16-byte chunk
        try:
            success = pn532.mifare_classic_write_block(block_no, chunks[chunk_idx])
            if not success:
               print(f"Write failed to block {block_no}.")
               return False
            print(f"  [+] Block {block_no} written (chunk {chunk_idx + 1}/{len(chunks)})")
        except Exception as e:
            print(f"Write Exception on block {block_no}: {e}")
            return False
            
        block_no += 1
        chunk_idx += 1
        
    print("\n=========================================")
    print("  WRITE SUCCESSFUL! Card is ready.")
    print("=========================================")
    return True

if __name__ == "__main__":
    write_sample_rfid()
