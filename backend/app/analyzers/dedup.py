"""Dedup para texto: hash exato (SHA-256) e near-duplicates (MinHash LSH).

Texto: content_hash = sha256(text); near-duplicate via MinHash (LSH) em vez de dHash.
Canônico eleito por maior token_count; desempate por lex id.
"""
import hashlib

DETECTOR_VERSION = "2"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _as_int(h: str | int) -> int:
    if isinstance(h, int):
        return h
    h = h.strip()
    if h.startswith("0b"):
        return int(h, 2)
    if len(h) == 64 and set(h) <= {"0", "1"}:
        return int(h, 2)
    return int(h, 16)


def _minhash(text: str, k: int = 5, num_hashes: int = 128) -> list[int]:
    """MinHash signature for a text (k-shingles)."""
    shingles = set()
    clean = text.replace("\n", " ").replace("\t", " ")
    for i in range(len(clean) - k + 1):
        shingles.add(clean[i:i + k])
    if not shingles:
        return []
    a = [i * 7919 + 31 for i in range(num_hashes)]
    b = [i * 6271 + 17 for i in range(num_hashes)]
    sig = [float("inf")] * num_hashes
    for sh in shingles:
        h = int(hashlib.sha256(sh.encode()).hexdigest()[:16], 16)
        for i in range(num_hashes):
            val = (a[i] * h + b[i]) % (2 ** 32)
            if val < sig[i]:
                sig[i] = val
    return sig


def _jaccard_from_signatures(a: list[int], b: list[int]) -> float:
    """Estimate Jaccard similarity from MinHash signatures."""
    if not a or not b or len(a) != len(b):
        return 0.0
    shared = sum(1 for x, y in zip(a, b) if x == y)
    return shared / len(a)


def hamming_hex(a: str | int, b: str | int) -> int:
    """Legacy: hamming distance between two hex/bin hashes."""
    return (_as_int(a) ^ _as_int(b)).bit_count()