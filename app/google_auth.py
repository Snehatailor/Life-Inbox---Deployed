"""Sign in with Google (OAuth 2.0 authorization code flow).

Turned on only when GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set.
Google proves the user owns the email address; the app then finds or
creates the account with that email and starts a normal session.
"""

from __future__ import annotations

import os
import secrets
from typing import Optional
from urllib.parse import urlencode

import requests

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
STATE_COOKIE = "life_inbox_oauth_state"
STATE_TTL_SECONDS = 10 * 60
CALLBACK_PATH = "/api/auth/google/callback"
HTTP_TIMEOUT_SECONDS = 10


class GoogleLoginError(Exception):
    """Sign-in could not be completed. The message is safe to show users."""


def google_client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def google_client_secret() -> str:
    return os.getenv("GOOGLE_CLIENT_SECRET", "").strip()


def google_login_enabled() -> bool:
    return bool(google_client_id() and google_client_secret())


def redirect_uri(base_url: str) -> str:
    """GOOGLE_REDIRECT_URI wins; otherwise derive it from the request URL."""
    explicit = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    return base_url.rstrip("/") + CALLBACK_PATH


def new_state() -> str:
    return secrets.token_urlsafe(32)


def authorization_url(*, state: str, callback_url: str) -> str:
    params = {
        "client_id": google_client_id(),
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
        "access_type": "online",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def fetch_google_profile(*, code: str, callback_url: str) -> dict:
    """Swap the one-time code for a token and return the verified profile."""
    try:
        token_response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": google_client_id(),
                "client_secret": google_client_secret(),
                "redirect_uri": callback_url,
                "grant_type": "authorization_code",
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise GoogleLoginError("Could not reach Google. Try again.") from exc
    if token_response.status_code != 200:
        raise GoogleLoginError("Google sign-in was not completed. Try again.")
    access_token = (token_response.json() or {}).get("access_token")
    if not access_token:
        raise GoogleLoginError("Google sign-in was not completed. Try again.")

    try:
        profile_response = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise GoogleLoginError("Could not reach Google. Try again.") from exc
    if profile_response.status_code != 200:
        raise GoogleLoginError("Could not read your Google profile.")
    profile = profile_response.json() or {}

    email = str(profile.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise GoogleLoginError("Your Google account did not share an email address.")
    if profile.get("email_verified") is not True:
        raise GoogleLoginError("Your Google email address is not verified.")
    return {
        "email": email,
        "name": str(profile.get("name") or "").strip()[:100],
    }


def find_or_create_google_user(profile: dict) -> dict:
    from app.database import ensure_user

    email = profile["email"]
    if email == "local@life-inbox.local":
        raise GoogleLoginError("That email is reserved.")
    return ensure_user(
        email=email,
        display_name=profile.get("name") or email.split("@", 1)[0],
        auth_provider="google",
    )


def states_match(expected: Optional[str], received: Optional[str]) -> bool:
    if not expected or not received:
        return False
    return secrets.compare_digest(expected, received)
