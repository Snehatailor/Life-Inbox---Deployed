"""Team leaderboard: opt-in sharing, invite codes, privacy."""

from datetime import date, timedelta

from app.attention.dates import today_in_configured_tz
from app.game.teams import build_leaderboard, normalize_code, new_invite_code, week_start

from tests.test_api import client  # noqa: F401  (fixture)
from tests.test_isolation import _login, app_env  # noqa: F401  (fixture + helper)

TODAY = date(2026, 11, 4)  # Wednesday


def test_week_starts_on_monday_and_codes_are_clean():
    assert week_start(TODAY) == date(2026, 11, 2)
    code = new_invite_code()
    assert len(code) == 8 and normalize_code(f" {code.lower()[:4]}-{code.lower()[4:]} ") == code


def test_leaderboard_ranks_week_points_and_hides_private_members():
    members = [
        {"user_id": 1, "display_name": "Ana", "share": True, "tasks_week": 3,
         "by_day": {"2026-11-02": 60, "2026-11-03": 50, "2026-10-20": 400}},
        {"user_id": 2, "display_name": "Ben", "share": True, "tasks_week": 5,
         "by_day": {"2026-11-03": 120, "2026-11-04": 30}},
        {"user_id": 3, "display_name": "Cal", "share": False, "tasks_week": 9,
         "by_day": {"2026-11-03": 500}},
    ]
    board = build_leaderboard(members, TODAY)
    assert [(r["display_name"], r["points_week"], r["rank"]) for r in board["rows"]] == [
        ("Ben", 150, 1), ("Ana", 110, 2),
    ]
    assert board["private_count"] == 1
    assert "Cal" not in str(board)  # private members are counted, never named
    assert board["rows"][0]["days_goal_met"] == 1 and board["rows"][0]["streak"] == 1  # goal met yesterday


def test_ties_share_a_rank():
    members = [
        {"user_id": i, "display_name": n, "share": True, "tasks_week": 2, "by_day": {"2026-11-03": 40}}
        for i, n in [(1, "Ana"), (2, "Ben")]
    ]
    assert [r["rank"] for r in build_leaderboard(members, TODAY)["rows"]] == [1, 1]


def _complete_task(client, sentence):
    task = client.post("/api/tasks/quick", json={"sentence": sentence}).json()
    client.post(f"/api/tasks/{task['id']}/complete")


def test_two_people_share_a_team_and_privacy_is_respected(app_env):
    ana = app_env.make_client()
    ben = app_env.make_client()
    assert _login(ana, "ana@example.com")  # sign-in helper returns the response body
    _login(ben, "ben@example.com")

    created = ana.post("/api/teams", json={"name": "Study Group", "share": True})
    assert created.status_code == 200
    team = created.json()["team"]
    code = team["invite_code"]
    assert team["member_count"] == 1 and team["i_share"] is True

    assert ana.post("/api/teams", json={"name": "Second", "share": True}).status_code == 409
    assert ben.get("/api/teams/me").json() == {"team": None}
    assert ben.post("/api/teams/join", json={"code": "WRONGCODE", "share": True}).status_code == 404

    _complete_task(ana, "Write essay today high priority")
    _complete_task(ben, "Call mum today medium priority")

    joined = ben.post("/api/teams/join", json={"code": code.lower(), "share": False}).json()["team"]
    assert joined["member_count"] == 2 and joined["i_share"] is False

    ana_view = ana.get("/api/teams/me").json()["team"]
    assert len(ana_view["rows"]) == 1
    assert ana_view["private_count"] == 1
    assert ana_view["rows"][0]["is_me"] is True and ana_view["rows"][0]["points_week"] == 30
    ben_name = ben.get("/api/auth/me").json()["display_name"]
    assert ben_name not in str(ana_view)  # Ben opted out: counted, never named

    shared = ben.patch("/api/teams/me", json={"share": True}).json()["team"]
    assert shared["private_count"] == 0 and len(shared["rows"]) == 2
    assert [r["points_week"] for r in shared["rows"]] == [30, 20]
    assert "email" not in str(shared).lower() and "@" not in str(shared)

    assert ben.post("/api/teams/leave").status_code == 204
    assert ben.get("/api/teams/me").json() == {"team": None}
    assert ana.get("/api/teams/me").json()["team"]["member_count"] == 1
    assert ana.post("/api/teams/leave").status_code == 204
    assert ben.post("/api/teams/join", json={"code": code, "share": True}).status_code == 404  # team deleted


def test_team_name_is_validated_and_sharing_defaults_to_off(client):
    assert client.get("/api/teams/me").json() == {"team": None}
    assert client.post("/api/teams", json={"name": "x", "share": True}).status_code == 422
    team = client.post("/api/teams", json={"name": "Solo"}).json()["team"]
    assert team["i_share"] is False and team["rows"] == [] and team["private_count"] == 1
    assert client.patch("/api/teams/me", json={"share": True}).json()["team"]["rows"][0]["is_me"]
