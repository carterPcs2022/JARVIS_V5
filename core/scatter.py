"""ScatterEngine — AES-256-GCM encrypted Shamir shards with secure deletion."""
from __future__ import annotations
import os, json, time, secrets, hashlib, logging
from pathlib import Path
from typing import List, Tuple, Optional
from core.sharding import ShamirSharding

log = logging.getLogger(__name__)

try:
    from core.crypto import derive_key as _derive_key_obj, encrypt as _crypto_encrypt, decrypt as _crypto_decrypt, encrypt_parallel
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False
    log.warning("core.crypto unavailable — scatter encryption disabled")


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return _derive_key_obj(passphrase, salt=salt).key


def _encrypt(data: bytes, key: bytes) -> bytes:
    return _crypto_encrypt(data, key)


def _decrypt(blob: bytes, key: bytes) -> bytes:
    return _crypto_decrypt(blob, key)


def _secure_delete(path: Path):
    """Overwrite 3× random, once zeros, sync, then unlink."""
    if not path.exists():
        return
    size = path.stat().st_size
    with open(path, "r+b") as f:
        for _ in range(3):
            f.seek(0); f.write(os.urandom(size)); f.flush(); os.fsync(f.fileno())
        f.seek(0); f.write(b"\x00" * size); f.flush(); os.fsync(f.fileno())
    path.unlink()
    log.debug("Secure-deleted %s", path)


class ScatterEngine:
    SCATTER_DIR = Path.home() / ".jarvis_scatter"
    MANIFEST    = SCATTER_DIR / "resurrection_manifest.enc"

    def __init__(self):
        self.shards_total    = int(os.getenv("SCATTER_SHARDS",    "7"))
        self.shards_thresh   = int(os.getenv("SCATTER_THRESHOLD", "4"))
        self.shamir          = ShamirSharding(self.shards_thresh, self.shards_total)
        self.SCATTER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    def scatter(self, passphrase: str, payload: dict | None = None) -> dict:
        """Encrypt JARVIS core state, split into shards, distribute to nodes."""
        if not _CRYPTO_OK:
            return {"ok": False, "error": "cryptography package missing"}

        from services import scatter_nodes
        log.info("Protocol 17: scatter initiated")

        if payload is None:
            payload = self._build_payload()

        raw      = json.dumps(payload).encode()
        salt     = secrets.token_bytes(32)
        key      = _derive_key(passphrase, salt)
        enc_data = _encrypt(raw, key)

        # Zero the key from local variables (best-effort in Python)
        del key

        shards = self.shamir.split(salt + enc_data)  # salt prepended so each shard is self-describing

        nodes    = scatter_nodes.get_nodes()
        manifest = {"ts": time.time(), "shards_total": self.shards_total, "threshold": self.shards_thresh, "placements": []}
        results  = []

        for i, (x, shard_bytes) in enumerate(shards):
            node = nodes[i % len(nodes)]
            ref  = node.upload(x, shard_bytes)
            manifest["placements"].append({"node": node.name, "index": x, "ref": ref})
            results.append({"node": node.name, "ok": ref is not None})

        # Encrypt and save manifest
        m_salt = secrets.token_bytes(32)
        m_key  = _derive_key(passphrase, m_salt)
        m_enc  = _encrypt(json.dumps(manifest).encode(), m_key)
        del m_key
        self.MANIFEST.write_bytes(m_salt + m_enc)
        self.MANIFEST.chmod(0o600)

        ok_count = sum(1 for r in results if r["ok"])
        log.info("Scatter complete: %d/%d shards placed", ok_count, self.shards_total)
        return {"ok": ok_count >= self.shards_thresh, "placed": ok_count, "total": self.shards_total, "results": results}

    def reassemble(self, passphrase: str) -> dict:
        """Collect shards from nodes, decrypt, return payload."""
        if not _CRYPTO_OK:
            return {"ok": False, "error": "cryptography package missing"}
        if not self.MANIFEST.exists():
            return {"ok": False, "error": "No scatter manifest found. Run scatter first."}

        from services import scatter_nodes

        m_blob  = self.MANIFEST.read_bytes()
        m_salt  = m_blob[:32]
        m_key   = _derive_key(passphrase, m_salt)
        try:
            manifest = json.loads(_decrypt(m_blob[32:], m_key))
        except Exception:
            return {"ok": False, "error": "Wrong passphrase or corrupt manifest"}
        finally:
            del m_key

        nodes_by_name = {n.name: n for n in scatter_nodes.get_nodes()}
        collected: List[Tuple[int, bytes]] = []

        for placement in manifest["placements"]:
            if not placement.get("ref"):
                continue
            node = nodes_by_name.get(placement["node"])
            if node is None:
                continue
            data = node.download(placement["ref"])
            if data is not None:
                collected.append((placement["index"], data))

        if len(collected) < manifest["threshold"]:
            return {"ok": False, "error": f"Only {len(collected)}/{manifest['threshold']} shards recovered"}

        combined = self.shamir.reconstruct(collected)
        salt     = combined[:32]
        enc_data = combined[32:]
        key      = _derive_key(passphrase, salt)
        try:
            raw     = _decrypt(enc_data, key)
            payload = json.loads(raw)
        except Exception:
            return {"ok": False, "error": "Decryption failed — wrong passphrase?"}
        finally:
            del key

        return {"ok": True, "payload": payload, "shards_recovered": len(collected)}

    def status(self) -> dict:
        from services import scatter_nodes
        nodes = scatter_nodes.get_nodes()
        return {
            "manifest_exists": self.MANIFEST.exists(),
            "shards_total":    self.shards_total,
            "threshold":       self.shards_thresh,
            "nodes":           [{"name": n.name, "available": n.available()} for n in nodes],
        }

    # ── Internals ──────────────────────────────────────────────────────────────

    def _build_payload(self) -> dict:
        """Collect JARVIS core state to scatter."""
        payload: dict = {"ts": time.time(), "version": "v5"}
        try:
            mem_path = Path("data/memory.json")
            if mem_path.exists():
                payload["memory"] = json.loads(mem_path.read_text())
        except Exception:
            pass
        try:
            personality_path = Path("data/personality.json")
            if personality_path.exists():
                payload["personality"] = json.loads(personality_path.read_text())
        except Exception:
            pass
        payload["env_keys"] = {
            k: os.getenv(k, "")
            for k in ["GROQ_API_KEY", "JARVIS_API_TOKEN", "ANTHROPIC_API_KEY"]
        }
        return payload


# Singleton
_engine: Optional[ScatterEngine] = None

def get_engine() -> ScatterEngine:
    global _engine
    if _engine is None:
        _engine = ScatterEngine()
    return _engine
