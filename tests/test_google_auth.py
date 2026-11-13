"""Sign in with Google. Google's endpoints are mocked; no network calls."""

import importlib
import sys
from contextlib import ExitStack
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient


_RELOADED_MODULES = (
    "app.main",
    "app.database",
    "app.auth",
    "app.config",
    "app.google_auth",
    "app.integrations.calendar",
    "app.retrieval.ask",
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture()
def google_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'google.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LIFE_INBOX_ENV", "beta")
    monkeypatch.setenv("LIFE_INBOX_ALLOW_DEV_LOGIN", "0")
    monkeypatch.setenv("LIFE_INBOX_SESSION_SECRET", "y" * 40)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for name in _RELOADED_MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    google_auth = importlib.import_module("app.google_auth")

    calls = SimpleNamespace(token=[], userinfo=[])
    profile = {
        "email": "Gina@Example.com",
        "email_verified": True,
        "name": "Gina G",
    }
    state = SimpleNamespace(profile=profile, token_status=200)

    def fake_post(url, data=None, timeout=None):
        calls.token.append({"url": url, "data": data})
        if state.token_status != 200:
            return _FakeResponse(state.token_status, {"error": "invalid_grant"})
        return _FakeResponse(200, {"access_token": "fake-access-token"})

    def fake_get(url, headers=None, timeout=None):
        calls.userinfo.append({"url": url, "headers": headers})
        return _FakeResponse(200, state.profile)

    monkeypatch.setattr(google_auth.requests, "post", fake_post)
    monkeypatch.setattr(google_auth.requests, "get", fake_get)

    with ExitStack() as stack:

        def make_client() -> TestClient:
            return stack.enter_context(
                TestClient(
                    main.app,
                    base_url="https://testserver",
                    follow_redirects=False,
                )
            )

        yield SimpleNamespace(
            main=main,
            db=database,
            google_auth=google_auth,
            make_client=make_client,
            calls=calls,
            state=state,
        )
    database.engine.dispose()
    for name in _RELOADED_MODULES:
        sys.modules.pop(name, None)


def _start(client):
    response = client.get("/api/auth/google/start")
    assert response.status_code == 302
    location = urlparse(response.headers["location"])
    params = parse_qs(location.query)
    return response, location, params


def test_start_redirects_to_google_with_state(google_env):
    client = google_env.make_client()
    response, location, params = _start(client)
    assert location.netloc == "accounts.google.com"
    assert params["client_id"] == ["test-client-id.apps.googleusercontent.com"]
    assert params["redirect_uri"] == ["https://testserver/api/auth/google/callback"]
    assert params["scope"] == ["openid email profile"]
    assert params["response_type"] == ["code"]
    assert len(params["state"][0]) >= 32
    assert "test-client-secret" not in response.headers["location"]
    assert google_env.google_auth.STATE_COOKIE in response.headers["set-cookie"]


def test_explicit_redirect_uri_is_used(google_env, monkeypatch):
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://inbox.example.com/api/auth/google/callback")
    _, _, params = _start(google_env.make_client())
    assert params["redirect_uri"] == ["https://inbox.example.com/api/auth/google/callback"]


def test_full_sign_in_creates_account_and_session(google_env):
    client = google_env.make_client()
    _, _, params = _start(client)
    callback = client.get(
        "/api/auth/google/callback",
        params={"code": "one-time-code", "state": params["state"][0]},
    )
    assert callback.status_code == 302
    assert callback.headers["location"] == "/"

    token_call = google_env.calls.token[0]
    assert token_call["data"]["code"] == "one-time-code"
    assert token_call["data"]["client_secret"] == "test-client-secret"
    assert token_call["data"]["redirect_uri"] == "https://testserver/api/auth/google/callback"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "gina@example.com"
    assert me.json()["display_name"] == "Gina G"
    assert me.json()["auth_provider"] == "google"

    created = client.post("/api/items", json={"raw_text": "GINA_NOTE"})
    assert created.status_code == 200


def test_signing_in_twice_reuses_the_same_account(google_env):
    ids = []
    for _ in range(2):
        client = google_env.make_client()
        _, _, params = _start(client)
        client.get(
            "/api/auth/google/callback",
            params={"code": "c", "state": params["state"][0]},
        )
        ids.append(client.get("/api/auth/me").json()["id"])
    assert ids[0] == ids[1]


def test_google_signs_into_existing_password_account_with_same_email(google_env):
    client = google_env.make_client()
    registered = client.post(
        "/api/auth/register",
        json={"email": "gina@example.com", "password": "a long password"},
    ).json()
    client.post("/api/auth/logout")

    other = google_env.make_client()
    _, _, params = _start(other)
    other.get(
        "/api/auth/google/callback",
        params={"code": "c", "state": params["state"][0]},
    )
    assert other.get("/api/auth/me").json()["id"] == registered["id"]


def test_wrong_or_missing_state_is_rejected(google_env):
    client = google_env.make_client()
    _start(client)
    response = client.get(
        "/api/auth/google/callback",
        params={"code": "c", "state": "attacker-chosen-state"},
    )
    assert response.status_code == 302
    assert "auth_error=" in response.headers["location"]
    assert client.get("/api/auth/me").status_code == 401
    assert google_env.calls.token == []

    fresh = google_env.make_client()
    response = fresh.get("/api/auth/google/callback", params={"code": "c", "state": "x"})
    assert "auth_error=" in response.headers["location"]
    assert google_env.calls.token == []


def test_unverified_email_is_rejected(google_env):
    google_env.state.profile = {
        "email": "unverified@example.com",
        "email_verified": False,
        "name": "U",
    }
    client = google_env.make_client()
    _, _, params = _start(client)
    response = client.get(
        "/api/auth/google/callback",
        params={"code": "c", "state": params["state"][0]},
    )
    assert "auth_error=" in response.headers["location"]
    assert client.get("/api/auth/me").status_code == 401
    assert google_env.db.get_user_by_email("unverified@example.com") is None


def test_cancelled_or_failed_exchange_shows_error(google_env):
    client = google_env.make_client()
    _, _, params = _start(client)
    cancelled = client.get(
        "/api/auth/google/callback",
        params={"error": "access_denied", "state": params["state"][0]},
    )
    assert "auth_error=" in cancelled.headers["location"]

    google_env.state.token_status = 400
    client = google_env.make_client()
    _, _, params = _start(client)
    failed = client.get(
        "/api/auth/google/callback",
        params={"code": "bad", "state": params["state"][0]},
    )
    assert "auth_error=" in failed.headers["location"]
    assert client.get("/api/auth/me").status_code == 401


def test_auth_config_reports_google(google_env):
    assert google_env.make_client().get("/api/auth/config").json()["google_login"] is True


def test_google_is_off_without_credentials(google_env, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET")
    client = google_env.make_client()
    assert client.get("/api/auth/config").json()["google_login"] is False
    assert client.get("/api/auth/google/start").status_code == 501
