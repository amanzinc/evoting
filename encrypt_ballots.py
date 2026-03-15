import os
import glob
from cryptography.fernet import Fernet

def encrypt_files():
    key_path = "secret.key"
    if not os.path.exists(key_path):
        print("Error: secret.key not found!")
        return

    with open(key_path, "rb") as kf:
        key = kf.read().strip()
    
    f_crypto = Fernet(key)

    # Find all .json files in the elections directory
    search_pattern = os.path.join("elections", "**", "*.json")
    json_files = glob.glob(search_pattern, recursive=True)

    if not json_files:
        print("No .json files found in the elections folder.")
        return

    encrypted_count = 0
    for file_path in json_files:
        try:
            with open(file_path, "rb") as f:
                data = f.read()

            # Skip if already encrypted (a bit naive, but will check if it starts with gAAAAA, characteristic of Fernet)
            if data.startswith(b"gAAAAA"):
                print(f"Skipping already encrypted file: {file_path}")
                continue

            encrypted_data = f_crypto.encrypt(data)
            
            with open(file_path, "wb") as f:
                f.write(encrypted_data)
                
            print(f"Encrypted: {file_path}")
            encrypted_count += 1
        except Exception as e:
            print(f"Failed to encrypt {file_path}: {e}")

    print(f"\nDone! Successfully encrypted {encrypted_count} files.")

if __name__ == "__main__":
    encrypt_files()
