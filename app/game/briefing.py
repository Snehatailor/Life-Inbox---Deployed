"""Build the spoken "what's due today?" briefing from tasks and progress."""

from datetime import date
from typing import Optional

MAX_NAMED = 3
MAX_TASK_CHARS = 60


def _short(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_TASK_CHARS else text[: MAX_TASK_CHARS - 1].rstrip() + "…"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _name_list(tasks: list[dict]) -> str:
    names = [_short(t["text"]) for t in tasks[:MAX_NAMED]]
    extra = len(tasks) - len(names)
    if extra > 0:
        names.append(f"and {extra} more")
    elif len(names) > 1:
        names[-1] = f"and {names[-1]}"
    return ", ".join(names) if len(names) > 2 else " ".join(names) if len(names) == 2 else names[0]


def greeting(hour: int) -> str:
    if hour < 12:
        return "Good morning."
    if hour < 18:
        return "Good afternoon."
    return "Good evening."


def build_briefing(open_tasks: list[dict], summary: dict, today: date, hour: int) -> dict:
    overdue = [t for t in open_tasks if t.get("days_left") is not None and t["days_left"] < 0]
    due_today = [t for t in open_tasks if t.get("days_left") == 0]
    upcoming = sorted(
        (t for t in open_tasks if t.get("days_left") is not None and t["days_left"] > 0),
        key=lambda t: (t["days_left"], -t["points_value"]),
    )

    parts = [greeting(hour)]
    if overdue:
        parts.append(f"{_plural(len(overdue), 'task')} overdue: {_name_list(overdue)}.")
    if due_today:
        parts.append(f"{_plural(len(due_today), 'task')} due today: {_name_list(due_today)}.")
    if not overdue and not due_today:
        parts.append("Nothing is due today.")
    if upcoming:
        nxt = upcoming[0]
        when = "tomorrow" if nxt["days_left"] == 1 else f"in {nxt['days_left']} days"
        parts.append(f"Next up is {_short(nxt['text'])}, {when}.")

    points, goal = summary["points_today"], summary["goal"]
    if summary["goal_met"]:
        parts.append(f"You have already hit your {goal} coin goal today with {points}.")
    else:
        parts.append(f"You are at {points} of {goal} coins, {goal - points} to go.")
        pool = overdue + due_today or upcoming
        if pool:
            best = max(pool, key=lambda t: t["points_value"])
            parts.append(f"Finishing {_short(best['text'])} is worth {best['points_value']} coins.")
    if summary["streak"]:
        parts.append(f"Your streak is {_plural(summary['streak'], 'day')}.")

    return {
        "text": " ".join(parts),
        "overdue": len(overdue),
        "due_today": len(due_today),
        "upcoming": len(upcoming),
    }
