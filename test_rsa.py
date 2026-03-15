import argparse
from cryptography.hazmat.primitives import serialization
import hardware_crypto

def test():
    try:
        passphrase = hardware_crypto.get_hardware_passphrase()
        print(f"Testing with Passphrase: {passphrase}")
        with open("private.pem", "rb") as kf:
             data = kf.read()
             
        private_key = serialization.load_pem_private_key(
             data,
             password=passphrase
        )
        print("SUCCESS! private.pem unlocked!")
    except Exception as e:
        print(f"FAILED TO UNLOCK: {e}")
        
if __name__ == "__main__":
    test()
