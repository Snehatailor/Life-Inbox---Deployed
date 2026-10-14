"""Two-user tenant isolation: every feature is scoped to the current owner."""

import ast
import importlib
import json
import re
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.image_fixtures import make_png_bytes
from tests.pdf_fixtures import make_text_pdf
from tests.voice_fixtures import make_wav_bytes


SENTINEL_A = "USER_A_PRIVATE_ALPHA_9917"
SENTINEL_B = "USER_B_PRIVATE_BETA_8824"
TOKEN_A = "ALPHA-9917"
TOKEN_B = "BETA-8824"
LEAK_A = re.compile(r"ALPHA.9917")
LEAK_B = re.compile(r"BETA.8824")

_RELOADED_MODULES = (
    "app.main",
    "app.database",
    "app.auth",
    "app.config",
    "app.integrations.calendar",
    "app.retrieval.ask",
)


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'isolation.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LIFE_INBOX_ENV", "local")
    monkeypatch.setenv("LIFE_INBOX_CALENDAR_PROVIDER", "mock")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for name in _RELOADED_MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    with ExitStack() as stack:

        def make_client(base_url: str = "http://testserver") -> TestClient:
            return stack.enter_context(TestClient(main.app, base_url=base_url))

        yield SimpleNamespace(main=main, db=database, make_client=make_client)
    database.engine.dispose()
    for name in _RELOADED_MODULES:
        sys.modules.pop(name, None)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/dev-login", json={"email": email})
    assert response.status_code == 200, response.text
    return response.json()


def _seed_user(client: TestClient, sentinel: str, token: str) -> dict:
    """Create every kind of owned record for the signed-in user."""
    texts = [
        f"{sentinel} urgent: pay the tax bill today, deadline tomorrow",
        f"{sentinel} urgent: pay the tax bill today, deadline tomorrow!",
        f"SECRET PROJECT {token} launches Friday.",
    ]
    note_ids = [
        client.post("/api/items", json={"raw_text": text}).json()["id"]
        for text in texts
    ]
    topic = client.post("/api/topics", json={"name": f"Topic {sentinel}"}).json()
    pdf = client.post(
        "/api/items/pdf",
        files={
            "file": (
                f"{sentinel}.pdf",
                make_text_pdf(f"{sentinel} PDF body"),
                "application/pdf",
            )
        },
    ).json()
    image = client.post(
        "/api/items/image",
        files={"file": (f"{sentinel}.png", make_png_bytes(), "image/png")},
    ).json()
    voice = client.post(
        "/api/items/voice",
        files={"file": (f"{sentinel}.wav", make_wav_bytes(), "audio/wav")},
    ).json()

    analysis = client.post("/api/analyze")
    assert analysis.status_code == 200, analysis.text

    insight = client.patch(
        f"/api/items/{note_ids[0]}/insight",
        json={"user_topic_id": topic["id"]},
    )
    assert insight.status_code == 200, insight.text
    client.patch(f"/api/items/{note_ids[2]}/insight", json={"needs_review": True})

    tasks = client.get("/api/tasks").json()
    assert tasks, "deterministic organizer should create tasks"
    task_id = tasks[0]["id"]
    client.post(f"/api/tasks/{task_id}/confirm-timing", json={"timing_text": "tomorrow"})
    client.post(f"/api/tasks/{task_id}/reminder", json={"reminder_at": "2099-02-01"})
    if len(tasks) > 1:
        client.post(f"/api/tasks/{tasks[1]['id']}/snooze", json={"until": "2099-01-01"})
    preview = client.post("/api/calendar/preview", json={"task_id": task_id})
    assert preview.status_code == 200, preview.text

    relations = client.get("/api/relations").json()
    assert relations, "near-identical notes should produce a relation"
    return {
        "note_ids": note_ids,
        "item_ids": note_ids + [pdf["id"], image["id"], voice["id"]],
        "pdf_id": pdf["id"],
        "image_id": image["id"],
        "voice_id": voice["id"],
        "topic_id": topic["id"],
        "task_ids": [task["id"] for task in tasks],
        "relation_ids": [relation["id"] for relation in relations],
        "draft_id": preview.json()["draft_id"],
        "analysis_run_id": analysis.json()["analysis_run_id"],
    }


@pytest.fixture()
def two_users(app_env):
    a_client = app_env.make_client()
    b_client = app_env.make_client()
    a_user = _login(a_client, "alpha-owner@example.com")
    b_user = _login(b_client, "ak@gmail.com")
    a_seed = _seed_user(a_client, SENTINEL_A, TOKEN_A)
    b_seed = _seed_user(b_client, SENTINEL_B, TOKEN_B)
    return SimpleNamespace(
        env=app_env,
        a=SimpleNamespace(client=a_client, user=a_user, seed=a_seed, leak=LEAK_A, token=TOKEN_A),
        b=SimpleNamespace(client=b_client, user=b_user, seed=b_seed, leak=LEAK_B, token=TOKEN_B),
    )


def _directions(two_users):
    return [
        (two_users.a, two_users.b),
        (two_users.b, two_users.a),
    ]


def _cross_owner_relation_count(database) -> int:
    with database.SessionLocal() as session:
        relations = session.scalars(
            database.select(database.ItemRelationRecord)
        ).all()
        owners = {
            item.id: item.owner_user_id
            for item in session.scalars(
                database.select(database.InboxItemRecord)
            ).all()
        }
    return sum(
        1
        for relation in relations
        if owners.get(relation.item_id_a) != owners.get(relation.item_id_b)
    )


def _assert_no_leak(response, leak: re.Pattern, label: str) -> None:
    body = response.text
    assert not leak.search(body), f"{label} leaked foreign data: {body[:400]}"


COLLECTION_ROUTES = [
    "/api/items?limit=500",
    "/api/notes",
    "/api/tasks?status=all",
    "/api/topics?include_archived=true",
    "/api/relations?include_dismissed=true",
    "/api/dashboard",
    "/api/analyze/latest",
    "/api/attention",
    "/api/briefing",
    "/api/auth/me",
]


def test_collections_never_include_the_other_users_data(two_users):
    for viewer, other in _directions(two_users):
        client = viewer.client
        for route in COLLECTION_ROUTES:
            response = client.get(route)
            assert response.status_code == 200, (route, response.text)
            _assert_no_leak(response, other.leak, route)

        own_ids = set(viewer.seed["item_ids"])
        assert client.get("/api/search", params={"q": other.token}).json() == []
        other_sentinel = SENTINEL_A if other is two_users.a else SENTINEL_B
        for query in (other_sentinel, "urgent tax bill", "secret project launches"):
            search = client.get("/api/search", params={"q": query})
            assert search.status_code == 200
            _assert_no_leak(search, other.leak, f"search {query}")
            assert {hit["item_id"] for hit in search.json()} <= own_ids

        other_ids = set(other.seed["item_ids"])
        items = client.get("/api/items", params={"limit": 500}).json()
        assert {item["id"] for item in items} == own_ids
        assert {item["owner_user_id"] for item in items} == {viewer.user["id"]}

        dashboard = client.get("/api/dashboard").json()
        for section in ("high_priority", "recently_captured", "needs_review"):
            ids = {card["id"] for card in dashboard[section]}
            assert ids <= own_ids, section
            assert not ids & other_ids, section
        assert dashboard["high_priority"], "own High priority items stay visible"
        assert dashboard["related_items"], "own relations stay visible"
        for relation in dashboard["related_items"]:
            assert {relation["item_id_a"], relation["item_id_b"]} <= own_ids
        assert dashboard["analysis"]["analysis_run_id"] == viewer.seed["analysis_run_id"]
        assert {task["id"] for task in dashboard["open_tasks"]} <= set(viewer.seed["task_ids"])

        topics = client.get("/api/topics", params={"include_archived": True}).json()
        topic_ids = {topic["id"] for topic in topics}
        assert viewer.seed["topic_id"] in topic_ids
        assert other.seed["topic_id"] not in topic_ids
        own_counts = sum(topic["item_count"] for topic in topics)
        assert own_counts <= len(viewer.seed["item_ids"])
        custom = next(t for t in topics if t["id"] == viewer.seed["topic_id"])
        assert custom["item_count"] == 1

        relations = client.get("/api/relations", params={"include_dismissed": True}).json()
        assert {r["id"] for r in relations} == set(viewer.seed["relation_ids"])

        tasks = client.get("/api/tasks", params={"status": "all"}).json()
        assert {task["id"] for task in tasks} == set(viewer.seed["task_ids"])
        for task in tasks:
            assert set(task["source_item_ids"]) <= own_ids

        latest = client.get("/api/analyze/latest").json()
        assert latest["analysis_run_id"] == viewer.seed["analysis_run_id"]
        analyzed_ids = {
            note["id"] for bucket in latest["buckets"] for note in bucket["notes"]
        }
        assert analyzed_ids <= own_ids

        attention = client.get("/api/attention").json()
        board_ids = {
            entry["id"]
            for bucket, entries in attention.items()
            if isinstance(entries, list)
            for entry in entries
        }
        assert board_ids <= set(viewer.seed["task_ids"])
        briefing = client.get("/api/briefing").json()
        assert {s["task_id"] for s in briefing["priority_suggestions"]} <= set(
            viewer.seed["task_ids"]
        )

    assert _cross_owner_relation_count(two_users.env.db) == 0


def _owner_snapshot(client: TestClient, seed: dict) -> dict:
    return {
        "items": client.get("/api/items", params={"limit": 500}).json(),
        "tasks": client.get("/api/tasks", params={"status": "all"}).json(),
        "topics": client.get("/api/topics", params={"include_archived": True}).json(),
        "relations": client.get("/api/relations", params={"include_dismissed": True}).json(),
        "insights": [
            client.get(f"/api/items/{item_id}/insight").json()
            for item_id in seed["note_ids"]
        ],
        "latest": client.get("/api/analyze/latest").json(),
    }


def _foreign_id_requests(other_seed: dict, viewer_seed: dict):
    item = other_seed["note_ids"][0]
    pdf = other_seed["pdf_id"]
    image = other_seed["image_id"]
    voice = other_seed["voice_id"]
    task = other_seed["task_ids"][0]
    topic = other_seed["topic_id"]
    relation = other_seed["relation_ids"][0]
    return [
        ("GET", f"/api/items/{item}", None),
        ("PUT", f"/api/items/{item}", {"raw_text": "overwritten"}),
        ("DELETE", f"/api/items/{item}", None),
        ("PUT", f"/api/notes/{item}", {"text": "overwritten"}),
        ("DELETE", f"/api/notes/{item}", None),
        ("GET", f"/api/items/{pdf}", None),
        ("GET", f"/api/items/{pdf}/file", None),
        ("GET", f"/api/items/{image}/file", None),
        ("GET", f"/api/items/{image}/file?variant=thumb", None),
        ("GET", f"/api/items/{voice}/file", None),
        ("PATCH", f"/api/items/{pdf}/extracted-text", {"extracted_text": "overwritten"}),
        ("PATCH", f"/api/items/{voice}/extracted-text", {"extracted_text": "overwritten"}),
        ("POST", f"/api/items/{pdf}/retry", None),
        ("POST", f"/api/items/{image}/retry", None),
        ("GET", f"/api/items/{item}/insight", None),
        ("PATCH", f"/api/items/{item}/insight", {"user_title": "PWNED"}),
        ("PATCH", f"/api/items/{item}/insight", {"user_priority": "Low"}),
        ("PATCH", f"/api/items/{item}/insight", {"user_topic_id": viewer_seed["topic_id"]}),
        ("PATCH", f"/api/items/{item}/insight", {"user_tags": ["pwned"]}),
        ("PATCH", f"/api/items/{item}/insight", {"needs_review": True}),
        ("PATCH", f"/api/items/{item}/insight", {"clear_overrides": True}),
        ("POST", f"/api/relations/{relation}/dismiss", None),
        ("POST", f"/api/tasks/{task}/complete", None),
        ("POST", f"/api/tasks/{task}/reopen", None),
        ("POST", f"/api/tasks/{task}/dismiss", None),
        ("POST", f"/api/tasks/{task}/confirm-timing", {"timing_text": "next week"}),
        ("POST", f"/api/tasks/{task}/snooze", {"until": "2031-01-01"}),
        ("POST", f"/api/tasks/{task}/reminder", {"reminder_at": "2031-01-01"}),
        ("PATCH", f"/api/topics/{topic}", {"name": "Renamed by intruder"}),
        ("PATCH", f"/api/topics/{topic}", {"archived": True}),
        ("POST", "/api/calendar/preview", {"task_id": task}),
        ("POST", "/api/calendar/confirm", {"draft_id": other_seed["draft_id"]}),
    ]


def test_direct_foreign_ids_are_not_found_in_both_directions(two_users):
    database = two_users.env.db
    def receipt_count(task_ids):
        with database.SessionLocal() as session:
            return len(
                session.scalars(
                    database.select(database.CalendarActionReceiptRecord).where(
                        database.CalendarActionReceiptRecord.task_id.in_(task_ids)
                    )
                ).all()
            )

    for viewer, other in _directions(two_users):
        before = _owner_snapshot(other.client, other.seed)
        receipts_before = receipt_count(other.seed["task_ids"])
        for method, path, body in _foreign_id_requests(other.seed, viewer.seed):
            response = viewer.client.request(method, path, json=body)
            assert response.status_code == 404, (method, path, response.status_code, response.text)
            _assert_no_leak(response, other.leak, f"{method} {path}")
        after = _owner_snapshot(other.client, other.seed)
        assert after == before, "foreign requests must not change the owner's data"
        assert receipt_count(other.seed["task_ids"]) == receipts_before

        own_draft = viewer.client.post(
            "/api/calendar/confirm", json={"draft_id": viewer.seed["draft_id"]}
        )
        assert own_draft.status_code == 200
        assert own_draft.json()["receipt"]["task_id"] == viewer.seed["task_ids"][0]


def test_insight_cannot_point_at_a_foreign_topic(two_users):
    for viewer, other in _directions(two_users):
        response = viewer.client.patch(
            f"/api/items/{viewer.seed['note_ids'][1]}/insight",
            json={"user_topic_id": other.seed["topic_id"]},
        )
        assert response.status_code == 400
        topics = other.client.get("/api/topics").json()
        custom = next(t for t in topics if t["id"] == other.seed["topic_id"])
        assert custom["item_count"] == 1


def test_legacy_foreign_topic_reference_is_ignored(two_users):
    database = two_users.env.db
    a, b = two_users.a, two_users.b
    with database.SessionLocal() as session:
        insight = session.get(database.ItemInsightRecord, a.seed["note_ids"][1])
        insight.user_topic_id = b.seed["topic_id"]
        session.commit()

    b_custom = next(
        t for t in b.client.get("/api/topics").json() if t["id"] == b.seed["topic_id"]
    )
    assert b_custom["item_count"] == 1
    a_insight = a.client.get(f"/api/items/{a.seed['note_ids'][1]}/insight").json()
    assert a_insight["user_topic_id"] is None
    assert a_insight["effective_topic_id"] != b.seed["topic_id"]


def test_relation_refresh_never_links_owners(two_users):
    database = two_users.env.db
    a, b = two_users.a, two_users.b
    a_relations_before = a.client.get("/api/relations", params={"include_dismissed": True}).json()

    # Both inboxes hold near-identical text; B re-analyzing must not touch A.
    assert b.client.post("/api/analyze").status_code == 200
    assert _cross_owner_relation_count(database) == 0
    assert (
        a.client.get("/api/relations", params={"include_dismissed": True}).json()
        == a_relations_before
    )

    dismissed = a.client.post(f"/api/relations/{a.seed['relation_ids'][0]}/dismiss")
    assert dismissed.status_code == 200

    # Rows a pre-fix analysis could have produced: cross-owner, live and dismissed.
    a_item, b_item = a.seed["note_ids"][0], b.seed["note_ids"][0]
    a_other, b_other = a.seed["note_ids"][2], b.seed["note_ids"][2]
    with database.SessionLocal() as session:
        for left, right, dismissed_flag in ((a_item, b_item, 0), (a_other, b_other, 1)):
            low, high = sorted((left, right))
            session.add(
                database.ItemRelationRecord(
                    item_id_a=low,
                    item_id_b=high,
                    relation_type="near_duplicate",
                    score="0.9000",
                    created_at="2026-01-01T00:00:00+00:00",
                    dismissed=dismissed_flag,
                )
            )
        session.commit()
        cross_ids = [
            row.id
            for row in session.scalars(database.select(database.ItemRelationRecord)).all()
            if row.relation_type == "near_duplicate"
            and {row.item_id_a, row.item_id_b} & {a_item, a_other}
            and {row.item_id_a, row.item_id_b} & {b_item, b_other}
        ]
    assert _cross_owner_relation_count(database) == 2

    for viewer in (a, b):
        listed = viewer.client.get("/api/relations", params={"include_dismissed": True}).json()
        assert not {r["id"] for r in listed} & set(cross_ids)
        dashboard = viewer.client.get("/api/dashboard").json()
        assert not {r["id"] for r in dashboard["related_items"]} & set(cross_ids)
        for cross_id in cross_ids:
            assert viewer.client.post(f"/api/relations/{cross_id}/dismiss").status_code == 404

    assert a.client.post("/api/analyze").status_code == 200
    assert _cross_owner_relation_count(database) == 0

    a_after = a.client.get("/api/relations", params={"include_dismissed": True}).json()
    kept = next(r for r in a_after if r["id"] == a.seed["relation_ids"][0])
    assert kept["dismissed"] is True
    assert a.seed["relation_ids"][0] not in {
        r["id"] for r in a.client.get("/api/relations").json()
    }


def test_analysis_runs_are_independent(app_env):
    a_client = app_env.make_client()
    b_client = app_env.make_client()
    _login(a_client, "alpha-owner@example.com")
    _login(b_client, "ak@gmail.com")
    a_seed = _seed_user(a_client, SENTINEL_A, TOKEN_A)
    a_latest = a_client.get("/api/analyze/latest").json()

    assert b_client.get("/api/analyze/latest").status_code == 204
    b_dashboard = b_client.get("/api/dashboard")
    _assert_no_leak(b_dashboard, LEAK_A, "empty B dashboard")
    b_dashboard = b_dashboard.json()
    assert b_dashboard["analysis"] is None
    for section in ("high_priority", "recently_captured", "needs_review", "related_items", "open_tasks"):
        assert b_dashboard[section] == [], section
    assert all(topic["item_count"] == 0 for topic in b_dashboard["topics"])

    b_run = b_client.post("/api/analyze")
    assert b_run.status_code == 200
    _assert_no_leak(b_run, LEAK_A, "B analyze")
    assert b_run.json()["analysis_run_id"] != a_seed["analysis_run_id"]
    assert b_client.get("/api/analyze/latest").json()["analysis_run_id"] == b_run.json()["analysis_run_id"]

    a_after = a_client.get("/api/analyze/latest").json()
    assert a_after["analysis_run_id"] == a_latest["analysis_run_id"]
    assert a_after["is_stale"] is False
    assert a_client.get("/api/relations").json()


def _capture_llm_prompts(monkeypatch) -> list[str]:
    import openai

    prompts: list[str] = []

    def create(**kwargs):
        prompt = kwargs["input"]
        prompts.append(prompt)
        citation_ids = re.findall(r'"citation_id": "([^"]+)"', prompt)
        return SimpleNamespace(
            output_text=json.dumps(
                {
                    "answer": "Grounded answer from your own inbox.",
                    "confidence": "high" if citation_ids else "insufficient",
                    "citation_ids": citation_ids[:1],
                }
            )
        )

    monkeypatch.setenv("OPENAI_API_KEY", "configured-for-test")
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda: SimpleNamespace(responses=SimpleNamespace(create=create)),
    )
    return prompts


def test_ask_is_scoped_extractive(two_users):
    for viewer, other in _directions(two_users):
        foreign = viewer.client.post("/api/ask", json={"question": f"What is {other.token}?"})
        assert foreign.status_code == 200
        body = foreign.json()
        assert body["confidence"] == "insufficient"
        assert body["citations"] == []
        assert not other.leak.search(body["answer"])

        own = viewer.client.post("/api/ask", json={"question": f"What is {viewer.token}?"})
        own_body = own.json()
        assert own_body["confidence"] != "insufficient"
        assert {c["item_id"] for c in own_body["citations"]} <= set(viewer.seed["item_ids"])


def test_ask_llm_never_receives_foreign_evidence(two_users, monkeypatch):
    prompts = _capture_llm_prompts(monkeypatch)
    for viewer, other in _directions(two_users):
        prompts.clear()
        for question in (
            f"What is {other.token}?",
            "When does the secret project launch?",
            "What urgent tax bill do I need to pay?",
        ):
            response = viewer.client.post("/api/ask", json={"question": question})
            assert response.status_code == 200
            body = response.json()
            assert {c["item_id"] for c in body["citations"]} <= set(viewer.seed["item_ids"])
            if other.token in question:
                assert body["confidence"] == "insufficient"
                assert body["citations"] == []

        assert prompts, "the LLM path should run for the viewer's own matches"
        for prompt in prompts:
            evidence = json.loads(prompt.split("Evidence (JSON):", 1)[1])
            assert evidence
            assert {e["item_id"] for e in evidence} <= set(viewer.seed["item_ids"])
            assert not other.leak.search(json.dumps(evidence))
            assert viewer.leak.search(json.dumps(evidence)) or any(
                "tax bill" in e["excerpt"] for e in evidence
            )


def test_non_local_without_session_fails_closed(app_env, monkeypatch):
    database = app_env.db
    local = app_env.make_client()
    local.post("/api/items", json={"raw_text": "LOCAL_OWNER_PRIVATE note"})

    monkeypatch.setenv("LIFE_INBOX_ENV", "beta")
    anon = app_env.make_client(base_url="https://testserver")
    with database.SessionLocal() as session:
        before = len(session.scalars(database.select(database.InboxItemRecord)).all())

    for method, path, body in [
        ("GET", "/api/items", None),
        ("POST", "/api/items", {"raw_text": "anonymous write"}),
        ("GET", "/api/items/1", None),
        ("GET", "/api/items/1/file", None),
        ("GET", "/api/dashboard", None),
        ("GET", "/api/relations", None),
        ("GET", "/api/tasks", None),
        ("GET", "/api/topics", None),
        ("GET", "/api/search?q=LOCAL", None),
        ("POST", "/api/ask", {"question": "What is private?"}),
        ("POST", "/api/analyze", None),
        ("GET", "/api/analyze/latest", None),
        ("GET", "/api/attention", None),
        ("GET", "/api/briefing", None),
        ("POST", "/api/calendar/preview", {"task_id": 1}),
        ("GET", "/api/auth/me", None),
    ]:
        response = anon.request(method, path, json=body)
        assert response.status_code == 401, (method, path, response.text)
        assert "LOCAL_OWNER_PRIVATE" not in response.text

    with database.SessionLocal() as session:
        after = len(session.scalars(database.select(database.InboxItemRecord)).all())
    assert after == before

    assert anon.get("/api/health").status_code == 200
    assert anon.get("/").status_code == 200

    tampered = app_env.make_client(base_url="https://testserver")
    tampered.cookies.set("life_inbox_session", "garbage.signature")
    assert tampered.get("/api/items").status_code == 401

    from app.auth import SESSION_COOKIE, create_session_token

    ghost = app_env.make_client(base_url="https://testserver")
    ghost.cookies.set(SESSION_COOKIE, create_session_token(987654))
    assert ghost.get("/api/items").status_code == 401

    user = _login(anon, "beta-user@example.com")
    items = anon.get("/api/items")
    assert items.status_code == 200
    assert items.json() == []
    created = anon.post("/api/items", json={"raw_text": "beta user note"}).json()
    assert created["owner_user_id"] == user["id"]
    assert anon.get("/api/auth/me").json()["email"] == "beta-user@example.com"


def test_local_mode_keeps_local_owner_and_separates_dev_users(app_env):
    client = app_env.make_client()
    me = client.get("/api/auth/me").json()
    assert me["email"] == "local@life-inbox.local"
    local_item = client.post("/api/items", json={"raw_text": "Local owner note"}).json()
    assert local_item["owner_user_id"] == me["id"]

    _login(client, "dev-user@example.com")
    assert client.get("/api/items").json() == []
    assert client.get(f"/api/items/{local_item['id']}").status_code == 404

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json()["email"] == "local@life-inbox.local"
    assert [item["id"] for item in client.get("/api/items").json()] == [local_item["id"]]


def test_require_owner_id_never_falls_back(app_env):
    database = app_env.db
    database.set_current_owner_id(None)
    with pytest.raises(database.OwnerRequiredError):
        database.require_owner_id()
    with pytest.raises(database.OwnerRequiredError):
        database.list_items_from_db()
    with pytest.raises(database.OwnerRequiredError):
        database.get_organization_dashboard()


_USER_DATA_MODELS = {
    "InboxItemRecord",
    "TaskRecord",
    "TopicRecord",
    "ItemInsightRecord",
    "ItemRelationRecord",
    "AnalysisRunRecord",
    "CalendarActionReceiptRecord",
    "TaskSourceItemRecord",
}
_OWNER_GUARD_EXEMPT = {"init_db"}


def test_public_database_helpers_require_an_owner():
    """Defense in depth: any public helper touching user tables binds an owner."""
    source_path = Path(__file__).resolve().parent.parent / "app" / "database.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    offenders = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        if node.name in _OWNER_GUARD_EXEMPT:
            continue
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        if not names & _USER_DATA_MODELS:
            continue
        has_owner_param = any(arg.arg == "owner_user_id" for arg in node.args.args)
        if "require_owner_id" not in names and not has_owner_param:
            offenders.append(node.name)
    assert offenders == []
