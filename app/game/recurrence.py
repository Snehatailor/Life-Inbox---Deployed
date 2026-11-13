"""Repeat rules for recurring tasks: pure date logic, no database.

A rule is stored as text on the task:

    daily              every day
    weekdays           Monday to Friday
    weekly             every 7 days from the due date
    days:mon,wed,fri   the chosen weekdays

`next_due` works out the next copy's due date. It counts on from the task's
own due date (or today, if it had none) and skips dates that are already past,
so a habit finished late stays on its schedule instead of piling up.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

DAY_CODES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_LABELS = dict(zip(DAY_CODES, ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")))
SIMPLE_RULES = {"daily", "weekdays", "weekly"}
MAX_RULE_LENGTH = 60


def normalize_rule(rule: Optional[str]) -> Optional[str]:
    """Return the canonical form of a rule, or None for "no repeat".

    Raises ValueError for anything that is not a valid rule.
    """
    if rule is None:
        return None
    text = str(rule).strip().lower()
    if text in {"", "none", "never", "off"}:
        return None
    if len(text) > MAX_RULE_LENGTH:
        raise ValueError("That repeat rule is too long")
    if text in SIMPLE_RULES:
        return text
    if text.startswith("days:"):
        chosen = [part.strip() for part in text[5:].split(",") if part.strip()]
        unknown = [part for part in chosen if part not in DAY_CODES]
        if unknown or not chosen:
            raise ValueError("Pick at least one day, like days:mon,wed,fri")
        ordered = [code for code in DAY_CODES if code in set(chosen)]
        if len(ordered) == 7:
            return "daily"
        if ordered == ["mon", "tue", "wed", "thu", "fri"]:
            return "weekdays"
        return "days:" + ",".join(ordered)
    raise ValueError("Repeat must be daily, weekdays, weekly or days:mon,wed,...")


def _matches(rule: str, day: date) -> bool:
    if rule == "daily":
        return True
    if rule == "weekdays":
        return day.weekday() < 5
    if rule.startswith("days:"):
        return DAY_CODES[day.weekday()] in rule[5:].split(",")
    return False


def _step(rule: str, day: date) -> date:
    """The first date after `day` that the rule allows."""
    if rule == "weekly":
        return day + timedelta(days=7)
    candidate = day + timedelta(days=1)
    for _ in range(7):
        if _matches(rule, candidate):
            return candidate
        candidate += timedelta(days=1)
    raise ValueError(f"Rule {rule!r} never matches")


def next_due(rule: str, due_on: Optional[date], today: date) -> date:
    """Due date for the next copy: after the current due date and after today."""
    rule = normalize_rule(rule)
    if rule is None:
        raise ValueError("This task does not repeat")
    candidate = _step(rule, due_on or today)
    while candidate <= today:
        candidate = _step(rule, candidate)
    return candidate


def describe(rule: Optional[str]) -> Optional[str]:
    """Short label for the ↻ badge, e.g. "Mon, Wed, Fri"."""
    try:
        rule = normalize_rule(rule)
    except ValueError:
        return None
    if rule is None:
        return None
    if rule == "daily":
        return "Every day"
    if rule == "weekdays":
        return "Weekdays"
    if rule == "weekly":
        return "Every week"
    return ", ".join(DAY_LABELS[code] for code in rule[5:].split(","))
