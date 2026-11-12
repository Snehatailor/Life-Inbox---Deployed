"""Weekly review: stored facts plus a short plain-language summary.

The numbers always come from ``get_weekly_review`` (the database).  A model
may only reword those facts into a friendlier sentence when
``OPENAI_API_KEY`` is set; any failure falls back to the rule-based sentence.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

REVIEW_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

_TYPE_LABELS = {
    "text": ("note", "notes"),
    "url": ("link", "links"),
    "pdf": ("PDF", "PDFs"),
    "image": ("image", "images"),
    "voice": ("voice note", "voice notes"),
}


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def rule_based_summary(facts: dict) -> str:
    total = facts["captured"]["total"]
    if total == 0 and not facts["completed_tasks"]:
        return "A quiet week: nothing new was captured and no tasks were completed."

    parts = []
    by_type = facts["captured"]["by_type"]
    if total:
        breakdown = ", ".join(
            _plural(count, *_TYPE_LABELS.get(kind, (kind, kind)))
            for kind, count in sorted(by_type.items(), key=lambda pair: -pair[1])
        )
        parts.append(f"You captured {_plural(total, 'item', 'items')} ({breakdown}).")
    else:
        parts.append("You captured nothing new.")

    done = len(facts["completed_tasks"])
    parts.append(f"You completed {_plural(done, 'task', 'tasks')}.")

    stats = facts.get("stats") or {}
    if stats.get("goal_days"):
        parts.append(
            f"You hit your daily goal on {stats['goal_days']} of the last 7 days."
        )
    if stats.get("habits_kept"):
        parts.append(f"You kept {_plural(stats['habits_kept'], 'habit', 'habits')} going.")

    if facts["top_topics"]:
        top = facts["top_topics"][0]
        parts.append(f"Most of it was about {top['name']}.")

    if facts["untouched_count"]:
        parts.append(
            f"{_plural(facts['untouched_count'], 'item is', 'items are')} "
            "still waiting to be organized."
        )
    return " ".join(parts)


def _model_summary(facts: dict) -> Optional[str]:
    """Ask the model to reword the facts. Returns None if it gives nothing usable."""
    payload = {
        "captured": facts["captured"],
        "completed_tasks": [task["text"][:120] for task in facts["completed_tasks"][:10]],
        "open_task_count": facts["open_task_count"],
        "top_topics": facts["top_topics"],
        "untouched_count": facts["untouched_count"],
        "goal_days_of_7": (facts.get("stats") or {}).get("goal_days"),
        "streak_days": (facts.get("stats") or {}).get("streak"),
        "habits_kept": (facts.get("stats") or {}).get("habits_kept"),
    }
    prompt = (
        "Write a friendly two-sentence weekly review for a personal inbox app. "
        "Use only the facts below. Do not invent numbers, tasks or topics. "
        "Plain text, no markdown.\n\n"
        f"Facts (JSON):\n{json.dumps(payload, ensure_ascii=False)}"
    )

    from openai import OpenAI

    client = OpenAI()
    response = client.responses.create(model=REVIEW_MODEL, input=prompt)
    text = getattr(response, "output_text", None)
    if not isinstance(text, str) or not text.strip():
        return None
    return text.strip()[:600]


def build_weekly_review(now: Optional[datetime] = None) -> dict:
    from app.database import get_weekly_review

    facts = get_weekly_review(now=now)
    summary = rule_based_summary(facts)
    summary_kind = "rule_based"

    if os.getenv("OPENAI_API_KEY", "").strip():
        try:
            generated = _model_summary(facts)
            if generated:
                summary = generated
                summary_kind = "model_generated"
        except Exception:
            logger.exception("Weekly review model summary failed; using rule-based summary")

    return {**facts, "summary": summary, "summary_kind": summary_kind}
