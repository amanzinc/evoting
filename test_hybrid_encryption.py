import os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet
from export_service import ExportService

def test_encryption_flow():
    test_votes = "test_votes.json"
    with open(test_votes, "w") as f:
        f.write('{"election": "Test", "votes": []}')
        
    try:
        # 1. Encrypt
        exporter = ExportService()
        enc_file, enc_key = exporter.hybrid_encrypt_file(test_votes, "public.pem")
        print("Encryption successful.")
        
        # 2. Decrypt (Simulating the Server)
        with open("private.pem", "rb") as key_file:
            # Note: private.pem is password protected by hardware_crypto in the real app,
            # but for this generic test we'll just try to load it or an unprotected mock key if needed.
            # Actually, let's just make a mock server keypair for the test to be safe.
            pass
            
    finally:
        if os.path.exists(test_votes): os.remove(test_votes)
        
def create_mock_server_keys():
    from cryptography.hazmat.primitives.asymmetric import rsa
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    
    with open("mock_server_private.pem", "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
        
    public_key = private_key.public_key()
    with open("mock_server_public.pem", "wb") as f:
        f.write(public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ))

if __name__ == "__main__":
    print("Creating mock server keys...")
    create_mock_server_keys()
    
    test_votes = "test_votes.json"
    with open(test_votes, "w") as f:
        f.write('{"election": "Test", "votes": [{"id": 1}]}')
        
    exporter = ExportService("private.pem") # Init with dummy evm key path
    
    print("Encrypting...")
    enc_file, enc_key = exporter.hybrid_encrypt_file(test_votes, "mock_server_public.pem")
    
    print("Decrypting simulation...")
    # Read Encrypted AES Key
    with open(enc_key, "rb") as f:
        raw_enc_key = f.read()
        
    # Read Encrypted Data
    with open(enc_file, "rb") as f:
        raw_enc_data = f.read()
        
    # Load Server Private Key
    with open("mock_server_private.pem", "rb") as f:
        server_priv = serialization.load_pem_private_key(f.read(), password=None)
        
    # Decrypt AES Key using RSA Private Key
    decrypted_aes_key = server_priv.decrypt(
        raw_enc_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    
    # Decrypt Data using AES Key
    fernet = Fernet(decrypted_aes_key)
    plaintext = fernet.decrypt(raw_enc_data)
    
    print(f"Decrypted text: {plaintext.decode('utf-8')}")
    
    # Cleanup
    os.remove("mock_server_private.pem")
    os.remove("mock_server_public.pem")
    os.remove(test_votes)
    os.remove(enc_file)
    os.remove(enc_key)
    print("Test passed and cleaned up.")
