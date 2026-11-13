import json
import logging
import os
import re

from app.schemas import AnalysisResult


MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
logger = logging.getLogger(__name__)


def extract_json_object(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output")
    return json.loads(raw[start:end + 1])


def priority_for_text(text: str) -> str:
    lowered = text.lower()

    high_markers = [
        "today", "tomorrow", "urgent", "asap", "due", "before friday",
        "before thursday", "expires", "deadline"
    ]
    medium_markers = [
        "this week", "weekend", "next week", "follow up", "remember",
        "need to", "appointment", "renew"
    ]

    if any(x in lowered for x in high_markers):
        return "High"
    if any(x in lowered for x in medium_markers):
        return "Medium"
    return "Low"


def bucket_for_text(text: str) -> str:
    lowered = text.lower()

    rules = [
        ("Work", ["team", "meeting", "architecture", "recruiter", "finance", "interview", "document"]),
        ("Money & Admin", ["bill", "tax", "insurance", "domain", "property tax", "reimbursement", "ca "]),
        ("Learning", ["read", "watch", "lecture", "article", "learn", "vector database", "prompt injection"]),
        ("Shopping & Errands", ["buy", "groceries", "pick up", "order", "dry cleaning"]),
        ("Health", ["dentist", "workout", "health"]),
        ("Travel", ["trip", "travel", "hotel", "jaipur"]),
        ("Ideas", ["idea", "build", "app", "startup", "product"]),
        ("People", ["call", "ask", "rohan", "papa", "mom"]),
    ]

    for name, markers in rules:
        if any(marker in lowered for marker in markers):
            return name
    return "Personal / Reference"


def _tags_for_text(text: str) -> list[str]:
    lowered = text.lower()
    tags = []
    tag_rules = [
        ("urgent", ["today", "tomorrow", "urgent", "asap", "deadline"]),
        ("errand", ["buy", "pick up", "order", "groceries"]),
        ("follow-up", ["call", "ask", "follow up", "email"]),
        ("learning", ["read", "watch", "learn", "article"]),
        ("money", ["bill", "tax", "pay", "insurance"]),
    ]
    for tag, markers in tag_rules:
        if any(marker in lowered for marker in markers):
            tags.append(tag)
    return tags


def _extract_timing(text: str) -> str | None:
    # Keep the exact phrase for the task, then normalize it in the attention
    # layer.  This covers explicit dates ("Oct 18" / "October 18") as well
    # as relative phrases while remaining deterministic without an API key.
    from app.attention.dates import timing_phrase_from_text

    return timing_phrase_from_text(text)


def _split_action_tasks(text: str, note_id: int, priority: str) -> list[dict]:
    """One source may yield multiple durable tasks when sentences look actionable."""
    action_markers = [
        "call", "buy", "send", "ask", "finish", "submit", "pay", "book",
        "pick up", "prepare", "renew", "follow up", "need to", "remember to",
        "research", "look into", "order",
    ]
    action_pattern = "|".join(
        sorted((re.escape(marker) for marker in action_markers), key=len, reverse=True)
    )
    # Bullets, new lines, semicolons and a comma/"and" before another action
    # are common ways of pasting many tasks into one capture.  Only split on
    # commas when another known action follows, so ordinary prose stays intact.
    chunks = [
        part.strip(" -•\t")
        for part in re.split(
            rf"(?:[.!?;\n]+|,\s*(?=(?:and\s+)?(?:{action_pattern})\b)|\s+and\s+(?=(?:{action_pattern})\b))",
            text,
            flags=re.I,
        )
        if part and part.strip(" -•\t")
    ]
    todos = []
    for chunk in chunks:
        if any(marker in chunk.lower() for marker in action_markers):
            todos.append(
                {
                    "task": chunk,
                    "priority": priority_for_text(chunk),
                    "source_note_ids": [note_id],
                    "when": _extract_timing(chunk) or _extract_timing(text),
                }
            )
    if not todos and any(marker in text.lower() for marker in action_markers):
        todos.append(
            {
                "task": text,
                "priority": priority,
                "source_note_ids": [note_id],
                "when": _extract_timing(text),
            }
        )
    return todos


def fallback_analyze(notes: list[dict]) -> dict:
    """Deterministic fallback so the demo still works if the API is unavailable."""
    buckets = {}
    todos = []
    priority_view = {"High": [], "Medium": [], "Low": []}

    for note in notes:
        text = note["text"]
        bucket = bucket_for_text(text)
        priority = priority_for_text(text)
        title = text[:72] + ("..." if len(text) > 72 else "")
        tags = _tags_for_text(text)

        item = {
            "id": note["id"],
            "title": title,
            "priority": priority,
            "tags": tags,
            "rationale": (
                f"Matched topic “{bucket}” from keywords in the note."
            ),
        }

        buckets.setdefault(bucket, []).append(item)
        priority_view[priority].append({"id": note["id"], "title": title})
        todos.extend(_split_action_tasks(text, note["id"], priority))

    return {
        "buckets": [
            {"name": name, "notes": items}
            for name, items in buckets.items()
        ],
        "todos": todos,
        "priority_view": priority_view,
        "mode": "fallback_no_api_call",
    }


def validate_analysis_result(result: dict, notes: list[dict]) -> dict:
    validated = AnalysisResult.model_validate(result)
    validated.validate_for_item_ids({note["id"] for note in notes})
    return validated.model_dump()


def analyze_inbox_with_openai(notes: list[dict]) -> dict:
    if not notes:
        return validate_analysis_result(
            {
                "buckets": [],
                "todos": [],
                "priority_view": {"High": [], "Medium": [], "Low": []},
                "mode": "empty_inbox",
            },
            notes,
        )

    from app.ai_provider import complete_text, resolve_ai_config

    ai_config = resolve_ai_config()
    if ai_config is None:
        return validate_analysis_result(fallback_analyze(notes), notes)

    try:
        client = None
        if ai_config.kind == "server_openai":
            from openai import OpenAI
            client = OpenAI()

        compact_notes = [{"id": n["id"], "text": n["text"]} for n in notes]

        prompt = f"""
You are the organization engine for a personal Life Inbox.

Analyze ALL saved notes together and turn the messy inbox into a practical dashboard.

Return ONLY valid JSON in exactly this shape:

{{
  "buckets": [
    {{
      "name": "short useful category name",
      "notes": [
        {{
          "id": 1,
          "title": "concise title preserving the note's meaning",
          "priority": "High",
          "tags": ["follow-up"],
          "rationale": "short reason this note belongs in the bucket"
        }}
      ]
    }}
  ],
  "todos": [
    {{
      "task": "concrete action",
      "priority": "High",
      "source_note_ids": [1],
      "when": "timing mentioned in the note, or null"
    }}
  ],
  "priority_view": {{
    "High": [
      {{"id": 1, "title": "concise title"}}
    ],
    "Medium": [],
    "Low": []
  }}
}}

Rules:
1. Organize the full inbox, not each note independently.
2. Every saved note must appear in exactly one bucket.
3. Prefer existing topic/bucket names when they fit: Work, Money & Admin,
   Learning, Shopping & Errands, Health, Travel, Ideas, People,
   Personal / Reference. Invent a new bucket only when genuinely clearer.
4. Priority must be one of High, Medium, Low.
5. High priority means explicit urgency, a near deadline, or a clearly time-sensitive obligation.
6. Medium means actionable but not immediately urgent.
7. Low means reference material, someday ideas, or non-urgent items.
8. Extract ToDos only when the note contains an explicit or strongly implied action.
9. A note can produce multiple ToDos if it genuinely contains multiple actions.
10. Do not invent dates, deadlines, people, facts, or actions.
11. Preserve relative timing exactly when present, for example "tomorrow" or "this weekend".
12. Keep titles and ToDos short and concrete. No motivational language, commentary, or prose outside the JSON.
13. priority_view should include every note once, grouped by priority.
14. Include a short rationale and a few useful tags for each note.

Saved notes:
{json.dumps(compact_notes, ensure_ascii=False)}
"""

        if client is not None:
            response = client.responses.create(model=MODEL, input=prompt)
            raw_text = response.output_text
            mode = "openai"
        else:
            raw_text = complete_text(prompt, ai_config)
            mode = "ai_provider"
        result = extract_json_object(raw_text)
        result["mode"] = mode
        return validate_analysis_result(result, notes)

    except Exception:
        logger.exception("AI analysis failed; using deterministic fallback")
        fallback = fallback_analyze(notes)
        fallback["mode"] = "fallback_after_api_error"
        return validate_analysis_result(fallback, notes)
