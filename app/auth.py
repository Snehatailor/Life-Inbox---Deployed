"""Session-based auth. Never trusts browser-supplied user IDs."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from typing import Optional

from fastapi import Cookie, HTTPException, Request, Response

from app.config import load_config
from app.database import ensure_user, get_user_by_email, get_user_by_id


SESSION_COOKIE = "life_inbox_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14


def _signer_key() -> bytes:
    config = load_config(strict=False)
    return hashlib.sha256(config.session_secret.encode("utf-8")).digest()


def create_session_token(user_id: int) -> str:
    payload = {
        "uid": int(user_id),
        "iat": int(time.time()),
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(_signer_key(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def parse_session_token(token: str) -> Optional[int]:
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(
        _signer_key(), body.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return int(payload["uid"])


def set_session_cookie(response: Response, user_id: int) -> None:
    secure = os.getenv("LIFE_INBOX_ENV", "local") in {"beta", "production"}
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(user_id),
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_current_user(
    request: Request,
    life_inbox_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict:
    # Never accept X-User-Id / query user_id as identity.
    if "x-user-id" in {k.lower() for k in request.headers.keys()}:
        # Ignore spoof header completely.
        pass

    token = life_inbox_session
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    user_id = parse_session_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown session user.")
    return user


def optional_current_user(
    request: Request,
    life_inbox_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
) -> Optional[dict]:
    try:
        return get_current_user(request, life_inbox_session)
    except HTTPException:
        return None


# --- Email + password accounts -------------------------------------------

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 200
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

# Failed sign-in throttling (per process, in memory).
LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_SECONDS = 15 * 60
_login_failures: dict[str, list[float]] = {}
_login_failures_lock = threading.Lock()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Verified against when the email is unknown, so timing does not reveal
# which emails have accounts.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def _clean_email(email: str) -> str:
    cleaned = (email or "").strip().lower()
    if (
        "@" not in cleaned
        or len(cleaned) < 5
        or len(cleaned) > 200
        or cleaned.startswith("@")
        or cleaned.endswith("@")
    ):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return cleaned


def _validate_new_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {PASSWORD_MIN_LENGTH} characters.",
        )
    if len(password) > PASSWORD_MAX_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at most {PASSWORD_MAX_LENGTH} characters.",
        )


def _recent_failures(key: str, now: float) -> list[float]:
    recent = [t for t in _login_failures.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    if recent:
        _login_failures[key] = recent
    else:
        _login_failures.pop(key, None)
    return recent


def reset_login_throttle_for_tests() -> None:
    with _login_failures_lock:
        _login_failures.clear()


def register_password_user(
    email: str,
    password: str,
    display_name: Optional[str] = None,
) -> dict:
    from app.database import UserAlreadyExistsError, create_password_user

    cleaned = _clean_email(email)
    _validate_new_password(password)
    if cleaned == "local@life-inbox.local":
        raise HTTPException(status_code=400, detail="That email is reserved.")
    try:
        return create_password_user(
            email=cleaned,
            display_name=(display_name or "").strip()[:100],
            password_hash=hash_password(password),
        )
    except UserAlreadyExistsError:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Sign in instead.",
        )


def password_login_user(email: str, password: str) -> dict:
    from app.database import get_password_login

    cleaned = _clean_email(email)
    now = time.time()
    with _login_failures_lock:
        if len(_recent_failures(cleaned, now)) >= LOGIN_MAX_FAILURES:
            raise HTTPException(
                status_code=429,
                detail="Too many failed sign-in attempts. Try again in 15 minutes.",
            )

    found = get_password_login(cleaned)
    stored_hash = found[1] if found else None
    ok = verify_password(password or "", stored_hash or _DUMMY_HASH)
    if not found or not stored_hash or not ok:
        with _login_failures_lock:
            _login_failures.setdefault(cleaned, []).append(now)
        raise HTTPException(status_code=401, detail="Wrong email or password.")

    with _login_failures_lock:
        _login_failures.pop(cleaned, None)
    return found[0]


def dev_login_user(email: str, display_name: Optional[str] = None) -> dict:
    config = load_config(strict=False)
    if not config.allow_dev_login:
        raise HTTPException(status_code=403, detail="Dev login is disabled.")
    cleaned = email.strip().lower()
    if "@" not in cleaned or len(cleaned) < 5:
        raise HTTPException(status_code=400, detail="Valid email required.")
    existing = get_user_by_email(cleaned)
    if existing:
        return existing
    return ensure_user(
        email=cleaned,
        display_name=display_name or cleaned.split("@", 1)[0],
        auth_provider="dev",
    )
