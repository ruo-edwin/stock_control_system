from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import base64

PEM_PUBLIC = b"""-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEkz341S9FpJWMvjfDo72cSlFxxlTh
cLBcfHlhX3EsaHHdcnahSb8Ra+dFq/Uv7qrDNfRyD3w3wmWqa0+6cA7jJw==
-----END PUBLIC KEY-----"""

pub = serialization.load_pem_public_key(PEM_PUBLIC)

# Raw uncompressed point (65 bytes) -> base64url (no "=")
raw = pub.public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint
)

vapid_public_key = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("utf-8")
print("VAPID_PUBLIC_KEY =", vapid_public_key)
