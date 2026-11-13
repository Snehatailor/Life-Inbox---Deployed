"""Encrypt per-user secrets (AI API keys, OAuth tokens) before storing them.

Uses Fernet (AES-128-CBC + HMAC-SHA256). The key comes from
LIFE_INBOX_ENCRYPTION_KEY when set, otherwise it is derived from the session
secret. Changing either makes stored secrets unreadable; users then re-enter
their key or reconnect their calendar.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    from app.config import load_config

    material = os.getenv("LIFE_INBOX_ENCRYPTION_KEY", "").strip()
    if not material:
        material = "life-inbox-secrets:" + load_config(strict=False).session_secret
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: Optional[str]) -> Optional[str]:
    """Return the plaintext, or None when missing or unreadable."""
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def key_hint(value: Optional[str]) -> Optional[str]:
    """A safe-to-show hint such as "…a1b2"."""
    if not value:
        return None
    return "…" + value[-4:] if len(value) >= 8 else "…"
