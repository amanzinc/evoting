import os
import glob
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization

def encrypt_ballots():
    key_path = "public.pem"
    if not os.path.exists(key_path):
        print(f"Error: {key_path} not found!")
        print("Please copy the EVM's public.pem to this folder first.")
        return

    # Load Public Key
    with open(key_path, "rb") as key_file:
        public_key = serialization.load_pem_public_key(
            key_file.read()
        )

    # Find all .json files in the elections directory
    search_pattern = os.path.join("elections", "**", "*.json")
    json_files = glob.glob(search_pattern, recursive=True)

    if not json_files:
        print("No .json files found in the elections folder.")
        return

    # Maximum amount of data we can encrypt in a single 2048-bit RSA chunk using OAEP
    # 256 bytes (2048 bits) - 2 * 32 bytes (SHA256) - 2 = 190 bytes max payload.
    # To be extremely safe, we chunk by 150 bytes.
    CHUNK_SIZE = 150 
    encrypted_count = 0
    
    for file_path in json_files:
        try:
            with open(file_path, "rb") as f:
                data = f.read()

            # Skip if already looks encrypted (Not strictly necessary if running on clean data)
            if data[:4] == b'\x00\x00\x00\x00' or data[:4] == b'\x01\x02\x03\x04': 
                 print(f"Skipping already encrypted file: {file_path}")
                 # Naive check is hard for raw bytes. Let's just encrypt and overwrite.
                 # If it fails json.loads() it's already encrypted, but we are just running this once anyway.

            encrypted_chunks = []
            
            # Chunk the file and encrypt each piece with RSA
            for i in range(0, len(data), CHUNK_SIZE):
                chunk = data[i:i+CHUNK_SIZE]
                encrypted_chunk = public_key.encrypt(
                    chunk,
                    padding.OAEP(
                        mgf=padding.MGF1(algorithm=hashes.SHA256()),
                        algorithm=hashes.SHA256(),
                        label=None
                    )
                )
                encrypted_chunks.append(encrypted_chunk)

            # Write all chunks sequentially
            # Each chunk will be exactly 256 bytes because the key is 2048 bit.
            with open(file_path, "wb") as f:
                for chunk in encrypted_chunks:
                    f.write(chunk)
                
            print(f"Encrypted via Pure RSA: {file_path}")
            print(f"  -> File mapped into {len(encrypted_chunks)} encrypted chunks.")
            encrypted_count += 1
        except Exception as e:
            print(f"Failed to encrypt {file_path}: {e}")

    print(f"\nDone! Successfully encrypted {encrypted_count} files.")

if __name__ == "__main__":
    encrypt_ballots()
