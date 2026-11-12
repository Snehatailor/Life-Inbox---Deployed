"""Settings: bring-your-own AI provider, and Google Calendar connect + push.

Claude, OpenAI-compatible providers and Google are all mocked: no network.
"""

import importlib
import json
import re
import sys
import time
from contextlib import ExitStack
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


_RELOADED_MODULES = (
    "app.main",
    "app.database",
    "app.auth",
    "app.config",
    "app.google_auth",
    "app.ai_provider",
    "app.secret_box",
    "app.organizer",
    "app.integrations.calendar",
    "app.integrations.google_calendar",
    "app.retrieval.ask",
)

PASSWORD = "a long test password"
CLAUDE_KEY = "sk-ant-test-0000000000-SECRET-abcd"
GEMINI_KEY = "AIza-test-key-SECRET-wxyz"


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _make_env(tmp_path, monkeypatch, environment="beta", google=True):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'settings.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LIFE_INBOX_ENV", environment)
    monkeypatch.setenv("LIFE_INBOX_ALLOW_DEV_LOGIN", "0")
    monkeypatch.setenv("LIFE_INBOX_SESSION_SECRET", "z" * 40)
    monkeypatch.setenv("LIFE_INBOX_CALENDAR_PROVIDER", "mock")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_REDIRECT_URI", raising=False)
    if google:
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "cal-client.apps.googleusercontent.com")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "cal-client-secret")
    else:
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    for name in _RELOADED_MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    calendar = importlib.import_module("app.integrations.calendar")
    calendar.reset_calendar_adapter_for_tests()
    return main


@pytest.fixture()
def env(tmp_path, monkeypatch):
    main = _make_env(tmp_path, monkeypatch)
    database = importlib.import_module("app.database")

    # Offline DNS: test hosts under example.com resolve to a public address.
    import app.capture.url_fetch as url_fetch

    real_getaddrinfo = url_fetch.socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        if str(host).endswith("example.com"):
            return [(2, 1, 6, "", ("93.184.216.34", 0))]
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(url_fetch.socket, "getaddrinfo", fake_getaddrinfo)
    with ExitStack() as stack:

        def make_client():
            return stack.enter_context(
                TestClient(main.app, base_url="https://testserver", follow_redirects=False)
            )

        yield SimpleNamespace(
            main=main,
            db=database,
            ai=importlib.import_module("app.ai_provider"),
            gcal=importlib.import_module("app.integrations.google_calendar"),
            make_client=make_client,
            db_path=tmp_path / "settings.db",
            monkeypatch=monkeypatch,
        )
    database.engine.dispose()
    for name in _RELOADED_MODULES:
        sys.modules.pop(name, None)


def _signed_in(env, email):
    client = env.make_client()
    response = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


# ---------- fake AI clients ----------

class FakeAnthropic:
    calls = []
    reply = "ready"
    stop_reason = "end_turn"

    def __init__(self, **kwargs):
        FakeAnthropic.calls.append({"init": kwargs})
        self.messages = SimpleNamespace(create=self._create(beta=False))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create(beta=True)))

    def _create(self, beta):
        def create(**kwargs):
            FakeAnthropic.calls.append({"beta": beta, **kwargs})
            prompt = kwargs["messages"][0]["content"]
            reply = FakeAnthropic.reply(prompt) if callable(FakeAnthropic.reply) else FakeAnthropic.reply
            return SimpleNamespace(
                stop_reason=FakeAnthropic.stop_reason,
                content=[SimpleNamespace(type="text", text=reply)],
            )

        return create


class FakeOpenAI:
    calls = []
    reply = "ready"

    def __init__(self, **kwargs):
        FakeOpenAI.calls.append({"init": kwargs})

        def create(**create_kwargs):
            FakeOpenAI.calls.append(create_kwargs)
            prompt = create_kwargs["messages"][0]["content"]
            reply = FakeOpenAI.reply(prompt) if callable(FakeOpenAI.reply) else FakeOpenAI.reply
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
        self.responses = SimpleNamespace(
            create=lambda **_: (_ for _ in ()).throw(AssertionError("server path must not run"))
        )


@pytest.fixture()
def fake_ai(monkeypatch):
    import anthropic
    import openai

    FakeAnthropic.calls, FakeOpenAI.calls = [], []
    FakeAnthropic.reply, FakeOpenAI.reply = "ready", "ready"
    FakeAnthropic.stop_reason = "end_turn"
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    return SimpleNamespace(anthropic=FakeAnthropic, openai=FakeOpenAI)


def _analysis_reply(prompt):
    ids = [int(x) for x in re.findall(r'"id":\s*(\d+)', prompt.split("Saved notes:")[-1])]
    return json.dumps({
        "buckets": [{"name": "Money & Admin", "notes": [
            {"id": i, "title": f"Note {i}", "priority": "High", "tags": ["money"], "rationale": "AI"}
            for i in ids
        ]}],
        "todos": [{"task": "Pay the bill", "priority": "High", "source_note_ids": ids[:1], "when": "tomorrow"}],
        "priority_view": {"High": [{"id": i, "title": f"Note {i}"} for i in ids], "Medium": [], "Low": []},
    })


# ---------- AI settings ----------

def test_saving_ai_settings_encrypts_key_and_only_shows_a_hint(env):
    client = _signed_in(env, "alice@example.com")
    saved = client.put(
        "/api/settings/ai",
        json={"provider": "anthropic", "api_key": CLAUDE_KEY},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-opus-5-5"
    assert body["base_url"] == "https://api.anthropic.com"
    assert body["has_key"] is True
    assert body["key_hint"] == "…abcd"
    assert body["active"]["source"] == "user"
    assert CLAUDE_KEY not in saved.text

    settings = client.get("/api/settings")
    assert settings.status_code == 200
    assert CLAUDE_KEY not in settings.text
    assert "SECRET" not in settings.text
    assert {p["id"] for p in settings.json()["presets"]} >= {
        "anthropic", "openai", "gemini", "openrouter", "groq", "ollama", "custom"
    }

    engine = create_engine(f"sqlite:///{env.db_path}")
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT ai_api_key_enc FROM user_settings")).scalar()
    engine.dispose()
    assert stored and CLAUDE_KEY not in stored and "SECRET" not in stored


def test_keeping_the_saved_key_when_only_model_changes(env):
    client = _signed_in(env, "alice@example.com")
    client.put("/api/settings/ai", json={"provider": "anthropic", "api_key": CLAUDE_KEY})
    changed = client.put(
        "/api/settings/ai", json={"provider": "anthropic", "model": "claude-sonnet-5-5"}
    )
    assert changed.status_code == 200
    assert changed.json()["model"] == "claude-sonnet-5-5"
    assert changed.json()["key_hint"] == "…abcd"


def test_ai_settings_validation(env):
    client = _signed_in(env, "alice@example.com")
    assert client.put("/api/settings/ai", json={"provider": "nope"}).status_code == 400
    missing_key = client.put("/api/settings/ai", json={"provider": "openai"})
    assert missing_key.status_code == 400
    assert "API key" in missing_key.json()["detail"]
    for bad_url in (
        "http://api.example.com/v1",
        "https://localhost:11434/v1",
        "https://127.0.0.1/v1",
        "https://10.0.0.5/v1",
        "https://user:pw@api.example.com/v1",
        "ftp://api.example.com",
    ):
        response = client.put(
            "/api/settings/ai",
            json={"provider": "custom", "base_url": bad_url, "model": "m", "api_key": "k"},
        )
        assert response.status_code == 400, bad_url
    assert client.put(
        "/api/settings/ai", json={"provider": "ollama"}
    ).status_code == 400  # localhost is blocked on the hosted site


def test_local_mode_allows_ollama_on_localhost(tmp_path, monkeypatch):
    main = _make_env(tmp_path, monkeypatch, environment="local")
    database = importlib.import_module("app.database")
    try:
        with TestClient(main.app) as client:
            response = client.put("/api/settings/ai", json={"provider": "ollama"})
            assert response.status_code == 200, response.text
            assert response.json()["base_url"] == "http://localhost:11434/v1"
            assert response.json()["active"]["label"].startswith("Ollama")
    finally:
        database.engine.dispose()
        for name in _RELOADED_MODULES:
            sys.modules.pop(name, None)


def test_settings_require_sign_in_and_are_private(env, fake_ai):
    anonymous = env.make_client()
    assert anonymous.get("/api/settings").status_code == 401
    assert anonymous.put("/api/settings/ai", json={"provider": "anthropic"}).status_code == 401

    alice = _signed_in(env, "alice@example.com")
    alice.put("/api/settings/ai", json={"provider": "anthropic", "api_key": CLAUDE_KEY})

    bob = _signed_in(env, "bob@example.com")
    bob_settings = bob.get("/api/settings").json()
    assert bob_settings["ai"]["provider"] is None
    assert bob_settings["ai"]["has_key"] is False
    assert bob_settings["ai"]["active"]["source"] == "none"

    # Bob's analysis must not use Alice's Claude key.
    bob.post("/api/items", json={"raw_text": "Pay the bill tomorrow"})
    analysis = bob.post("/api/analyze")
    assert analysis.status_code == 200
    assert analysis.json()["mode"] == "fallback_no_api_call"
    assert fake_ai.anthropic.calls == []


def test_analyze_uses_claude_with_server_side_fallbacks(env, fake_ai):
    fake_ai.anthropic.reply = _analysis_reply
    client = _signed_in(env, "alice@example.com")
    client.put("/api/settings/ai", json={"provider": "anthropic", "api_key": CLAUDE_KEY})
    client.post("/api/items", json={"raw_text": "Pay the electricity bill tomorrow"})

    analysis = client.post("/api/analyze")
    assert analysis.status_code == 200, analysis.text
    assert analysis.json()["mode"] == "ai_provider"

    init = fake_ai.anthropic.calls[0]["init"]
    assert init["api_key"] == CLAUDE_KEY
    request = next(call for call in fake_ai.anthropic.calls if "model" in call)
    assert request["beta"] is True
    assert request["model"] == "claude-opus-5-5"
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["max_tokens"] == 16000


def test_claude_model_without_fallback_support_uses_plain_messages(env, fake_ai):
    fake_ai.anthropic.reply = _analysis_reply
    client = _signed_in(env, "alice@example.com")
    client.put(
        "/api/settings/ai",
        json={"provider": "anthropic", "api_key": CLAUDE_KEY, "model": "claude-haiku-5-5"},
    )
    client.post("/api/items", json={"raw_text": "Buy groceries"})
    assert client.post("/api/analyze").json()["mode"] == "ai_provider"
    request = next(call for call in fake_ai.anthropic.calls if "model" in call)
    assert request["beta"] is False
    assert "fallbacks" not in request


def test_claude_refusal_falls_back_to_built_in_rules(env, fake_ai):
    fake_ai.anthropic.stop_reason = "refusal"
    client = _signed_in(env, "alice@example.com")
    client.put("/api/settings/ai", json={"provider": "anthropic", "api_key": CLAUDE_KEY})
    client.post("/api/items", json={"raw_text": "Pay the bill tomorrow"})
    analysis = client.post("/api/analyze")
    assert analysis.status_code == 200
    assert analysis.json()["mode"] == "fallback_after_api_error"


def test_analyze_uses_gemini_through_openai_compatible_api(env, fake_ai):
    fake_ai.openai.reply = _analysis_reply
    client = _signed_in(env, "alice@example.com")
    saved = client.put("/api/settings/ai", json={"provider": "gemini", "api_key": GEMINI_KEY})
    assert saved.status_code == 200, saved.text
    client.post("/api/items", json={"raw_text": "Renew insurance before Friday"})
    assert client.post("/api/analyze").json()["mode"] == "ai_provider"

    init = fake_ai.openai.calls[0]["init"]
    assert init["api_key"] == GEMINI_KEY
    assert init["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"
    request = fake_ai.openai.calls[1]
    assert request["model"] == "gemini-2.5-flash"
    assert request["messages"][0]["role"] == "user"


def test_ask_my_inbox_uses_the_users_provider(env, fake_ai):
    def answer(prompt):
        citation = re.search(r"item-\d+-\d+", prompt).group(0)
        return json.dumps({"answer": "Pay it tomorrow.", "confidence": "high", "citation_ids": [citation]})

    fake_ai.openai.reply = answer
    client = _signed_in(env, "alice@example.com")
    client.put(
        "/api/settings/ai",
        json={
            "provider": "custom",
            "base_url": "https://llm.example.com/v1",
            "model": "my-open-model",
            "api_key": "custom-key",
        },
    )
    client.post("/api/items", json={"raw_text": "Pay the electricity bill tomorrow"})
    response = client.post("/api/ask", json={"question": "When do I pay the electricity bill?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "llm_grounded"
    assert body["answer"] == "Pay it tomorrow."
    assert body["citations"]
    assert fake_ai.openai.calls[0]["init"]["base_url"] == "https://llm.example.com/v1"


def test_connection_test_endpoint(env, fake_ai):
    client = _signed_in(env, "alice@example.com")
    assert client.post("/api/settings/ai/test").status_code == 400  # nothing saved
    client.put("/api/settings/ai", json={"provider": "anthropic", "api_key": CLAUDE_KEY})
    ok = client.post("/api/settings/ai/test")
    assert ok.status_code == 200
    assert ok.json()["ok"] is True
    assert "Claude" in ok.json()["message"]

    def reject(prompt, config):
        raise env.ai.AIProviderError("Claude rejected the API key.")

    env.monkeypatch.setattr(env.ai, "_complete_anthropic", reject)
    failed = client.post("/api/settings/ai/test").json()
    assert failed == {"ok": False, "message": "Claude rejected the API key."}
    assert CLAUDE_KEY not in json.dumps(failed)


def test_removing_ai_settings(env):
    client = _signed_in(env, "alice@example.com")
    client.put("/api/settings/ai", json={"provider": "anthropic", "api_key": CLAUDE_KEY})
    removed = client.delete("/api/settings/ai")
    assert removed.status_code == 200
    assert removed.json()["provider"] is None
    assert removed.json()["has_key"] is False


# ---------- Google Calendar ----------

@pytest.fixture()
def fake_google(env):
    state = SimpleNamespace(
        posts=[],
        gets=[],
        token_scope="openid https://www.googleapis.com/auth/userinfo.email "
        "https://www.googleapis.com/auth/calendar.events",
        refresh_status=200,
        event_status=200,
    )

    def post(url, data=None, json=None, headers=None, timeout=None):
        state.posts.append({"url": url, "data": data, "json": json, "headers": headers})
        if url == env.gcal.GOOGLE_TOKEN_URL and data.get("grant_type") == "authorization_code":
            return _Resp(200, {
                "access_token": "access-1", "refresh_token": "refresh-1",
                "expires_in": 3600, "scope": state.token_scope,
            })
        if url == env.gcal.GOOGLE_TOKEN_URL and data.get("grant_type") == "refresh_token":
            return _Resp(state.refresh_status, {"access_token": "access-2", "expires_in": 3600})
        if url == env.gcal.GOOGLE_REVOKE_URL:
            return _Resp(200)
        if url.startswith("https://www.googleapis.com/calendar/v3/"):
            return _Resp(state.event_status, {"id": "evt-123", "htmlLink": "https://calendar.google.com/event?eid=abc"})
        raise AssertionError(f"unexpected POST {url}")

    def get(url, headers=None, timeout=None):
        state.gets.append({"url": url, "headers": headers})
        return _Resp(200, {"email": "Alice.G@gmail.com"})

    env.monkeypatch.setattr(env.gcal.requests, "post", post)
    env.monkeypatch.setattr(env.gcal.requests, "get", get)
    return state


def _connect_calendar(client):
    start = client.get("/api/integrations/google-calendar/connect")
    assert start.status_code == 302, start.text
    params = parse_qs(urlparse(start.headers["location"]).query)
    callback = client.get(
        "/api/integrations/google-calendar/callback",
        params={"code": "one-time", "state": params["state"][0]},
    )
    return start, params, callback


def _task_with_date(client):
    client.post("/api/items", json={"raw_text": "Pay the electricity bill tomorrow"})
    assert client.post("/api/analyze").status_code == 200
    tasks = client.get("/api/tasks").json()
    task = next(t for t in tasks if t.get("due_on"))
    return task


def test_connect_requests_calendar_scope_and_offline_access(env, fake_google):
    client = _signed_in(env, "alice@example.com")
    start, params, callback = _connect_calendar(client)
    location = urlparse(start.headers["location"])
    assert location.netloc == "accounts.google.com"
    assert "https://www.googleapis.com/auth/calendar.events" in params["scope"][0]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["redirect_uri"] == ["https://testserver/api/integrations/google-calendar/callback"]
    assert params["login_hint"] == ["alice@example.com"]
    assert "cal-client-secret" not in start.headers["location"]

    assert callback.status_code == 302
    assert callback.headers["location"].startswith("/?calendar=connected")

    status = client.get("/api/settings").json()["calendar"]
    assert status == {"available": True, "connected": True, "email": "alice.g@gmail.com"}
    settings_text = client.get("/api/settings").text
    assert "refresh-1" not in settings_text and "access-1" not in settings_text

    engine = create_engine(f"sqlite:///{env.db_path}")
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT google_calendar_token_enc FROM user_settings")).scalar()
    engine.dispose()
    assert stored and "refresh-1" not in stored


def test_calendar_unavailable_without_google_client(tmp_path, monkeypatch):
    main = _make_env(tmp_path, monkeypatch, google=False)
    database = importlib.import_module("app.database")
    try:
        with TestClient(main.app, base_url="https://testserver") as client:
            client.post("/api/auth/register", json={"email": "a@example.com", "password": PASSWORD})
            assert client.get("/api/settings").json()["calendar"]["available"] is False
            assert client.get("/api/integrations/google-calendar/connect").status_code == 501
    finally:
        database.engine.dispose()
        for name in _RELOADED_MODULES:
            sys.modules.pop(name, None)


def test_callback_rejects_wrong_state_other_user_and_missing_scope(env, fake_google):
    alice = _signed_in(env, "alice@example.com")
    start = alice.get("/api/integrations/google-calendar/connect")
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    wrong = alice.get(
        "/api/integrations/google-calendar/callback",
        params={"code": "c", "state": "attacker-state"},
    )
    assert "calendar=error" in wrong.headers["location"]

    # Bob cannot finish Alice's flow, even holding her state value.
    bob = _signed_in(env, "bob@example.com")
    bob.cookies.set(env.gcal.STATE_COOKIE, f"{state}.1", path=env.gcal.STATE_COOKIE_PATH)
    stolen = bob.get(
        "/api/integrations/google-calendar/callback", params={"code": "c", "state": state}
    )
    assert "calendar=error" in stolen.headers["location"]
    assert bob.get("/api/settings").json()["calendar"]["connected"] is False

    fake_google.token_scope = "openid email"
    _, _, no_scope = _connect_calendar(alice)
    assert "calendar=error" in no_scope.headers["location"]
    assert alice.get("/api/settings").json()["calendar"]["connected"] is False


def test_confirmed_task_is_added_to_google_calendar(env, fake_google):
    client = _signed_in(env, "alice@example.com")
    _connect_calendar(client)
    task = _task_with_date(client)

    preview = client.post("/api/calendar/preview", json={"task_id": task["id"]})
    assert preview.status_code == 200, preview.text
    draft = preview.json()
    assert draft["provider"] == "google"
    assert draft["confirmation_required"] is True
    assert not any(p["url"].startswith("https://www.googleapis.com/calendar") for p in fake_google.posts)

    confirmed = client.post("/api/calendar/confirm", json={"draft_id": draft["draft_id"]})
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "created"
    assert body["link"] == "https://calendar.google.com/event?eid=abc"

    event_call = next(p for p in fake_google.posts if p["url"].startswith("https://www.googleapis.com/calendar"))
    assert event_call["url"].endswith("/calendars/primary/events")
    assert event_call["headers"]["Authorization"] == "Bearer access-1"
    assert event_call["json"]["start"] == {"date": task["due_on"]}
    assert event_call["json"]["summary"] == draft["title"]


def test_expired_token_is_refreshed_before_pushing(env, fake_google):
    client = _signed_in(env, "alice@example.com")
    _connect_calendar(client)
    owner = client.get("/api/auth/me").json()["id"]
    tokens = env.gcal._load_tokens(owner)
    tokens["expires_at"] = int(time.time()) - 10
    env.gcal._save_tokens(owner, tokens)

    task = _task_with_date(client)
    draft = client.post("/api/calendar/preview", json={"task_id": task["id"]}).json()
    assert client.post("/api/calendar/confirm", json={"draft_id": draft["draft_id"]}).status_code == 200
    assert any(p["data"] and p["data"].get("grant_type") == "refresh_token" for p in fake_google.posts)
    event_call = next(p for p in fake_google.posts if p["url"].startswith("https://www.googleapis.com/calendar"))
    assert event_call["headers"]["Authorization"] == "Bearer access-2"


def test_revoked_access_returns_a_clear_error(env, fake_google):
    client = _signed_in(env, "alice@example.com")
    _connect_calendar(client)
    fake_google.event_status = 401
    task = _task_with_date(client)
    draft = client.post("/api/calendar/preview", json={"task_id": task["id"]}).json()
    failed = client.post("/api/calendar/confirm", json={"draft_id": draft["draft_id"]})
    assert failed.status_code == 502
    assert "Reconnect" in failed.json()["detail"]


def test_disconnect_revokes_and_falls_back_to_mock(env, fake_google):
    client = _signed_in(env, "alice@example.com")
    _connect_calendar(client)
    disconnected = client.post("/api/integrations/google-calendar/disconnect")
    assert disconnected.status_code == 200
    assert disconnected.json()["connected"] is False
    assert any(p["url"] == env.gcal.GOOGLE_REVOKE_URL and p["data"]["token"] == "refresh-1" for p in fake_google.posts)

    task = _task_with_date(client)
    draft = client.post("/api/calendar/preview", json={"task_id": task["id"]}).json()
    assert draft["provider"] == "mock"


def test_other_users_do_not_get_alices_calendar(env, fake_google):
    alice = _signed_in(env, "alice@example.com")
    _connect_calendar(alice)
    bob = _signed_in(env, "bob@example.com")
    assert bob.get("/api/settings").json()["calendar"]["connected"] is False
    task = _task_with_date(bob)
    draft = bob.post("/api/calendar/preview", json={"task_id": task["id"]}).json()
    assert draft["provider"] == "mock"
    confirmed = bob.post("/api/calendar/confirm", json={"draft_id": draft["draft_id"]}).json()
    assert confirmed["status"] == "confirmed_mock"
    assert not any(p["url"].startswith("https://www.googleapis.com/calendar") for p in fake_google.posts)
