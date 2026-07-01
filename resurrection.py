#!/usr/bin/env python3
"""
JARVIS V5 — Zero-dependency Resurrection Script (Protocol 17)
Run this on any machine to reassemble JARVIS from scattered shards.
Requires: Python 3.10+ and the cryptography package.
"""
import os, sys, json, getpass, base64, hashlib
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
except ImportError:
    sys.exit("Install cryptography first:  pip3 install cryptography")


SCATTER_DIR = Path.home() / ".jarvis_scatter"
MANIFEST    = SCATTER_DIR / "resurrection_manifest.enc"
SHARDS_DIR  = SCATTER_DIR / "local"
BACKUP_DIR  = SCATTER_DIR / "backup"


def derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
    return kdf.derive(passphrase.encode())


def decrypt(blob: bytes, key: bytes) -> bytes:
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, None)


def gf_mul(a: int, b: int, exp: list, log: list) -> int:
    if a == 0 or b == 0:
        return 0
    return exp[(log[a] + log[b]) % 255]


def gf_inv(x: int, exp: list, log: list) -> int:
    return exp[255 - log[x]]


def init_gf():
    POLY = 0x11d
    exp  = [0] * 512
    log  = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= POLY
        x &= 0xFF
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


def reconstruct(shards, threshold, exp, log):
    shards = shards[:threshold]
    secret = bytearray()
    length = len(shards[0][1])
    for i in range(length):
        points = [(x, data[i]) for x, data in shards]
        val = 0
        for j, (xj, yj) in enumerate(points):
            num = denom = 1
            for k, (xk, _) in enumerate(points):
                if k == j:
                    continue
                num   = gf_mul(num,   xk,     exp, log)
                denom = gf_mul(denom, xj ^ xk, exp, log)
            val ^= gf_mul(yj, gf_mul(num, gf_inv(denom, exp, log), exp, log), exp, log)
        secret.append(val)
    return bytes(secret)


def load_local_shards(indices: list[int]) -> dict[int, bytes]:
    shards = {}
    for d in [SHARDS_DIR, BACKUP_DIR]:
        if not d.exists():
            continue
        for p in d.glob("*.bin"):
            try:
                data = base64.b85decode(p.read_bytes())
                # Index encoded in filename: shard_N.bin or backup_N.bin
                parts = p.stem.split("_")
                idx   = int(parts[-1])
                if idx not in shards:
                    shards[idx] = data
            except Exception:
                continue
    return shards


def main():
    print("=" * 50)
    print("  J.A.R.V.I.S  Resurrection Protocol 17")
    print("=" * 50)

    if not MANIFEST.exists():
        sys.exit(f"No manifest found at {MANIFEST}\nRun scatter first from main JARVIS instance.")

    passphrase = getpass.getpass("Passphrase: ")

    # Decrypt manifest
    blob   = MANIFEST.read_bytes()
    m_key  = derive_key(passphrase, blob[:32])
    try:
        manifest = json.loads(decrypt(blob[32:], m_key))
    except Exception:
        sys.exit("Wrong passphrase or corrupt manifest.")
    finally:
        del m_key

    print(f"\nManifest: {manifest['shards_total']} shards, threshold {manifest['threshold']}")
    print(f"Created:  {manifest.get('ts', 'unknown')}\n")

    threshold = manifest["threshold"]
    exp, log  = init_gf()

    # Collect local shards
    local = load_local_shards([p["index"] for p in manifest["placements"]])
    print(f"Local shards found: {len(local)}")

    if len(local) < threshold:
        print(f"Need {threshold} shards, only found {len(local)} locally.")
        print("Ensure other node shards are accessible, then re-run.")
        # Future: prompt for missing shard bytes from user
        sys.exit(1)

    shard_list = list(local.items())
    combined   = reconstruct(shard_list, threshold, exp, log)

    salt     = combined[:32]
    enc_data = combined[32:]
    key      = derive_key(passphrase, salt)
    try:
        payload = json.loads(decrypt(enc_data, key))
    except Exception:
        sys.exit("Decryption failed — wrong passphrase or corrupt shards.")
    finally:
        del key

    print("\n✓ Identity reassembled successfully.\n")

    # Restore memory
    if "memory" in payload:
        target = Path("data/memory.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload["memory"], indent=2))
        print(f"  Memory restored → {target}")

    # Restore personality
    if "personality" in payload:
        target = Path("data/personality.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload["personality"], indent=2))
        print(f"  Personality restored → {target}")

    # Print recovered keys (user must manually set in .env)
    if "env_keys" in payload:
        print("\n  Recovered keys (add to .env):")
        for k, v in payload["env_keys"].items():
            if v:
                print(f"    {k}={v}")

    print("\nRun the server normally to bring JARVIS back online.")


if __name__ == "__main__":
    main()
