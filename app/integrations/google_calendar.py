"""Connect a user's Google Calendar and add confirmed tasks to it.

- Uses the same Google OAuth client as "Sign in with Google"
  (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET) with the narrow
  calendar.events scope: add and edit events only.
- Tokens are stored encrypted per user and never sent to the browser.
- Nothing is written until the user previews an event and presses confirm.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote, urlencode

import requests

from app.integrations.calendar import (
    CalendarAdapter,
    CalendarAdapterStatus,
    CalendarEventDraft,
)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar}/events"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
SCOPES = f"openid email {CALENDAR_SCOPE}"
CALLBACK_PATH = "/api/integrations/google-calendar/callback"
STATE_COOKIE = "life_inbox_calendar_state"
STATE_COOKIE_PATH = "/api/integrations/google-calendar"
HTTP_TIMEOUT_SECONDS = 15


class CalendarConnectionError(Exception):
    """Calendar connect/push failed. The message is safe to show users."""


def client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def client_secret() -> str:
    return os.getenv("GOOGLE_CLIENT_SECRET", "").strip()


def google_calendar_available() -> bool:
    return bool(client_id() and client_secret())


def redirect_uri(base_url: str) -> str:
    explicit = os.getenv("GOOGLE_CALENDAR_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    return base_url.rstrip("/") + CALLBACK_PATH


def authorization_url(*, state: str, callback_url: str, login_hint: str = "") -> str:
    params = {
        "client_id": client_id(),
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    if login_hint and "@" in login_hint:
        params["login_hint"] = login_hint
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


# ---------- token storage ----------

def _load_tokens(owner_user_id: int) -> Optional[dict]:
    from app.database import get_user_settings
    from app.secret_box import decrypt_secret

    raw = decrypt_secret(get_user_settings(owner_user_id).get("google_calendar_token_enc"))
    if not raw:
        return None
    try:
        tokens = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return tokens if tokens.get("refresh_token") or tokens.get("access_token") else None


def _save_tokens(owner_user_id: int, tokens: dict, email: Optional[str] = None) -> None:
    from app.database import update_user_settings
    from app.secret_box import encrypt_secret

    changes = {"google_calendar_token_enc": encrypt_secret(json.dumps(tokens))}
    if email is not None:
        changes["google_calendar_email"] = email
    update_user_settings(owner_user_id, **changes)


def connection_status(owner_user_id: int) -> dict:
    from app.database import get_user_settings

    connected = _load_tokens(owner_user_id) is not None
    return {
        "available": google_calendar_available(),
        "connected": connected,
        "email": get_user_settings(owner_user_id).get("google_calendar_email") if connected else None,
    }


def is_connected(owner_user_id: Optional[int]) -> bool:
    return owner_user_id is not None and _load_tokens(owner_user_id) is not None


# ---------- OAuth exchange ----------

def connect_with_code(owner_user_id: int, *, code: str, callback_url: str) -> str:
    """Swap the one-time code for tokens, store them, return the Google email."""
    try:
        token_response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id(),
                "client_secret": client_secret(),
                "redirect_uri": callback_url,
                "grant_type": "authorization_code",
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise CalendarConnectionError("Could not reach Google. Try again.") from exc
    if token_response.status_code != 200:
        raise CalendarConnectionError("Google did not finish connecting your calendar.")
    payload = token_response.json() or {}
    access_token = payload.get("access_token")
    granted = set(str(payload.get("scope", "")).split())
    if not access_token:
        raise CalendarConnectionError("Google did not finish connecting your calendar.")
    if CALENDAR_SCOPE not in granted:
        raise CalendarConnectionError(
            "Calendar access was not granted. Tick the calendar box on Google's screen."
        )

    email = None
    try:
        info = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        if info.status_code == 200:
            email = str((info.json() or {}).get("email") or "").strip().lower() or None
    except requests.RequestException:
        email = None

    previous = _load_tokens(owner_user_id) or {}
    tokens = {
        "access_token": access_token,
        # Google only sends a refresh token on first consent; keep the old one.
        "refresh_token": payload.get("refresh_token") or previous.get("refresh_token"),
        "expires_at": int(time.time()) + int(payload.get("expires_in", 3600)),
        "scope": " ".join(sorted(granted)),
    }
    _save_tokens(owner_user_id, tokens, email=email or "")
    return email or ""


def disconnect(owner_user_id: int) -> None:
    """Forget the tokens and ask Google to revoke them (best effort)."""
    from app.database import update_user_settings

    tokens = _load_tokens(owner_user_id) or {}
    token = tokens.get("refresh_token") or tokens.get("access_token")
    if token:
        try:
            requests.post(
                GOOGLE_REVOKE_URL,
                data={"token": token},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            pass
    update_user_settings(
        owner_user_id, google_calendar_token_enc=None, google_calendar_email=None
    )


def _access_token(owner_user_id: int) -> str:
    tokens = _load_tokens(owner_user_id)
    if not tokens:
        raise CalendarConnectionError("Google Calendar is not connected.")
    if tokens.get("access_token") and int(tokens.get("expires_at", 0)) > time.time() + 60:
        return tokens["access_token"]
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise CalendarConnectionError("Calendar access expired. Reconnect Google Calendar in Settings.")
    try:
        response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id(),
                "client_secret": client_secret(),
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise CalendarConnectionError("Could not reach Google. Try again.") from exc
    if response.status_code != 200:
        raise CalendarConnectionError(
            "Google Calendar access was revoked or expired. Reconnect it in Settings."
        )
    payload = response.json() or {}
    tokens["access_token"] = payload.get("access_token")
    tokens["expires_at"] = int(time.time()) + int(payload.get("expires_in", 3600))
    if not tokens["access_token"]:
        raise CalendarConnectionError("Google Calendar access expired. Reconnect it in Settings.")
    _save_tokens(owner_user_id, tokens)
    return tokens["access_token"]


def create_all_day_event(
    owner_user_id: int,
    *,
    title: str,
    start_date: str,
    description: str,
    calendar: str = "primary",
) -> dict:
    start = date.fromisoformat(start_date)
    body = {
        "summary": title[:500],
        "description": description[:4000],
        "start": {"date": start.isoformat()},
        "end": {"date": (start + timedelta(days=1)).isoformat()},
    }
    try:
        response = requests.post(
            CALENDAR_EVENTS_URL.format(calendar=quote(calendar, safe="")),
            headers={"Authorization": f"Bearer {_access_token(owner_user_id)}"},
            json=body,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise CalendarConnectionError("Could not reach Google Calendar. Try again.") from exc
    if response.status_code in {401, 403}:
        raise CalendarConnectionError(
            "Google Calendar refused the event. Reconnect it in Settings."
        )
    if response.status_code not in {200, 201}:
        raise CalendarConnectionError("Google Calendar could not create the event.")
    created = response.json() or {}
    return {"event_id": created.get("id"), "html_link": created.get("htmlLink")}


class GoogleCalendarLiveAdapter(CalendarAdapter):
    """Adds events to the signed-in user's own Google Calendar after confirm."""

    def __init__(self, owner_user_id: int) -> None:
        self.owner_user_id = owner_user_id

    def status(self) -> CalendarAdapterStatus:
        info = connection_status(self.owner_user_id)
        return CalendarAdapterStatus(
            provider="google",
            configured=True,
            oauth_connected=True,
            writes_enabled=True,
            mode="live",
            message=f"Connected to Google Calendar ({info['email'] or 'your account'}). "
            "Events are added only after you confirm.",
        )

    def preview_event(
        self,
        *,
        task_id: int,
        title: str,
        start_date: date,
        description: str = "",
        timezone_name: str = "UTC",
    ) -> CalendarEventDraft:
        email = connection_status(self.owner_user_id)["email"]
        return CalendarEventDraft(
            draft_id=f"gcal-{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            title=title,
            start_date=start_date.isoformat(),
            end_date=start_date.isoformat(),
            description=description,
            timezone_name=timezone_name,
            provider="google",
            status="preview",
            confirmation_required=True,
            notes=[
                f"Will be added as an all-day event to {email or 'your Google Calendar'}.",
                "Nothing is added until you confirm.",
            ],
        )

    def confirm_event(self, draft: CalendarEventDraft) -> CalendarEventDraft:
        created = create_all_day_event(
            self.owner_user_id,
            title=draft.title,
            start_date=draft.start_date,
            description=draft.description or "Added from Life Inbox.",
        )
        notes = [
            "Added to Google Calendar.",
            f"Recorded at {datetime.now(timezone.utc).isoformat()}",
        ]
        return CalendarEventDraft(
            draft_id=draft.draft_id,
            task_id=draft.task_id,
            title=draft.title,
            start_date=draft.start_date,
            end_date=draft.end_date,
            description=draft.description,
            timezone_name=draft.timezone_name,
            provider="google",
            status="created",
            confirmation_required=False,
            notes=notes,
            external_event_id=created.get("event_id"),
            external_link=created.get("html_link"),
        )
