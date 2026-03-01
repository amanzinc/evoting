import os
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from hardware_crypto import get_hardware_passphrase

def generate_keys():
    print("Generating 2048-bit RSA Hardware-Bound Keys...")
    
    # 1. Generate Private Key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # 2. Get the unique hardware passphrase
    passphrase = get_hardware_passphrase()
    print("Locked with Hardware Identity.")

    # 3. Serialize Private Key (Encrypted with Passphrase)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase)
    )

    with open('private.pem', 'wb') as f:
        f.write(private_pem)

    # 4. Serialize Public Key (Unencrypted)
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    with open('public.pem', 'wb') as f:
        f.write(public_pem)

    print("Success! Generated 'public.pem' and 'private.pem'.")
    print("Give 'public.pem' to the Election Admin to encrypt ballots.")
    print("Keep 'private.pem' on this exact Raspberry Pi.")

if __name__ == "__main__":
    generate_keys()
