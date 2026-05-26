"""
Cadence — Fernet wrapper for OAuth token encryption at rest.

Key sourcing (in order):
  1. CADENCE_FERNET_KEY env var (production; recommended)
  2. Derived deterministically from FLASK_SECRET (acceptable beta)
  3. Persistent key generated + saved to ./.cadence_fernet_key (fallback so
     boot never crashes; rotate before prod scale)
"""
from __future__ import annotations

import os
import base64
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet


_KEY_FILE = Path(os.environ.get("CADENCE_KEY_PATH", ".cadence_fernet_key"))


def _get_key() -> bytes:
    explicit = os.environ.get("CADENCE_FERNET_KEY")
    if explicit:
        return explicit.encode()

    seed = os.environ.get("FLASK_SECRET", "")
    if seed:
        digest = hashlib.sha256(seed.encode()).digest()
        return base64.urlsafe_b64encode(digest)

    # Fallback — persist a generated key so boot never crashes.
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    generated = Fernet.generate_key()
    try:
        _KEY_FILE.write_bytes(generated)
    except OSError:
        pass  # ephemeral fs; key won't persist but app will run
    return generated


_F = Fernet(_get_key())


def encrypt(plaintext: str) -> str:
    return _F.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _F.decrypt(ciphertext.encode()).decode()
