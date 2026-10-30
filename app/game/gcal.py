"""Google Calendar helpers that need no credentials: prefilled-event links and .ics."""

from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlencode


def _compact(day: date) -> str:
    return day.strftime("%Y%m%d")


def google_event_url(title: str, due_on: str, details: str = "") -> str:
    """All-day event on the deadline. Google shows it for the user to save."""
    start = date.fromisoformat(due_on[:10])
    query = urlencode(
        {
            "action": "TEMPLATE",
            "text": title,
            "dates": f"{_compact(start)}/{_compact(start + timedelta(days=1))}",
            "details": details,
        }
    )
    return f"https://calendar.google.com/calendar/render?{query}"


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def build_ics(tasks: Iterable[dict]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Life Inbox//Task Quest//EN",
        "CALSCALE:GREGORIAN",
    ]
    for task in tasks:
        if not task.get("due_on"):
            continue
        start = date.fromisoformat(task["due_on"][:10])
        summary = f"[{task['priority']}] {task['text']} (+{task['points_value']} pts)"
        lines += [
            "BEGIN:VEVENT",
            f"UID:life-inbox-task-{task['id']}@life-inbox.local",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{_compact(start)}",
            f"DTEND;VALUE=DATE:{_compact(start + timedelta(days=1))}",
            f"SUMMARY:{_escape(summary)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
