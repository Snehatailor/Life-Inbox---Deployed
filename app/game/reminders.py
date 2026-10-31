"""Pet reminders for tasks that have a saved time slot. Pure functions."""

from datetime import datetime, timedelta
from typing import Optional

SOON_MINUTES = 10
MISSED_WINDOW_MINUTES = 120
LOOKAHEAD_HOURS = 24
MAX_SLOT_HOURS = 8


def parse_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def _label(phase: str, minutes: int) -> str:
    if phase == "now":
        return "now"
    if phase == "missed":
        return f"{abs(minutes)} min ago"
    if minutes < 60:
        return f"in {minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"in {hours} h" if not rest else f"in {hours} h {rest} min"


def reminder_phase(start: datetime, end: datetime, now: datetime) -> Optional[str]:
    """later / soon (within 10 min) / now (inside the slot) / missed (ended, still open)."""
    if now < start:
        minutes = (start - now).total_seconds() / 60
        if minutes > LOOKAHEAD_HOURS * 60:
            return None
        return "soon" if minutes <= SOON_MINUTES else "later"
    if now < end:
        return "now"
    if now <= end + timedelta(minutes=MISSED_WINDOW_MINUTES):
        return "missed"
    return None


def build_reminders(tasks: list[dict], now: datetime) -> list[dict]:
    """Open tasks with a slot, soonest first, each tagged with a phase."""
    reminders = []
    for task in tasks:
        if task.get("status") != "open":
            continue
        start, end = parse_utc(task.get("slot_start")), parse_utc(task.get("slot_end"))
        if start is None or end is None:
            continue
        phase = reminder_phase(start, end, now)
        if phase is None:
            continue
        minutes = int((start - now).total_seconds() // 60) if phase != "missed" else int((end - now).total_seconds() // 60)
        reminders.append(
            {
                "task_id": task["id"],
                "text": task["text"],
                "priority": task["priority"],
                "domain": task.get("domain"),
                "slot_start": task["slot_start"],
                "slot_end": task["slot_end"],
                "phase": phase,
                "minutes_until": minutes,
                "label": _label(phase, minutes),
            }
        )
    reminders.sort(key=lambda r: r["slot_start"])
    return reminders


def validate_slot(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Slot times need a time zone")
    if end <= start:
        raise ValueError("A slot must end after it starts")
    if end - start > timedelta(hours=MAX_SLOT_HOURS):
        raise ValueError(f"A slot can be at most {MAX_SLOT_HOURS} hours")
