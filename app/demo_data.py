"""Load (and later remove) sample data that exercises every feature.

Everything is created for the signed-in account only, through the same
helpers the app uses. The ids of every created row are saved in
user_settings.demo_data_json so "Remove demo data" deletes exactly those rows
and never touches the person's own notes, tasks, team or busy times.
"""

from __future__ import annotations

import io
import json
import wave
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select

from app import database as db
from app.attention.dates import configured_timezone, today_in_configured_tz


class DemoDataError(ValueError):
    """Shown to the person as-is."""


DEMO_NOTES = [
    ("Pay the electricity bill before Friday and renew car insurance.", "Finance"),
    ("Book train tickets and a hotel for the Jaipur trip next month.", "Travel"),
    ("Read the article on prompt injection this weekend.", "Study"),
    ("Dentist checkup on Monday at 10am.", "Health"),
    ("Buy groceries: milk, eggs, coffee and basil.", "Shopping"),
    ("Idea: a habit tracker app that rewards streaks with pets.", "Work"),
    ("Call mom about Rohan's birthday dinner on Saturday.", "Social"),
    ("Finish the quarterly report draft for the team meeting.", "Work"),
]

DEMO_URL = {
    "url": "https://en.wikipedia.org/wiki/Getting_Things_Done",
    "title": "Getting Things Done (Wikipedia)",
    "text": (
        "Getting Things Done is a time-management method by David Allen. "
        "Capture everything in an inbox, clarify what each item means, organize "
        "it into lists, reflect weekly, and engage with the next action."
    ),
}

DEMO_PDF_TEXT = [
    "Apartment lease renewal",
    "Rent increases to 32,000 per month from 1 January.",
    "Sign and return the renewal form by 20 December.",
]

DEMO_VOICE_TRANSCRIPT = (
    "Reminder to myself: pick up the dry cleaning tomorrow evening and "
    "email the landlord about the kitchen tap."
)

DEMO_IMAGE_TEXT = "Cafe Mocha receipt - Total 640 - Card ending 4242"


def _ids(rows) -> list[int]:
    return [int(row["id"]) for row in rows if row and row.get("id") is not None]


def _minimal_pdf(lines: list[str]) -> bytes:
    """A small, valid one-page PDF with the given text lines."""
    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    stream_lines = ["BT", "/F1 14 Tf", "72 760 Td", "18 TL"]
    for line in lines:
        stream_lines.append(f"({esc(line)}) Tj T*")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def _receipt_png() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (480, 320), (250, 248, 242))
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 20, 460, 300], outline=(60, 60, 60), width=2)
    draw.text((40, 40), "CAFE MOCHA", fill=(20, 20, 20))
    draw.text((40, 90), "Cappuccino x2 ........ 420", fill=(40, 40, 40))
    draw.text((40, 120), "Croissant ............ 220", fill=(40, 40, 40))
    draw.text((40, 180), "TOTAL ................ 640", fill=(0, 0, 0))
    draw.text((40, 240), "Card ending 4242 - Thank you!", fill=(80, 80, 80))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _silent_wav(seconds: float = 1.0, rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\x00\x00" * int(seconds * rate))
    return buffer.getvalue()


def _local_slot_utc(day, hour: int, minutes: int = 30) -> tuple[str, str]:
    tz = configured_timezone()
    start = datetime.combine(day, time(hour, 0), tzinfo=tz)
    end = start + timedelta(minutes=minutes)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


def demo_status(owner_id: int) -> dict:
    raw = db.get_user_settings(owner_id).get("demo_data_json")
    if not raw:
        return {"loaded": False}
    try:
        record = json.loads(raw)
    except ValueError:
        return {"loaded": False}
    return {
        "loaded": True,
        "loaded_at": record.get("loaded_at"),
        "counts": {key: len(value) for key, value in record.items() if isinstance(value, list)},
    }


def load_demo_data(owner_id: int) -> dict:
    if demo_status(owner_id)["loaded"]:
        raise DemoDataError("Demo data is already loaded. Remove it first to load a fresh set.")

    from app.capture.image_extract import make_thumbnail_bytes
    from app.capture.storage import (
        store_audio_bytes,
        store_image_bytes,
        store_pdf_bytes,
        store_thumbnail_bytes,
    )
    from app.organizer import fallback_analyze, validate_analysis_result

    today = today_in_configured_tz()
    record: dict = {
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "items": [], "tasks": [], "point_events": [], "purchases": [],
        "busy_blocks": [], "teams": [], "topics": [],
    }
    had_items = bool(db.list_items_from_db())
    tasks_before = {task["id"] for task in db.list_tasks_from_db(status_filter="all")}

    # 1. Captures of every kind.
    for text, domain in DEMO_NOTES:
        item = db.add_item_to_db(text)
        record["items"].append(item["id"])
        db.set_item_domain(item["id"], domain)

    url_item = db.add_url_item_to_db(DEMO_URL["url"])
    db.complete_url_item_processing(
        url_item["id"], title=DEMO_URL["title"], raw_text=DEMO_URL["text"],
        mime_type="text/html", final_url=DEMO_URL["url"],
    )
    record["items"].append(url_item["id"])

    pdf_path = store_pdf_bytes(_minimal_pdf(DEMO_PDF_TEXT))
    pdf_item = db.add_pdf_item_to_db("lease-renewal.pdf", pdf_path, "application/pdf")
    pdf_text = "\n".join(DEMO_PDF_TEXT)
    db.complete_pdf_item_processing(
        pdf_item["id"], title="Lease renewal", raw_text=pdf_text,
        extracted_text=pdf_text, mime_type="application/pdf",
    )
    record["items"].append(pdf_item["id"])

    png = _receipt_png()
    image_path = store_image_bytes(png, ".png")
    store_thumbnail_bytes(image_path, make_thumbnail_bytes(png))
    image_item = db.add_image_item_to_db("cafe-receipt.png", image_path, "image/png")
    db.complete_image_item_processing(
        image_item["id"], title="Cafe receipt", raw_text=DEMO_IMAGE_TEXT,
        extracted_text=DEMO_IMAGE_TEXT,
        ai_description="A printed cafe receipt with two coffees and a croissant (demo).",
        mime_type="image/png",
    )
    record["items"].append(image_item["id"])

    voice_path = store_audio_bytes(_silent_wav(), ".wav")
    voice_item = db.add_voice_item_to_db("reminder.wav", voice_path, "audio/wav")
    db.complete_voice_item_processing(
        voice_item["id"], title="Voice reminder", raw_text=DEMO_VOICE_TRANSCRIPT,
        extracted_text=DEMO_VOICE_TRANSCRIPT, mime_type="audio/wav",
    )
    record["items"].append(voice_item["id"])

    # 2. Organize, but only a fresh inbox, so real notes are never reshuffled.
    if not had_items:
        run_id = db.start_analysis_run()
        notes = db.list_notes_from_db()
        db.complete_analysis_run(run_id, validate_analysis_result(fallback_analyze(notes), notes))

    # 3. Tasks with every kind of date.
    def quick(text, priority, offset_days, chosen=True):
        due = (today + timedelta(days=offset_days)).isoformat() if offset_days is not None else None
        task = db.create_quick_task(text, priority, due, "high" if due else None, priority_chosen=chosen)
        return task["id"]

    overdue = quick("Submit the expense reimbursement form", "High", -2)
    due_today = quick("Pay the water bill", "Medium", 0)
    tomorrow = quick("Prepare slides for Monday's client call", "High", 1)
    upcoming = quick("Renew passport application", "Medium", 5)
    later = quick("Plan the weekend hike", "Low", 9)
    unscheduled = quick("Sort out the bookshelf", "Low", None)
    done_a = quick("Water the plants", "Low", 0)
    done_b = quick("Reply to the recruiter email", "Medium", 0)
    binned = quick("Return the library book", "Low", -1)
    # Habits: recurring tasks. "Water the plants" repeats daily and is completed
    # below, so its next copy shows up for tomorrow.
    revise = quick("Revise DSA for 30 minutes", "Medium", 0)
    gym = quick("Gym", "High", 0)
    db.update_task_fields(revise, repeat_rule="daily", set_repeat=True)
    db.update_task_fields(gym, repeat_rule="days:mon,wed,fri", set_repeat=True)
    db.update_task_fields(done_a, repeat_rule="daily", set_repeat=True)

    db.set_task_status(done_a, "completed")
    db.set_task_status(done_b, "completed")
    db.set_task_status(binned, "completed")
    db.set_task_binned(binned, True)
    # Snoozed twice: the Procrastination Radar flags it.
    db.snooze_task_in_db(overdue, (today + timedelta(days=1)).isoformat())
    db.snooze_task_in_db(overdue, (today + timedelta(days=1)).isoformat())
    start, end = _local_slot_utc(today + timedelta(days=1), 10)
    db.set_task_slot(tomorrow, start, end)

    tasks_after = db.list_tasks_from_db(status_filter="all")
    demo_items = set(record["items"])
    demo_task_ids = {overdue, due_today, tomorrow, upcoming, later, unscheduled, done_a, done_b, binned, revise, gym}
    demo_task_ids |= {task["next_task_id"] for task in tasks_after if task["id"] in demo_task_ids and task.get("next_task_id")}
    created = [
        task for task in tasks_after
        if task["id"] not in tasks_before
        and (
            task["id"] in demo_task_ids
            or set(task.get("source_item_ids") or []) & demo_items
        )
    ]
    record["tasks"] = sorted({task["id"] for task in created})

    with db.SessionLocal() as session:
        # 4. A six-day streak of past points (today's come from completed tasks).
        now_iso = datetime.now(timezone.utc).isoformat()
        for days_ago, points in [(6, 110), (5, 120), (4, 105), (3, 130), (2, 115), (1, 140)]:
            event = db.PointEventRecord(
                owner_user_id=owner_id, task_id=None, points=points,
                day=(today - timedelta(days=days_ago)).isoformat(), created_at=now_iso,
            )
            session.add(event)
            session.flush()
            record["point_events"].append(event.id)
        record["point_events"] += [
            row.id for row in session.scalars(
                select(db.PointEventRecord).where(
                    db.PointEventRecord.owner_user_id == owner_id,
                    db.PointEventRecord.task_id.in_(record["tasks"] or [-1]),
                )
            )
        ]
        session.commit()

    # 5. Spend coins on a second pet.
    purchases_before = _purchase_ids(owner_id)
    try:
        db.buy_pet("dog")
        db.select_pet("dog")
    except ValueError:
        pass
    record["purchases"] = sorted(_purchase_ids(owner_id) - purchases_before)

    # 6. Busy calendar times (only if none were imported) for "Find time".
    if not db.list_busy_blocks():
        blocks = []
        for offset, hour, summary in [(1, 9, "Stand-up"), (1, 14, "Design review"), (2, 11, "Gym")]:
            start, end = _local_slot_utc(today + timedelta(days=offset), hour, 60)
            blocks.append({"starts_at": start, "ends_at": end, "summary": f"{summary} (demo)"})
        db.replace_busy_blocks(blocks)
        with db.SessionLocal() as session:
            record["busy_blocks"] = list(session.scalars(
                select(db.BusyBlockRecord.id).where(db.BusyBlockRecord.owner_user_id == owner_id)
            ))

    # 7. A team for the weekly leaderboard (only if not already in one).
    try:
        team = db.create_team("Demo Squad", True)
        team_id = team.get("id") or (team.get("team") or {}).get("id")
        if team_id:
            record["teams"].append(team_id)
    except ValueError:
        pass

    # 8. A topic of your own.
    try:
        topic = db.create_topic_in_db("Home projects (demo)", "Sample topic from demo data")
        record["topics"].append(topic["id"])
    except ValueError:
        pass

    db.update_user_settings(owner_id, demo_data_json=json.dumps(record))
    return demo_status(owner_id)


def _purchase_ids(owner_id: int) -> set[int]:
    with db.SessionLocal() as session:
        return set(session.scalars(
            select(db.ShopPurchaseRecord.id).where(db.ShopPurchaseRecord.owner_user_id == owner_id)
        ))


def remove_demo_data(owner_id: int) -> dict:
    raw = db.get_user_settings(owner_id).get("demo_data_json")
    if not raw:
        return {"loaded": False}
    record = json.loads(raw)

    for item_id in record.get("items", []):
        db.delete_item_from_db(item_id)

    with db.SessionLocal() as session:
        owned = lambda model, column="owner_user_id": getattr(model, column) == owner_id  # noqa: E731
        task_ids = record.get("tasks") or []
        if task_ids:
            session.execute(delete(db.TaskEventRecord).where(
                db.TaskEventRecord.task_id.in_(task_ids), owned(db.TaskEventRecord)))
            session.execute(delete(db.CalendarActionReceiptRecord).where(
                db.CalendarActionReceiptRecord.task_id.in_(task_ids)
                & db.CalendarActionReceiptRecord.task_id.in_(
                    select(db.TaskRecord.id).where(owned(db.TaskRecord)))))
            session.execute(delete(db.TaskSourceItemRecord).where(
                db.TaskSourceItemRecord.task_id.in_(
                    select(db.TaskRecord.id).where(db.TaskRecord.id.in_(task_ids), owned(db.TaskRecord)))))
            session.execute(delete(db.PointEventRecord).where(
                db.PointEventRecord.task_id.in_(task_ids), owned(db.PointEventRecord)))
            session.execute(delete(db.TaskRecord).where(
                db.TaskRecord.id.in_(task_ids), owned(db.TaskRecord)))
        for ids, model in [
            (record.get("point_events"), db.PointEventRecord),
            (record.get("purchases"), db.ShopPurchaseRecord),
            (record.get("busy_blocks"), db.BusyBlockRecord),
        ]:
            if ids:
                session.execute(delete(model).where(model.id.in_(ids), owned(model)))
        if record.get("purchases"):
            pet = session.get(db.PetSettingsRecord, owner_id)
            if pet is not None and pet.active_pet == "dog":
                pet.active_pet = "cat"
        for team_id in record.get("teams") or []:
            session.execute(delete(db.TeamMemberRecord).where(
                db.TeamMemberRecord.team_id == team_id, db.TeamMemberRecord.user_id == owner_id))
            remaining = session.scalar(select(db.TeamMemberRecord.id).where(
                db.TeamMemberRecord.team_id == team_id))
            if remaining is None:
                session.execute(delete(db.TeamRecord).where(
                    db.TeamRecord.id == team_id, db.TeamRecord.created_by == owner_id))
        if record.get("topics"):
            session.execute(delete(db.TopicRecord).where(
                db.TopicRecord.id.in_(record["topics"]), owned(db.TopicRecord)))
        session.commit()

    db.update_user_settings(owner_id, demo_data_json=None)
    return {"loaded": False}
