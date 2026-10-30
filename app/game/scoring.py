"""Scoring rules for Task Quest. Pure functions, no database access."""

from datetime import date
from typing import Optional

PRIORITY_POINTS = {"High": 30, "Medium": 20, "Low": 10}
DAILY_GOAL = 100
EARLY_BONUS = 5
OVERDUE_FACTOR = 0.5
SOON_DAYS = 2
RAISE_TO_HIGH_DAYS = 2
RAISE_TO_MEDIUM_DAYS = 5


def _parse_day(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def days_left(due_on: Optional[str], today: date) -> Optional[int]:
    """Whole days until the deadline; negative when overdue; None if no date."""
    due = _parse_day(due_on)
    if due is None:
        return None
    return (due - today).days


def urgency(due_on: Optional[str], today: date) -> str:
    left = days_left(due_on, today)
    if left is None:
        return "none"
    if left < 0:
        return "overdue"
    if left == 0:
        return "due"
    if left <= SOON_DAYS:
        return "soon"
    return "safe"


def days_left_label(due_on: Optional[str], today: date) -> Optional[str]:
    left = days_left(due_on, today)
    if left is None:
        return None
    if left < 0:
        n = -left
        return f"{n} day{'s' if n != 1 else ''} overdue"
    if left == 0:
        return "Due today"
    return f"{left} day{'s' if left != 1 else ''} left"


def points_for(priority: str, due_on: Optional[str], completed_on: date) -> int:
    """Base points by priority, +5 if done a day or more early, half if late."""
    base = PRIORITY_POINTS.get(priority, PRIORITY_POINTS["Low"])
    left = days_left(due_on, completed_on)
    if left is None or left == 0:
        return base
    if left < 0:
        return int(base * OVERDUE_FACTOR)
    return base + EARLY_BONUS


def default_due_offset(priority: str) -> int:
    """Days from today used to suggest a deadline when the note has none."""
    return {"High": 2, "Medium": 5, "Low": 10}.get(priority, 5)


def effective_priority(
    base: str,
    source: Optional[str],
    due_on: Optional[str],
    today: date,
    status: str = "open",
) -> str:
    """Priority after deadline pressure. Only raises, never lowers.

    Within 2 days (or overdue) becomes High; a Low task within 5 days becomes
    Medium. A priority a person chose, or a task that is not open, is left alone.
    """
    if source == "user" or status != "open":
        return base
    left = days_left(due_on, today)
    if left is None:
        return base
    if left <= RAISE_TO_HIGH_DAYS:
        return "High"
    if left <= RAISE_TO_MEDIUM_DAYS and base == "Low":
        return "Medium"
    return base
