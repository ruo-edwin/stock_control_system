import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

DER_B64 = """
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgRDqaATSjH2W1/5KJ
sQqn8Nmpo2v6aUFvte9D9AIVKhmhRANCAASTPfjVL0WklYy+N8OjvZxKUXHGVOFw
sFx8eWFfcSxocd1ydqFJvxFr50Wr9S/uqsM19HIPfDfCZaprT7pwDuMn
""".replace("\n", "").strip()

der = base64.b64decode(DER_B64)

key = serialization.load_der_private_key(der, password=None, backend=default_backend())

pem = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)

print(pem.decode())

