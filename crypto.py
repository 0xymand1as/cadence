"""
Cadence — Fernet wrapper for OAuth token encryption at rest.

Key sourcing:
  - CADENCE_FERNET_KEY env var (production)
  - Derived deterministically from FLASK_SECRET if CADENCE_FERNET_KEY missing
    (acceptable during private beta; rotate before prod-scale)
"""
from __future__ import annotations

import os
import base64
import hashlib
from cryptography.fernet import Fernet


def _get_key() -> bytes:
    explicit = os.environ.get("CADENCE_FERNET_KEY")
    if explicit:
        return explicit.encode()
    seed = os.environ.get("FLASK_SECRET", "")
    if not seed:
        raise RuntimeError("Cannot derive Fernet key: set FLASK_SECRET or CADENCE_FERNET_KEY")
    digest = hashlib.sha256(seed.encode()).digest()
    return base64.urlsafe_b64encode(digest)


_F = Fernet(_get_key())


def encrypt(plaintext: str) -> str:
    return _F.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _F.decrypt(ciphertext.encode()).decode()
