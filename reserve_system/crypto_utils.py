"""Cryptographic utilities: serial generation, checksums, and RSA-SHA256 signing.

RSA operations are performed via the system `openssl` CLI so there is no
dependency on the `cryptography` Python package (which may have broken C
extensions on some platforms).  Pure-Python operations use only the stdlib.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import tempfile
from typing import Optional


# ---------------------------------------------------------------------------
# Serial number generation
# ---------------------------------------------------------------------------

def generate_serial(seed: Optional[str] = None, counter: int = 0) -> str:
    """Return a 128-bit collision-resistant hex serial.

    Seeded: HMAC-SHA256(seed, counter) — deterministic, reproducible.
    Unseeded: secrets.token_hex — cryptographically secure.
    """
    if seed is not None:
        key = seed.encode("utf-8")
        msg = f"serial:{counter}".encode("utf-8")
        return hmac.new(key, msg, hashlib.sha256).hexdigest()[:32]
    return secrets.token_hex(16)


# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------

def canonical_bytes(bill_data: dict) -> bytes:
    """Stable JSON serialisation excluding 'checksum' and 'signature' fields."""
    filtered = {k: v for k, v in bill_data.items() if k not in ("checksum", "signature")}
    return json.dumps(filtered, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_checksum(bill_data: dict) -> str:
    """SHA-256 hex digest of the canonical bill content."""
    return hashlib.sha256(canonical_bytes(bill_data)).hexdigest()


def verify_checksum(bill_data: dict) -> bool:
    """Return True if the stored checksum matches recomputation."""
    stored = bill_data.get("checksum", "")
    if not stored:
        return False
    return secrets.compare_digest(stored, compute_checksum(bill_data))


# ---------------------------------------------------------------------------
# RSA signing via openssl CLI
# ---------------------------------------------------------------------------

def _run(cmd: list, input_data: bytes = b"", check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        check=check,
    )


def generate_key_pair(key_dir: str) -> tuple:
    """Generate an RSA-2048 key pair using openssl; return (priv_path, pub_path)."""
    os.makedirs(key_dir, exist_ok=True)
    priv_path = os.path.join(key_dir, "private.pem")
    pub_path = os.path.join(key_dir, "public.pem")

    _run(["openssl", "genrsa", "-out", priv_path, "2048"])
    os.chmod(priv_path, 0o600)
    _run(["openssl", "rsa", "-pubout", "-in", priv_path, "-out", pub_path])
    return priv_path, pub_path


def load_private_key(pem_path: str) -> str:
    """Return the private key PEM path (kept as a path reference)."""
    if not os.path.exists(pem_path):
        raise FileNotFoundError(pem_path)
    return pem_path


def load_public_key(pem_path: str) -> str:
    """Return the public key PEM path (kept as a path reference)."""
    if not os.path.exists(pem_path):
        raise FileNotFoundError(pem_path)
    return pem_path


def sign_checksum(checksum: str, private_key_path: str) -> str:
    """RSA-SHA256 sign the checksum string; return base64-encoded DER signature."""
    result = _run(
        ["openssl", "dgst", "-sha256", "-sign", private_key_path],
        input_data=checksum.encode("utf-8"),
    )
    return base64.b64encode(result.stdout).decode("ascii")


def verify_signature(checksum: str, signature_b64: str, public_key_path: str) -> bool:
    """Return True if the RSA-SHA256 signature over the checksum is valid."""
    try:
        sig_bytes = base64.b64decode(signature_b64)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".sig") as tf:
            tf.write(sig_bytes)
            sig_path = tf.name
        try:
            result = _run(
                ["openssl", "dgst", "-sha256", "-verify", public_key_path,
                 "-signature", sig_path],
                input_data=checksum.encode("utf-8"),
                check=False,
            )
            return result.returncode == 0
        finally:
            os.unlink(sig_path)
    except Exception:
        return False
