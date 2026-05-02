"""Binary Merkle tree for tamper-proof bill integrity chains."""

import hashlib
from typing import List


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _hash_pair(left: str, right: str) -> str:
    return _sha256(left + right)


def compute_merkle_root(leaves: List[str]) -> str:
    """Return the Merkle root of a list of hex-digest leaf hashes.

    An empty list returns the SHA-256 of an empty string.
    Odd-length levels duplicate the last node (standard Bitcoin convention).
    """
    if not leaves:
        return hashlib.sha256(b"").hexdigest()

    level = list(leaves)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_hash_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def get_merkle_proof(leaves: List[str], index: int) -> List[dict]:
    """Return an inclusion proof for the leaf at *index*.

    Each step is {"hash": <sibling_hex>, "position": "left"|"right"}.
    """
    if not leaves or index >= len(leaves):
        return []

    level = list(leaves)
    proof = []
    pos = index

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        if pos % 2 == 0:
            sibling = level[pos + 1]
            proof.append({"hash": sibling, "position": "right"})
        else:
            sibling = level[pos - 1]
            proof.append({"hash": sibling, "position": "left"})
        level = [_hash_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        pos //= 2

    return proof


def verify_merkle_proof(leaf: str, proof: List[dict], root: str) -> bool:
    """Return True if *proof* correctly links *leaf* to *root*."""
    current = leaf
    for step in proof:
        sibling = step["hash"]
        if step["position"] == "right":
            current = _hash_pair(current, sibling)
        else:
            current = _hash_pair(sibling, current)
    return current == root
