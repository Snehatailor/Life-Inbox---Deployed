"""Team helpers: invite codes and the weekly leaderboard. No database access."""

import secrets
from datetime import date, timedelta

from app.game.progress import level_for, streak_days

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def new_invite_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def week_start(today: date) -> date:
    """Monday of the current week."""
    return today - timedelta(days=today.weekday())


def build_leaderboard(members: list[dict], today: date) -> dict:
    """members: {user_id, display_name, share, by_day: {iso: points}}.

    Only members who opted in get numbers; the rest are counted, not shown.
    """
    start = week_start(today).isoformat()
    shown = []
    private_count = 0
    for member in members:
        if not member["share"]:
            private_count += 1
            continue
        by_day = member["by_day"]
        week_days = {day: pts for day, pts in by_day.items() if day >= start}
        shown.append(
            {
                "user_id": member["user_id"],
                "display_name": member["display_name"],
                "points_week": sum(week_days.values()),
                "days_goal_met": sum(1 for pts in week_days.values() if pts >= 100),
                "streak": streak_days(by_day, today),
                "level": level_for(sum(by_day.values()))["title"],
                "tasks_week": member.get("tasks_week", 0),
            }
        )
    shown.sort(key=lambda row: (-row["points_week"], -row["tasks_week"], row["display_name"].lower()))
    rank = 0
    previous = None
    for index, row in enumerate(shown, start=1):
        key = (row["points_week"], row["tasks_week"])
        if key != previous:
            rank = index
            previous = key
        row["rank"] = rank
    return {"week_start": start, "rows": shown, "private_count": private_count}
