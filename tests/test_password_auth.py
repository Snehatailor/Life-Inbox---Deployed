"""Email + password accounts: sign-up, sign-in, throttling, beta isolation."""

import importlib
import sys
from contextlib import ExitStack
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text


_RELOADED_MODULES = (
    "app.main",
    "app.database",
    "app.auth",
    "app.config",
    "app.integrations.calendar",
    "app.retrieval.ask",
)

PASSWORD = "correct horse battery"


def _make_env(tmp_path, monkeypatch, environment: str):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LIFE_INBOX_ENV", environment)
    monkeypatch.setenv("LIFE_INBOX_ALLOW_DEV_LOGIN", "0")
    monkeypatch.setenv("LIFE_INBOX_SESSION_SECRET", "x" * 40)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for name in _RELOADED_MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    auth = importlib.import_module("app.auth")
    auth.reset_login_throttle_for_tests()
    return main, database, auth


@pytest.fixture()
def beta_env(tmp_path, monkeypatch):
    main, database, auth = _make_env(tmp_path, monkeypatch, "beta")
    with ExitStack() as stack:

        def make_client() -> TestClient:
            # https so the Secure session cookie is sent back in beta mode.
            return stack.enter_context(
                TestClient(main.app, base_url="https://testserver")
            )

        yield SimpleNamespace(
            main=main,
            db=database,
            auth=auth,
            make_client=make_client,
            db_path=tmp_path / "auth.db",
        )
    database.engine.dispose()
    for name in _RELOADED_MODULES:
        sys.modules.pop(name, None)


def _register(client, email, password=PASSWORD, name=None):
    body = {"email": email, "password": password}
    if name is not None:
        body["display_name"] = name
    return client.post("/api/auth/register", json=body)


def test_hash_and_verify_password_round_trip(beta_env):
    auth = beta_env.auth
    stored = auth.hash_password(PASSWORD)
    assert PASSWORD not in stored
    assert stored.startswith("scrypt$")
    assert auth.verify_password(PASSWORD, stored)
    assert not auth.verify_password("wrong password", stored)
    assert not auth.verify_password(PASSWORD, None)
    assert not auth.verify_password(PASSWORD, "garbage")
    # Same password, different salt.
    assert auth.hash_password(PASSWORD) != stored


def test_register_signs_in_and_never_returns_the_hash(beta_env):
    client = beta_env.make_client()
    response = _register(client, "Alice@Example.com", name="Alice")
    assert response.status_code == 200, response.text
    user = response.json()
    assert user["email"] == "alice@example.com"
    assert user["display_name"] == "Alice"
    assert user["auth_provider"] == "password"
    assert "password_hash" not in user
    assert PASSWORD not in response.text
    assert "scrypt$" not in response.text

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"
    assert "password_hash" not in me.json()

    engine = create_engine(f"sqlite:///{beta_env.db_path}")
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT password_hash FROM users WHERE email = 'alice@example.com'")
        ).scalar()
    engine.dispose()
    assert stored and stored.startswith("scrypt$") and PASSWORD not in stored


def test_register_rejects_duplicates_bad_email_and_short_password(beta_env):
    client = beta_env.make_client()
    assert _register(client, "bob@example.com").status_code == 200
    duplicate = _register(beta_env.make_client(), "BOB@example.com")
    assert duplicate.status_code == 409
    assert _register(client, "not-an-email").status_code == 400
    assert _register(client, "carol@example.com", password="short").status_code == 400
    assert _register(client, "local@life-inbox.local").status_code == 400


def test_login_requires_the_right_password(beta_env):
    _register(beta_env.make_client(), "dana@example.com")

    client = beta_env.make_client()
    wrong = client.post(
        "/api/auth/login",
        json={"email": "dana@example.com", "password": "wrong password"},
    )
    assert wrong.status_code == 401
    assert client.get("/api/auth/me").status_code == 401

    unknown = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": PASSWORD},
    )
    assert unknown.status_code == 401
    # Same message for unknown email and wrong password.
    assert unknown.json()["detail"] == wrong.json()["detail"]

    ok = client.post(
        "/api/auth/login",
        json={"email": " DANA@example.com ", "password": PASSWORD},
    )
    assert ok.status_code == 200, ok.text
    assert client.get("/api/auth/me").json()["email"] == "dana@example.com"

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_dev_login_account_cannot_be_used_with_a_password(beta_env):
    beta_env.db.ensure_user(
        email="dev@example.com", display_name="Dev", auth_provider="dev"
    )
    client = beta_env.make_client()
    response = client.post(
        "/api/auth/login", json={"email": "dev@example.com", "password": PASSWORD}
    )
    assert response.status_code == 401


def test_repeated_failures_are_throttled(beta_env):
    _register(beta_env.make_client(), "erin@example.com")
    client = beta_env.make_client()
    limit = beta_env.auth.LOGIN_MAX_FAILURES
    for _ in range(limit):
        response = client.post(
            "/api/auth/login",
            json={"email": "erin@example.com", "password": "wrong password"},
        )
        assert response.status_code == 401
    blocked = client.post(
        "/api/auth/login", json={"email": "erin@example.com", "password": PASSWORD}
    )
    assert blocked.status_code == 429


def test_beta_requires_sign_in_and_keeps_accounts_apart(beta_env):
    anonymous = beta_env.make_client()
    assert anonymous.get("/api/items").status_code == 401
    assert anonymous.post("/api/items", json={"raw_text": "x"}).status_code == 401
    assert anonymous.get("/api/auth/config").status_code == 200
    assert anonymous.get("/api/health").status_code == 200

    alice = beta_env.make_client()
    _register(alice, "alice@example.com")
    created = alice.post("/api/items", json={"raw_text": "ALICE_PRIVATE_NOTE"})
    assert created.status_code == 200, created.text
    alice_item_id = created.json()["id"]

    bob = beta_env.make_client()
    _register(bob, "bob@example.com")
    bob_items = bob.get("/api/items").json()
    assert all("ALICE_PRIVATE_NOTE" not in str(item) for item in bob_items)
    assert bob.get(f"/api/items/{alice_item_id}").status_code == 404
    assert "ALICE_PRIVATE_NOTE" not in bob.get("/api/search?q=ALICE_PRIVATE_NOTE").text

    # Alice signs in again from a fresh browser and still sees her note.
    again = beta_env.make_client()
    login = again.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    assert any(
        item["id"] == alice_item_id for item in again.get("/api/items").json()
    )


def test_auth_config_reports_options(beta_env):
    config = beta_env.make_client().get("/api/auth/config").json()
    assert config["environment"] == "beta"
    assert config["allow_dev_login"] is False
    assert config["password_login"] is True
    assert config["anonymous_local_owner"] is False


def test_local_mode_still_falls_back_to_local_owner(tmp_path, monkeypatch):
    main, database, _ = _make_env(tmp_path, monkeypatch, "local")
    try:
        with TestClient(main.app) as client:
            assert client.get("/api/auth/me").json()["email"] == "local@life-inbox.local"
            assert client.get("/api/auth/config").json()["anonymous_local_owner"] is True
    finally:
        database.engine.dispose()
        for name in _RELOADED_MODULES:
            sys.modules.pop(name, None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///./data/x.db", "sqlite:///./data/x.db"),
        ("  sqlite:///y.db  ", "sqlite:///y.db"),
    ],
)
def test_normalize_database_url(raw, expected):
    from app.config import normalize_database_url

    assert normalize_database_url(raw) == expected


def test_migration_adds_password_hash_column(tmp_path):
    from tests.test_migrations import alembic_config
    from alembic import command

    database_path = tmp_path / "migrated.db"
    command.upgrade(alembic_config(database_path), "head")
    engine = create_engine(f"sqlite:///{database_path}")
    columns = {c["name"] for c in inspect(engine).get_columns("users")}
    engine.dispose()
    assert "password_hash" in columns
