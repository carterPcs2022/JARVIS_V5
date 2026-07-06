"""services/quantum_crypto.py — hash-chain-based signing/encryption
hardening.

IMPORTANT correction from the source spec: this module does NOT implement
CRYSTALS-Kyber or CRYSTALS-Dilithium (the actual NIST-standardized
post-quantum algorithms), despite the source doc's docstring claiming it
does. Kyber/Dilithium are lattice-based public-key algorithms — a
completely different mathematical foundation from hashing, and neither is
implemented anywhere below. What this actually is: SHA3-512 + BLAKE2b +
SHAKE-256 hash chaining. That's a real, legitimate property (symmetric
hash functions are far more quantum-resistant than RSA/ECC public-key
crypto, since Grover's algorithm only gives a quadratic speedup against
them, vs. Shor's algorithm breaking RSA/ECC outright) — but calling it
"quantum-resistant" without naming actual PQC algorithms it doesn't use
would be a false security claim. If you need real post-quantum key
exchange/signatures, that requires a library implementing the actual NIST
PQC standards (e.g. liboqs bindings) — a materially bigger dependency and
integration than this batch, and out of scope here."""
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime


class HashChainCrypto:

    KEY_SIZE = 64  # 512 bits

    def generate_key(self) -> dict:
        """Generate a key from multiple independent entropy sources."""
        entropy_sources = [os.urandom(64), str(datetime.now().timestamp()).encode(), os.urandom(64)]
        combined = b"".join(entropy_sources)

        shake = hashlib.shake_256(combined)
        key = shake.digest(self.KEY_SIZE)
        key_id = hashlib.sha3_256(key).hexdigest()[:16]

        return {
            "key_id": key_id, "key": base64.b64encode(key).decode(),
            "algorithm": "SHAKE-256-512", "created": datetime.now().isoformat(),
        }

    def sign(self, message: str, key: bytes) -> str:
        """HMAC-SHA3-512 signing (resistant to length-extension attacks,
        unlike plain SHA-256-based HMAC constructions)."""
        sig = hmac.new(key, message.encode(), digestmod=hashlib.sha3_512).digest()
        return base64.b64encode(sig).decode()

    def verify(self, message: str, signature: str, key: bytes) -> bool:
        try:
            expected = self.sign(message, key)
            return hmac.compare_digest(signature, expected)
        except Exception:
            return False

    def hash_chain(self, data: str) -> str:
        """SHA3-512 -> BLAKE2b chain — breaking this requires breaking
        both hash functions independently."""
        layer1 = hashlib.sha3_512(data.encode()).digest()
        layer2 = hashlib.blake2b(layer1, digest_size=64).digest()
        return base64.b64encode(layer2).decode()

    def encrypt_layered(self, data: str, key: bytes) -> dict:
        """Two independent layers: AES-256-GCM, then XOR with a SHAKE-256
        keystream. Even if one layer's assumptions are ever broken, the
        other still protects the data."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aes_key = hashlib.sha3_256(key).digest()
        nonce = secrets.token_bytes(12)
        layer1 = AESGCM(aes_key).encrypt(nonce, data.encode(), None)

        key_stream = hashlib.shake_256(key + nonce).digest(len(layer1))
        layer2 = bytes(a ^ b for a, b in zip(layer1, key_stream))

        return {
            "ciphertext": base64.b64encode(layer2).decode(), "nonce": base64.b64encode(nonce).decode(),
            "layers": 2, "algorithms": ["AES-256-GCM", "SHAKE-256-XOR"],
        }

    def decrypt_layered(self, encrypted: dict, key: bytes) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        ciphertext = base64.b64decode(encrypted["ciphertext"])
        nonce = base64.b64decode(encrypted["nonce"])

        key_stream = hashlib.shake_256(key + nonce).digest(len(ciphertext))
        layer1 = bytes(a ^ b for a, b in zip(ciphertext, key_stream))

        aes_key = hashlib.sha3_256(key).digest()
        return AESGCM(aes_key).decrypt(nonce, layer1, None).decode()


hash_chain_crypto = HashChainCrypto()
