"""Shamir's Secret Sharing over GF(2^8) — pure stdlib, no dependencies."""
from __future__ import annotations
import os, secrets
from typing import List, Tuple

# GF(2^8) with primitive polynomial x^8 + x^4 + x^3 + x^2 + 1 (0x11d)
_POLY = 0x11d
_EXP  = [0] * 512
_LOG  = [0] * 256

def _init_tables():
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= _POLY
        x &= 0xFF
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]

_init_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[(_LOG[a] + _LOG[b]) % 255]


def _gf_pow(x: int, p: int) -> int:
    if x == 0:
        return 0
    return _EXP[(_LOG[x] * p) % 255]


def _gf_inv(x: int) -> int:
    if x == 0:
        raise ZeroDivisionError("no inverse of 0 in GF(2^8)")
    return _EXP[255 - _LOG[x]]


def _eval_poly(coeffs: List[int], x: int) -> int:
    """Evaluate polynomial with given coefficients at point x in GF(2^8)."""
    result = 0
    for c in reversed(coeffs):
        result = _gf_mul(result, x) ^ c
    return result


class ShamirSharding:
    """Split and reconstruct secrets using Shamir's Secret Sharing."""

    def __init__(self, threshold: int, total: int):
        if threshold > total:
            raise ValueError("threshold must be ≤ total shards")
        if total > 255:
            raise ValueError("total shards must be ≤ 255")
        self.threshold = threshold
        self.total     = total

    def split(self, secret: bytes) -> List[Tuple[int, bytes]]:
        """Split secret into (total) shards, any (threshold) can reconstruct."""
        shards = [(i, bytearray()) for i in range(1, self.total + 1)]

        for byte in secret:
            # Random polynomial of degree (threshold-1) with secret as constant term
            coeffs = [byte] + [secrets.randbelow(256) for _ in range(self.threshold - 1)]
            for idx, (x, buf) in enumerate(shards):
                buf.append(_eval_poly(coeffs, x))

        return [(x, bytes(buf)) for x, buf in shards]

    def reconstruct(self, shards: List[Tuple[int, bytes]]) -> bytes:
        """Reconstruct secret from at least (threshold) shards."""
        if len(shards) < self.threshold:
            raise ValueError(f"need at least {self.threshold} shards, got {len(shards)}")
        shards = shards[:self.threshold]
        secret = bytearray()
        length = len(shards[0][1])

        for i in range(length):
            points = [(x, data[i]) for x, data in shards]
            # Lagrange interpolation at x=0
            val = 0
            for j, (xj, yj) in enumerate(points):
                num = denom = 1
                for k, (xk, _) in enumerate(points):
                    if k == j:
                        continue
                    num   = _gf_mul(num,   xk)
                    denom = _gf_mul(denom, xj ^ xk)
                val ^= _gf_mul(yj, _gf_mul(num, _gf_inv(denom)))
            secret.append(val)

        return bytes(secret)
