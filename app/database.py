import hashlib
import json
import os
import re
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_current_owner_id: ContextVar[Optional[int]] = ContextVar(
    "life_inbox_owner_id", default=None
)

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    event,
    func,
    or_,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.attention.dates import today_in_configured_tz
from app.game.gcal import google_event_url
from app.sorting import DOMAINS, UNSORTED, detect_domain, detect_format
from app.game.progress import build_game_summary
from app.game.scoring import (
    points_for,
    PRIORITY_POINTS,
    days_left,
    days_left_label,
    default_due_offset,
    urgency,
)
from app.capture.pipeline import (
    ANALYZABLE_STATUSES,
    ANALYZABLE_TYPES,
    STATUS_CAPTURED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_READY,
    IMAGE_ITEM_TYPE,
    PDF_ITEM_TYPE,
    URL_ITEM_TYPE,
    VOICE_ITEM_TYPE,
)
from app.capture.storage import delete_stored_file
from app.similarity import find_item_relations


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "life_inbox.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DB_PATH}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
AUTO_CREATE_TABLES = os.getenv(
    "LIFE_INBOX_AUTO_CREATE_TABLES", ""
).strip().lower() in {"1", "true", "yes"}


def _connect_args(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine = create_engine(DATABASE_URL, connect_args=_connect_args(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite only enforces CASCADE when foreign_keys pragma is on."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


TEXT_ITEM_TYPE = "text"
READY_STATUS = STATUS_READY
ANALYSIS_RUNNING = "running"
ANALYSIS_SUCCEEDED = "succeeded"
ANALYSIS_FAILED = "failed"
TASK_OPEN = "open"
TASK_COMPLETED = "completed"
TASK_DISMISSED = "dismissed"
TASK_STATUSES = {TASK_OPEN, TASK_COMPLETED, TASK_DISMISSED}
DEFAULT_OWNER_EMAIL = "local@life-inbox.local"


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(Text, nullable=False)
    display_name = Column(Text, nullable=False)
    auth_provider = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)


class InboxItemRecord(Base):
    __tablename__ = "inbox_items"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_type = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    original_filename = Column(Text, nullable=True)
    mime_type = Column(Text, nullable=True)
    processing_status = Column(Text, nullable=False)
    error_message = Column(Text, nullable=True)
    storage_path = Column(Text, nullable=True)
    extracted_text = Column(Text, nullable=True)
    ai_description = Column(Text, nullable=True)
    domain = Column(Text, nullable=True)
    domain_source = Column(Text, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=True)


class AnalysisRunRecord(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(Text, nullable=False)
    completed_at = Column(Text, nullable=True)
    status = Column(Text, nullable=False)
    mode = Column(Text, nullable=False)
    result_json = Column(Text, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)


class TopicRecord(Base):
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("name", "owner_user_id", name="uq_topics_name_owner"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    archived = Column(Integer, nullable=False, default=0)


class ItemInsightRecord(Base):
    __tablename__ = "item_insights"

    item_id = Column(
        Integer,
        ForeignKey("inbox_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    analysis_run_id = Column(
        Integer,
        ForeignKey("analysis_runs.id"),
        nullable=False,
    )
    category = Column(Text, nullable=False)
    concise_title = Column(Text, nullable=False)
    priority = Column(Text, nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=True)
    tags_json = Column(Text, nullable=True)
    rationale = Column(Text, nullable=True)
    user_title = Column(Text, nullable=True)
    user_topic_id = Column(Integer, ForeignKey("topics.id"), nullable=True)
    user_priority = Column(Text, nullable=True)
    user_tags_json = Column(Text, nullable=True)
    needs_review = Column(Integer, nullable=False, default=0)
    updated_at = Column(Text, nullable=False)


class ItemRelationRecord(Base):
    __tablename__ = "item_relations"
    __table_args__ = (
        UniqueConstraint(
            "item_id_a",
            "item_id_b",
            "relation_type",
            name="uq_item_relations_pair_type",
        ),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id_a = Column(
        Integer,
        ForeignKey("inbox_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id_b = Column(
        Integer,
        ForeignKey("inbox_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type = Column(Text, nullable=False)
    score = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    dismissed = Column(Integer, nullable=False, default=0)


class TaskRecord(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('High', 'Medium', 'Low')",
            name="ck_tasks_priority",
        ),
        CheckConstraint(
            "status IN ('open', 'completed', 'dismissed')",
            name="ck_tasks_status",
        ),
        UniqueConstraint("dedup_key"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    priority = Column(Text, nullable=False)
    timing_text = Column(Text, nullable=True)
    ai_timing_text = Column(Text, nullable=True)
    timing_confirmed = Column(Integer, nullable=False, default=0)
    due_on = Column(Text, nullable=True)
    due_confidence = Column(Text, nullable=True)
    snoozed_until = Column(Text, nullable=True)
    reminder_at = Column(Text, nullable=True)
    status = Column(Text, nullable=False)
    dedup_key = Column(Text, nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_at = Column(Text, nullable=True)
    points_awarded = Column(Integer, nullable=True)
    binned_at = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)


class PointEventRecord(Base):
    __tablename__ = "point_events"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_id = Column(
        Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    points = Column(Integer, nullable=False)
    day = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)


class CalendarActionReceiptRecord(Base):
    __tablename__ = "calendar_action_receipts"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(Text, nullable=False)
    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)


class TaskSourceItemRecord(Base):
    __tablename__ = "task_source_items"

    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    item_id = Column(
        Integer,
        ForeignKey("inbox_items.id", ondelete="CASCADE"),
        primary_key=True,
    )


DEFAULT_TOPIC_NAMES = (
    "Work",
    "Money & Admin",
    "Learning",
    "Shopping & Errands",
    "Health",
    "Travel",
    "Ideas",
    "People",
    "Personal / Reference",
)


def set_current_owner_id(owner_user_id: Optional[int]) -> None:
    _current_owner_id.set(owner_user_id)


def get_current_owner_id() -> Optional[int]:
    return _current_owner_id.get()


def _user_to_dict(user: UserRecord) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "auth_provider": user.auth_provider,
        "created_at": user.created_at,
    }


def get_user_by_id(user_id: int) -> Optional[dict]:
    with SessionLocal() as session:
        user = session.get(UserRecord, user_id)
        return _user_to_dict(user) if user else None


def get_user_by_email(email: str) -> Optional[dict]:
    with SessionLocal() as session:
        user = session.scalar(
            select(UserRecord).where(UserRecord.email == email.strip().lower())
        )
        return _user_to_dict(user) if user else None


def ensure_user(
    *,
    email: str,
    display_name: str,
    auth_provider: str,
) -> dict:
    cleaned = email.strip().lower()
    with SessionLocal() as session:
        user = session.scalar(
            select(UserRecord).where(UserRecord.email == cleaned)
        )
        if user is None:
            user = UserRecord(
                email=cleaned,
                display_name=display_name.strip() or cleaned,
                auth_provider=auth_provider,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(user)
            session.commit()
        return _user_to_dict(user)


def get_or_create_default_owner_id() -> int:
    user = ensure_user(
        email=DEFAULT_OWNER_EMAIL,
        display_name="Local Owner",
        auth_provider="local",
    )
    return user["id"]


class OwnerRequiredError(PermissionError):
    """No owner is bound to the current request; user data is off limits."""


def require_owner_id() -> int:
    """Return the bound owner. Never falls back to Local Owner.

    Only the HTTP middleware decides when Local Owner applies (local mode with
    no session). Everywhere else, a missing owner fails closed.
    """
    owner = get_current_owner_id()
    if owner is None:
        raise OwnerRequiredError("Authentication required.")
    return owner


def _owned_item(session, item_id: int, owner_id: int) -> Optional["InboxItemRecord"]:
    item = session.get(InboxItemRecord, item_id)
    if item is None or item.owner_user_id != owner_id:
        return None
    return item


def _owned_task(session, task_id: int, owner_id: int) -> Optional["TaskRecord"]:
    task = session.get(TaskRecord, task_id)
    if task is None or task.owner_user_id != owner_id:
        return None
    return task


def _owned_topic(session, topic_id: int, owner_id: int) -> Optional["TopicRecord"]:
    topic = session.get(TopicRecord, topic_id)
    if topic is None or topic.owner_user_id != owner_id:
        return None
    return topic


def _owned_item_ids(owner_id: int):
    return select(InboxItemRecord.id).where(
        InboxItemRecord.owner_user_id == owner_id
    )


def _owned_topic_ids(session, owner_id: int) -> set[int]:
    return set(
        session.scalars(
            select(TopicRecord.id).where(TopicRecord.owner_user_id == owner_id)
        )
    )


def ensure_default_topics(session, owner_user_id: Optional[int] = None) -> None:
    """Seed missing default topics for one owner.

    A name already exists only when this owner has it. Another user's Work
    is not reused and does not block this owner's copy.
    """
    owner = owner_user_id if owner_user_id is not None else require_owner_id()
    existing_names = set(
        session.scalars(
            select(TopicRecord.name).where(TopicRecord.owner_user_id == owner)
        )
    )
    missing = [
        name for name in DEFAULT_TOPIC_NAMES if name not in existing_names
    ]
    if not missing:
        return
    now = datetime.now(timezone.utc).isoformat()
    for name in missing:
        session.add(
            TopicRecord(
                name=name,
                description=None,
                owner_user_id=owner,
                created_at=now,
                updated_at=now,
                archived=0,
            )
        )
    session.flush()


def init_db():
    """Prepare the DB connection.

    Alembic owns schema evolution. Table auto-creation is opt-in for isolated
    automated tests via LIFE_INBOX_AUTO_CREATE_TABLES=1.
    """
    if AUTO_CREATE_TABLES:
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            owner = ensure_user(
                email=DEFAULT_OWNER_EMAIL,
                display_name="Local Owner",
                auth_provider="local",
            )
            ensure_default_topics(session, owner_user_id=owner["id"])
            session.commit()


def _item_to_dict(item: InboxItemRecord) -> dict:
    if item.domain and item.domain_source == "user":
        domain, domain_confidence, domain_source = item.domain, "user", "user"
    else:
        domain, domain_confidence = detect_domain(
            item.title,
            item.original_filename,
            item.source_url,
            item.raw_text,
            item.extracted_text,
        )
        domain_source = "auto"
    return {
        "file_format": detect_format(
            item.item_type, item.original_filename, item.mime_type
        ),
        "domain": domain,
        "domain_confidence": domain_confidence,
        "domain_source": domain_source,
        "id": item.id,
        "item_type": item.item_type,
        "title": item.title,
        "raw_text": item.raw_text,
        "source_url": item.source_url,
        "original_filename": item.original_filename,
        "mime_type": item.mime_type,
        "processing_status": item.processing_status,
        "error_message": item.error_message,
        "storage_path": item.storage_path,
        "extracted_text": item.extracted_text,
        "ai_description": item.ai_description,
        "owner_user_id": item.owner_user_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def add_item_to_db(raw_text: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=TEXT_ITEM_TYPE,
            raw_text=raw_text,
            processing_status=READY_STATUS,
            owner_user_id=owner_id,
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def list_items_from_db(
    search: Optional[str] = None,
    item_type: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    processing_status: Optional[str] = None,
    limit: Optional[int] = 100,
    offset: int = 0,
) -> list[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        statement = select(InboxItemRecord).where(
            InboxItemRecord.owner_user_id == owner_id
        )

        if category or priority:
            statement = statement.join(
                ItemInsightRecord,
                ItemInsightRecord.item_id == InboxItemRecord.id,
            )

        search_text = (search or "").strip()
        if search_text:
            statement = statement.where(
                or_(
                    InboxItemRecord.raw_text.icontains(
                        search_text,
                        autoescape=True,
                    ),
                    InboxItemRecord.title.icontains(
                        search_text,
                        autoescape=True,
                    ),
                    InboxItemRecord.extracted_text.icontains(
                        search_text,
                        autoescape=True,
                    ),
                    InboxItemRecord.original_filename.icontains(
                        search_text,
                        autoescape=True,
                    ),
                )
            )
        if item_type:
            statement = statement.where(
                InboxItemRecord.item_type == item_type
            )
        if category:
            statement = statement.where(
                ItemInsightRecord.category == category
            )
        if priority:
            statement = statement.where(
                ItemInsightRecord.priority == priority
            )
        if processing_status:
            statement = statement.where(
                InboxItemRecord.processing_status == processing_status
            )

        statement = statement.order_by(InboxItemRecord.id.asc()).offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        items = session.scalars(statement).all()
        return [_item_to_dict(item) for item in items]


def compute_inbox_fingerprint(session=None) -> str:
    """Stable hash of current inbox content used to detect stale analysis."""
    owner_id = require_owner_id()

    def _fingerprint(active_session) -> str:
        items = active_session.scalars(
            select(InboxItemRecord)
            .where(InboxItemRecord.owner_user_id == owner_id)
            .order_by(InboxItemRecord.id.asc())
        ).all()
        payload = [
            [
                item.id,
                item.item_type,
                item.raw_text or "",
                item.title or "",
                item.source_url or "",
                item.processing_status,
                item.updated_at or item.created_at,
            ]
            for item in items
        ]
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    if session is not None:
        return _fingerprint(session)
    with SessionLocal() as owned_session:
        return _fingerprint(owned_session)


def update_item_in_db(item_id: int, raw_text: str) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None or item.item_type != TEXT_ITEM_TYPE:
            return None

        item.raw_text = raw_text
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def _remove_orphan_tasks(session, item_ids: list[int]) -> None:
    """Drop source links for deleted items and remove tasks with no sources."""
    if not item_ids:
        return

    affected_task_ids = session.scalars(
        select(TaskSourceItemRecord.task_id).where(
            TaskSourceItemRecord.item_id.in_(item_ids)
        )
    ).all()
    for link in session.scalars(
        select(TaskSourceItemRecord).where(
            TaskSourceItemRecord.item_id.in_(item_ids)
        )
    ).all():
        session.delete(link)
    session.flush()

    for task_id in sorted(set(affected_task_ids)):
        remaining = session.scalars(
            select(TaskSourceItemRecord.item_id).where(
                TaskSourceItemRecord.task_id == task_id
            )
        ).all()
        if remaining:
            task = session.get(TaskRecord, task_id)
            if task is not None:
                task.dedup_key = _task_dedup_key(list(remaining), task.text)
            continue
        task = session.get(TaskRecord, task_id)
        if task is not None:
            session.delete(task)


def delete_item_from_db(item_id: int) -> bool:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None:
            return False

        insight = session.get(ItemInsightRecord, item_id)
        if insight is not None:
            session.delete(insight)
        _remove_orphan_tasks(session, [item_id])
        storage_path = item.storage_path
        session.delete(item)
        session.commit()
        delete_stored_file(storage_path)
        return True


def _item_to_note(item: dict) -> dict:
    return {
        "id": item["id"],
        "text": item["raw_text"],
        "created_at": item["created_at"],
    }


def add_note_to_db(text: str) -> dict:
    return _item_to_note(add_item_to_db(text))


def list_notes_from_db() -> list[dict]:
    """Analyzable ready items exposed in the legacy note shape for the organizer."""
    notes = []
    for item in list_items_from_db(limit=None, offset=0):
        if item["item_type"] not in ANALYZABLE_TYPES:
            continue
        if item["processing_status"] not in ANALYZABLE_STATUSES:
            continue
        text = item.get("extracted_text") or item.get("raw_text")
        if not text:
            continue
        notes.append(
            {
                "id": item["id"],
                "text": text,
                "created_at": item["created_at"],
            }
        )
    return notes


def update_note_in_db(note_id: int, text: str) -> Optional[dict]:
    item = update_item_in_db(note_id, text)
    return _item_to_note(item) if item is not None else None


def delete_note_from_db(note_id: int) -> bool:
    return delete_item_from_db(note_id)


def start_analysis_run() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    owner_id = require_owner_id()
    with SessionLocal() as session:
        run = AnalysisRunRecord(
            started_at=started_at,
            status=ANALYSIS_RUNNING,
            mode="pending",
            owner_user_id=owner_id,
        )
        session.add(run)
        session.commit()
        return run.id


def _topic_id_by_name(session, name: str) -> Optional[int]:
    owner_id = require_owner_id()
    ensure_default_topics(session, owner_user_id=owner_id)
    topic = session.scalars(
        select(TopicRecord).where(
            TopicRecord.name == name,
            TopicRecord.owner_user_id == owner_id,
        )
    ).first()
    if topic is not None:
        return topic.id
    now = datetime.now(timezone.utc).isoformat()
    topic = TopicRecord(
        name=name,
        description="Created from AI organization",
        owner_user_id=owner_id,
        created_at=now,
        updated_at=now,
        archived=0,
    )
    session.add(topic)
    session.flush()
    return topic.id


def _normalize_task_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def complete_analysis_run(run_id: int, result: dict) -> dict:
    completed_at = datetime.now(timezone.utc).isoformat()
    owner_id = require_owner_id()
    with SessionLocal() as session:
        run = session.get(AnalysisRunRecord, run_id)
        if (
            run is None
            or run.status != ANALYSIS_RUNNING
            or run.owner_user_id != owner_id
        ):
            raise ValueError("Analysis run is not available for completion")

        ensure_default_topics(session, owner_user_id=owner_id)

        for bucket in result["buckets"]:
            topic_id = _topic_id_by_name(session, bucket["name"])
            for analyzed_item in bucket["notes"]:
                item_id = analyzed_item["id"]
                if _owned_item(session, item_id, owner_id) is None:
                    raise ValueError(
                        f"Analysis references missing item {item_id}"
                    )
                insight = session.get(ItemInsightRecord, item_id)
                if insight is None:
                    insight = ItemInsightRecord(
                        item_id=item_id,
                        needs_review=0,
                    )
                    session.add(insight)
                insight.analysis_run_id = run_id
                # AI fields always refresh; user overrides are preserved.
                insight.category = bucket["name"]
                insight.concise_title = analyzed_item["title"]
                insight.priority = analyzed_item["priority"]
                insight.topic_id = topic_id
                tags = analyzed_item.get("tags") or []
                insight.tags_json = json.dumps(tags, ensure_ascii=False)
                insight.rationale = analyzed_item.get("rationale") or (
                    f"Grouped under “{bucket['name']}” based on the note content."
                )
                insight.needs_review = 0
                insight.updated_at = completed_at
                item = _owned_item(session, item_id, owner_id)
                if item is not None and insight.user_title is None:
                    item.title = analyzed_item["title"]

        for todo in result["todos"]:
            source_item_ids = sorted(set(todo["source_note_ids"]))
            if not source_item_ids:
                continue
            for item_id in source_item_ids:
                if _owned_item(session, item_id, owner_id) is None:
                    raise ValueError(
                        f"Task references missing item {item_id}"
                    )

            dedup_key = _task_dedup_key(source_item_ids, todo["task"])
            task = session.scalars(
                select(TaskRecord).where(
                    TaskRecord.dedup_key == dedup_key,
                    TaskRecord.owner_user_id == owner_id,
                )
            ).first()

            if task is None:
                # Durable match: same sources + similar normalized wording.
                candidates = session.scalars(
                    select(TaskRecord)
                    .join(TaskSourceItemRecord)
                    .where(
                        TaskRecord.owner_user_id == owner_id,
                        TaskSourceItemRecord.item_id.in_(source_item_ids),
                    )
                    .distinct()
                    .order_by(TaskRecord.id.asc())
                ).all()
                target_norm = _normalize_task_text(todo["task"])
                for candidate in candidates:
                    candidate_sources = set(
                        session.scalars(
                            select(TaskSourceItemRecord.item_id).where(
                                TaskSourceItemRecord.task_id == candidate.id
                            )
                        ).all()
                    )
                    if candidate_sources != set(source_item_ids):
                        continue
                    if _normalize_task_text(candidate.text) == target_norm:
                        task = candidate
                        break
                    # Soft wording drift still maps to the same durable task.
                    left = set(target_norm.split())
                    right = set(_normalize_task_text(candidate.text).split())
                    if left and right and len(left & right) / len(left | right) >= 0.6:
                        task = candidate
                        break

            if task is None:
                from app.attention.dates import parse_timing_phrase

                parsed_timing = parse_timing_phrase(todo.get("when"))
                task = TaskRecord(
                    text=todo["task"],
                    priority=todo["priority"],
                    timing_text=todo["when"],
                    ai_timing_text=todo["when"],
                    timing_confirmed=0,
                    due_on=parsed_timing.normalized_iso,
                    due_confidence=parsed_timing.confidence,
                    status=TASK_OPEN,
                    dedup_key=dedup_key,
                    owner_user_id=owner_id,
                    created_at=completed_at,
                    updated_at=completed_at,
                )
                session.add(task)
                session.flush()
                for item_id in source_item_ids:
                    session.add(
                        TaskSourceItemRecord(
                            task_id=task.id,
                            item_id=item_id,
                        )
                    )
            else:
                from app.attention.dates import parse_timing_phrase

                task.text = todo["task"]
                task.priority = todo["priority"]
                task.ai_timing_text = todo["when"]
                if not task.timing_confirmed:
                    task.timing_text = todo["when"]
                    parsed_timing = parse_timing_phrase(todo.get("when"))
                    task.due_on = parsed_timing.normalized_iso
                    task.due_confidence = parsed_timing.confidence
                task.dedup_key = dedup_key
                task.updated_at = completed_at
                linked = set(
                    session.scalars(
                        select(TaskSourceItemRecord.item_id).where(
                            TaskSourceItemRecord.task_id == task.id
                        )
                    ).all()
                )
                for item_id in source_item_ids:
                    if item_id not in linked:
                        session.add(
                            TaskSourceItemRecord(
                                task_id=task.id,
                                item_id=item_id,
                            )
                        )

        _refresh_owner_relations(session, owner_id, completed_at)

        fingerprint = compute_inbox_fingerprint(session)
        persisted = {
            **result,
            "inbox_fingerprint": fingerprint,
        }
        run.completed_at = completed_at
        run.status = ANALYSIS_SUCCEEDED
        run.mode = result["mode"]
        run.result_json = json.dumps(persisted, ensure_ascii=False)
        session.commit()
        return {
            **result,
            "analysis_run_id": run_id,
            "generated_at": completed_at,
            "is_stale": False,
            "inbox_fingerprint": fingerprint,
        }


def _refresh_owner_relations(session, owner_id: int, now: str) -> None:
    """Recompute deterministic relations among one owner's items only.

    A relation row must never connect items of different owners. Dismissed
    rows are kept only when both endpoints belong to this owner; any
    cross-owner row touching this owner's items is removed, dismissed or not.
    """
    owned_items = session.scalars(
        select(InboxItemRecord).where(InboxItemRecord.owner_user_id == owner_id)
    ).all()
    owned_ids = {item.id for item in owned_items}
    touching = session.scalars(
        select(ItemRelationRecord).where(
            or_(
                ItemRelationRecord.item_id_a.in_(_owned_item_ids(owner_id)),
                ItemRelationRecord.item_id_b.in_(_owned_item_ids(owner_id)),
            )
        )
    ).all()
    for relation in touching:
        same_owner = (
            relation.item_id_a in owned_ids and relation.item_id_b in owned_ids
        )
        if not same_owner or not relation.dismissed:
            session.delete(relation)
    session.flush()

    items = [_item_to_dict(item) for item in owned_items]
    for relation in find_item_relations(items):
        if (
            relation["item_id_a"] not in owned_ids
            or relation["item_id_b"] not in owned_ids
        ):
            continue
        existing = session.scalars(
            select(ItemRelationRecord).where(
                ItemRelationRecord.item_id_a == relation["item_id_a"],
                ItemRelationRecord.item_id_b == relation["item_id_b"],
                ItemRelationRecord.relation_type == relation["relation_type"],
            )
        ).first()
        if existing is not None:
            if existing.dismissed:
                continue
            existing.score = relation["score"]
            continue
        session.add(
            ItemRelationRecord(
                item_id_a=relation["item_id_a"],
                item_id_b=relation["item_id_b"],
                relation_type=relation["relation_type"],
                score=relation["score"],
                created_at=now,
                dismissed=0,
            )
        )
    session.flush()


def fail_analysis_run(run_id: int) -> None:
    completed_at = datetime.now(timezone.utc).isoformat()
    owner_id = require_owner_id()
    with SessionLocal() as session:
        run = session.get(AnalysisRunRecord, run_id)
        if (
            run is None
            or run.status != ANALYSIS_RUNNING
            or run.owner_user_id != owner_id
        ):
            return
        run.completed_at = completed_at
        run.status = ANALYSIS_FAILED
        run.mode = "error"
        run.result_json = None
        session.commit()


def get_latest_successful_analysis() -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        run = session.scalars(
            select(AnalysisRunRecord)
            .where(
                AnalysisRunRecord.status == ANALYSIS_SUCCEEDED,
                AnalysisRunRecord.owner_user_id == owner_id,
            )
            .order_by(
                AnalysisRunRecord.completed_at.desc(),
                AnalysisRunRecord.id.desc(),
            )
            .limit(1)
        ).first()
        if run is None:
            return None
        stored = json.loads(run.result_json)
        fingerprint = stored.pop("inbox_fingerprint", None)
        current = compute_inbox_fingerprint(session)
        return {
            **stored,
            "analysis_run_id": run.id,
            "generated_at": run.completed_at,
            "is_stale": fingerprint != current,
            "inbox_fingerprint": fingerprint,
        }


def _task_dedup_key(source_item_ids: list[int], task_text: str = "") -> str:
    fingerprint = json.dumps(
        {
            "sources": sorted(set(source_item_ids)),
            "task": _normalize_task_text(task_text),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def _ensure_task_due_fields(task: TaskRecord) -> None:
    """Normalize due_on from timing_text when missing."""
    from app.attention.dates import parse_timing_phrase

    if task.due_on and task.due_confidence:
        return
    parsed = parse_timing_phrase(task.timing_text)
    task.due_on = parsed.normalized_iso
    task.due_confidence = parsed.confidence


def _task_to_dict(session, task: TaskRecord) -> dict:
    _ensure_task_due_fields(task)
    source_item_ids = session.scalars(
        select(TaskSourceItemRecord.item_id)
        .where(TaskSourceItemRecord.task_id == task.id)
        .order_by(TaskSourceItemRecord.item_id.asc())
    ).all()
    today = today_in_configured_tz()
    suggested_due_on = None
    if not task.due_on:
        suggested_due_on = (
            today + timedelta(days=default_due_offset(task.priority))
        ).isoformat()
    return {
        "id": task.id,
        "text": task.text,
        "priority": task.priority,
        "days_left": days_left(task.due_on, today),
        "days_left_label": days_left_label(task.due_on, today),
        "urgency": urgency(task.due_on, today),
        "suggested_due_on": suggested_due_on,
        "points_value": PRIORITY_POINTS.get(task.priority, 10),
        "google_event_url": (
            google_event_url(
                f"[{task.priority}] {task.text}", task.due_on, "From Life Inbox"
            )
            if task.due_on
            else None
        ),
        "completed_at": task.completed_at,
        "points_awarded": task.points_awarded,
        "binned_at": task.binned_at,
        "timing_text": task.timing_text,
        "ai_timing_text": task.ai_timing_text,
        "timing_confirmed": bool(task.timing_confirmed),
        "due_on": task.due_on,
        "due_confidence": task.due_confidence,
        "snoozed_until": task.snoozed_until,
        "reminder_at": task.reminder_at,
        "status": task.status,
        "source_item_ids": list(source_item_ids),
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def list_tasks_from_db(status_filter: str = TASK_OPEN) -> list[dict]:
    if status_filter not in TASK_STATUSES | {"all", "backlog"}:
        raise ValueError("Unsupported task status")

    owner_id = require_owner_id()
    with SessionLocal() as session:
        statement = (
            select(TaskRecord)
            .where(TaskRecord.owner_user_id == owner_id)
            .order_by(TaskRecord.id.asc())
        )
        if status_filter == "backlog":
            statement = statement.where(TaskRecord.binned_at.is_not(None))
        elif status_filter != "all":
            statement = statement.where(
                TaskRecord.status == status_filter,
                TaskRecord.binned_at.is_(None),
            )
        tasks = session.scalars(statement).all()
        return [_task_to_dict(session, task) for task in tasks]


def set_task_status(task_id: int, task_status: str) -> Optional[dict]:
    if task_status not in TASK_STATUSES:
        raise ValueError("Unsupported task status")

    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = _owned_task(session, task_id, owner_id)
        if task is None:
            return None
        if task.status != task_status:
            now = datetime.now(timezone.utc)
            today = today_in_configured_tz()
            if task_status == "completed" and task.points_awarded is None:
                points = points_for(task.priority, task.due_on, today)
                task.points_awarded = points
                task.completed_at = now.isoformat()
                session.add(
                    PointEventRecord(
                        owner_user_id=owner_id,
                        task_id=task.id,
                        points=points,
                        day=today.isoformat(),
                        created_at=now.isoformat(),
                    )
                )
            elif task.status == "completed" and task_status != "completed":
                # Reopening or dismissing takes the points back, so
                # complete -> reopen -> complete cannot farm points.
                session.execute(
                    delete(PointEventRecord).where(
                        PointEventRecord.task_id == task.id
                    )
                )
                task.points_awarded = None
                task.completed_at = None
            task.status = task_status
            task.updated_at = now.isoformat()
            session.commit()
        return _task_to_dict(session, task)


def set_item_domain(item_id: int, domain: Optional[str]) -> Optional[dict]:
    """Save a person's domain choice; None/Unsorted clears it back to auto."""
    if domain is not None and domain not in DOMAINS + [UNSORTED]:
        raise ValueError("Unknown domain")
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None:
            return None
        if domain in (None, UNSORTED):
            item.domain, item.domain_source = None, None
        else:
            item.domain, item.domain_source = domain, "user"
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def add_text_file_item_to_db(
    filename: str, mime_type: str, text: str
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=TEXT_ITEM_TYPE,
            title=filename,
            raw_text=text,
            original_filename=filename,
            mime_type=mime_type,
            processing_status=READY_STATUS,
            owner_user_id=require_owner_id(),
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def create_quick_task(
    text: str,
    priority: str,
    due_on: Optional[str],
    due_confidence: Optional[str],
) -> dict:
    """Create a task directly from a spoken or typed sentence (no source note)."""
    owner_id = require_owner_id()
    now = datetime.now(timezone.utc).isoformat()
    dedup_key = hashlib.sha256(
        f"quick:{owner_id}:{text}:{now}".encode("utf-8")
    ).hexdigest()
    with SessionLocal() as session:
        task = TaskRecord(
            text=text,
            priority=priority,
            timing_text=due_on,
            timing_confirmed=1 if due_on else 0,
            due_on=due_on,
            due_confidence=due_confidence or ("high" if due_on else None),
            status=TASK_OPEN,
            dedup_key=dedup_key,
            owner_user_id=owner_id,
            created_at=now,
            updated_at=now,
        )
        session.add(task)
        session.commit()
        return _task_to_dict(session, task)


def update_task_fields(
    task_id: int,
    priority: Optional[str] = None,
    due_on: Optional[str] = None,
) -> Optional[dict]:
    """Change an open task's priority or deadline (drag between lanes/days)."""
    if priority is not None and priority not in PRIORITY_POINTS:
        raise ValueError("Unknown priority")
    if due_on is not None:
        from datetime import date as _date

        _date.fromisoformat(due_on)
    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = _owned_task(session, task_id, owner_id)
        if task is None:
            return None
        if task.status != TASK_OPEN:
            raise ValueError("Only open tasks can be changed")
        if priority is not None:
            task.priority = priority
        if due_on is not None:
            task.due_on = due_on
            task.timing_text = due_on
            task.timing_confirmed = 1
            task.due_confidence = "high"
        task.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _task_to_dict(session, task)


def set_task_binned(task_id: int, binned: bool) -> Optional[dict]:
    """Move a completed task to the bin (backlog) or restore it.

    Binning never changes status or points, so the daily total is unchanged.
    """
    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = _owned_task(session, task_id, owner_id)
        if task is None:
            return None
        if binned and task.status != TASK_COMPLETED:
            raise ValueError("Only completed tasks can be binned")
        now = datetime.now(timezone.utc).isoformat()
        task.binned_at = now if binned else None
        task.updated_at = now
        session.commit()
        return _task_to_dict(session, task)


def game_summary_from_db() -> dict:
    owner_id = require_owner_id()
    today = today_in_configured_tz()
    with SessionLocal() as session:
        rows = session.execute(
            select(PointEventRecord.day, func.sum(PointEventRecord.points))
            .where(PointEventRecord.owner_user_id == owner_id)
            .group_by(PointEventRecord.day)
        ).all()
        done_today = session.scalar(
            select(func.count(PointEventRecord.id)).where(
                PointEventRecord.owner_user_id == owner_id,
                PointEventRecord.day == today.isoformat(),
            )
        )
    return build_game_summary(
        {day: int(total) for day, total in rows}, today, int(done_today or 0)
    )


def add_pdf_item_to_db(
    original_filename: str,
    storage_path: str,
    mime_type: str,
) -> dict:
    """Persist uploaded PDF metadata before text extraction."""
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=PDF_ITEM_TYPE,
            original_filename=original_filename,
            storage_path=storage_path,
            mime_type=mime_type,
            processing_status=STATUS_CAPTURED,
            owner_user_id=require_owner_id(),
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def complete_pdf_item_processing(
    item_id: int,
    *,
    title: str,
    raw_text: str,
    extracted_text: str,
    mime_type: Optional[str],
) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None:
            return None
        item.title = title
        item.raw_text = raw_text
        item.extracted_text = extracted_text
        item.mime_type = mime_type
        item.processing_status = STATUS_READY
        item.error_message = None
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def add_image_item_to_db(
    original_filename: str,
    storage_path: str,
    mime_type: str,
) -> dict:
    """Persist uploaded image metadata before OCR/description."""
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=IMAGE_ITEM_TYPE,
            original_filename=original_filename,
            storage_path=storage_path,
            mime_type=mime_type,
            processing_status=STATUS_CAPTURED,
            owner_user_id=require_owner_id(),
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def complete_image_item_processing(
    item_id: int,
    *,
    title: str,
    raw_text: str,
    extracted_text: str,
    ai_description: str,
    mime_type: Optional[str],
) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None:
            return None
        item.title = title
        item.raw_text = raw_text
        item.extracted_text = extracted_text
        item.ai_description = ai_description
        item.mime_type = mime_type
        item.processing_status = STATUS_READY
        item.error_message = None
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def add_voice_item_to_db(
    original_filename: str,
    storage_path: str,
    mime_type: str,
) -> dict:
    """Persist uploaded voice note metadata before transcription."""
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=VOICE_ITEM_TYPE,
            original_filename=original_filename,
            storage_path=storage_path,
            mime_type=mime_type,
            processing_status=STATUS_CAPTURED,
            owner_user_id=require_owner_id(),
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def complete_voice_item_processing(
    item_id: int,
    *,
    title: str,
    raw_text: str,
    extracted_text: str,
    mime_type: Optional[str],
) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None:
            return None
        item.title = title
        item.raw_text = raw_text
        item.extracted_text = extracted_text
        item.mime_type = mime_type
        item.processing_status = STATUS_READY
        item.error_message = None
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def update_item_extracted_text(
    item_id: int,
    extracted_text: str,
) -> Optional[dict]:
    """User edit of extracted/OCR/transcript text (facts), preserving AI description."""
    cleaned = extracted_text.strip()
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None:
            return None
        if item.item_type not in {IMAGE_ITEM_TYPE, VOICE_ITEM_TYPE, PDF_ITEM_TYPE}:
            return None
        item.extracted_text = cleaned
        if item.item_type == IMAGE_ITEM_TYPE and item.ai_description:
            item.raw_text = (
                f"{cleaned}\n\n[AI description — inferred]\n{item.ai_description}"
                if cleaned
                else f"[AI description — inferred]\n{item.ai_description}"
            )
        else:
            item.raw_text = cleaned
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def add_url_item_to_db(url: str) -> dict:
    """Persist URL first (captured), then return the row for processing."""
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=URL_ITEM_TYPE,
            source_url=url,
            processing_status=STATUS_CAPTURED,
            owner_user_id=require_owner_id(),
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def mark_item_processing(item_id: int) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None:
            return None
        item.processing_status = STATUS_PROCESSING
        item.error_message = None
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def complete_url_item_processing(
    item_id: int,
    *,
    title: str,
    raw_text: str,
    mime_type: Optional[str],
    final_url: Optional[str] = None,
) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None:
            return None
        item.title = title
        item.raw_text = raw_text
        item.extracted_text = raw_text
        item.mime_type = mime_type
        if final_url:
            item.source_url = final_url
        item.processing_status = STATUS_READY
        item.error_message = None
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def fail_item_processing(item_id: int, error_message: str) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None:
            return None
        item.processing_status = STATUS_FAILED
        item.error_message = error_message[:1000]
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def get_item_from_db(item_id: int) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None:
            return None
        return _item_to_dict(item)


def confirm_task_timing(
    task_id: int,
    timing_text: Optional[str] = None,
) -> Optional[dict]:
    from app.attention.dates import parse_timing_phrase

    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = _owned_task(session, task_id, owner_id)
        if task is None:
            return None
        if timing_text is not None:
            task.timing_text = timing_text
        parsed = parse_timing_phrase(task.timing_text)
        task.due_on = parsed.normalized_iso
        task.due_confidence = "high" if parsed.due_date else parsed.confidence
        task.timing_confirmed = 1
        task.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _task_to_dict(session, task)


def snooze_task_in_db(task_id: int, until_iso_date: str) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = _owned_task(session, task_id, owner_id)
        if task is None:
            return None
        task.snoozed_until = until_iso_date
        task.reminder_at = until_iso_date
        task.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _task_to_dict(session, task)


def set_task_reminder_in_db(task_id: int, reminder_iso_date: str) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = _owned_task(session, task_id, owner_id)
        if task is None:
            return None
        task.reminder_at = reminder_iso_date
        task.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _task_to_dict(session, task)


def get_attention_board() -> dict:
    from app.attention.dates import (
        classify_attention_bucket,
        parse_timing_phrase,
        today_in_configured_tz,
    )
    from datetime import date as date_cls

    today = today_in_configured_tz()
    board = {
        "today": [],
        "upcoming": [],
        "overdue": [],
        "unscheduled": [],
        "snoozed": [],
        "needs_confirmation": [],
        "reference_date": today.isoformat(),
    }
    for task in list_tasks_from_db(status_filter=TASK_OPEN):
        parsed = parse_timing_phrase(task.get("timing_text"))
        due = None
        if task.get("due_on"):
            try:
                due = date_cls.fromisoformat(task["due_on"])
            except ValueError:
                due = parsed.due_date
        else:
            due = parsed.due_date
        snoozed = None
        if task.get("snoozed_until"):
            try:
                snoozed = date_cls.fromisoformat(task["snoozed_until"])
            except ValueError:
                snoozed = None
        bucket = classify_attention_bucket(due, reference=today, snoozed_until=snoozed)
        entry = {
            **task,
            "original_timing_phrase": task.get("timing_text"),
            "normalized_due_on": due.isoformat() if due else None,
            "due_confidence": task.get("due_confidence") or parsed.confidence,
            "needs_confirmation": (
                (not task.get("timing_confirmed"))
                and parsed.needs_confirmation
            ),
            "attention_bucket": bucket,
            "parse_note": parsed.note,
        }
        board[bucket].append(entry)
        if entry["needs_confirmation"]:
            board["needs_confirmation"].append(entry)
    return board


def get_daily_briefing() -> dict:
    board = get_attention_board()
    priority_rank = {"High": 0, "Medium": 1, "Low": 2}
    focus = sorted(
        board["overdue"] + board["today"],
        key=lambda item: (
            priority_rank.get(item.get("priority"), 9),
            item.get("normalized_due_on") or "9999",
        ),
    )
    suggestions = []
    for item in focus[:5]:
        reason = []
        if item["attention_bucket"] == "overdue":
            reason.append("overdue")
        if item["attention_bucket"] == "today":
            reason.append("due today")
        if item.get("priority") == "High":
            reason.append("high priority")
        suggestions.append(
            {
                "task_id": item["id"],
                "text": item["text"],
                "priority": item["priority"],
                "reason": ", ".join(reason) or "on your attention list",
            }
        )
    return {
        "reference_date": board["reference_date"],
        "counts": {
            "overdue": len(board["overdue"]),
            "today": len(board["today"]),
            "upcoming": len(board["upcoming"]),
            "unscheduled": len(board["unscheduled"]),
            "snoozed": len(board["snoozed"]),
            "needs_confirmation": len(board["needs_confirmation"]),
        },
        "focus": focus[:10],
        "priority_suggestions": suggestions,
        "summary": (
            f"{len(board['overdue'])} overdue, {len(board['today'])} due today, "
            f"{len(board['upcoming'])} upcoming."
        ),
    }


WEEKLY_REVIEW_DAYS = 7


def _parse_stored_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_weekly_review(now: Optional[datetime] = None) -> dict:
    """Facts about the owner's last seven days, computed only from stored rows.

    Counts come from the database, never from a model.  The plain-language
    summary is added separately by ``app.review``.
    """
    from datetime import timedelta

    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WEEKLY_REVIEW_DAYS)
    owner_id = require_owner_id()

    def in_window(value: Optional[str]) -> bool:
        stamp = _parse_stored_timestamp(value)
        return stamp is not None and since <= stamp <= now

    with SessionLocal() as session:
        items = [
            item
            for item in session.scalars(
                select(InboxItemRecord)
                .where(InboxItemRecord.owner_user_id == owner_id)
                .order_by(InboxItemRecord.id.asc())
            )
            if in_window(item.created_at)
        ]
        item_ids = [item.id for item in items]

        captured_by_type: dict[str, int] = {}
        for item in items:
            captured_by_type[item.item_type] = captured_by_type.get(item.item_type, 0) + 1

        tasks = session.scalars(
            select(TaskRecord).where(TaskRecord.owner_user_id == owner_id)
        ).all()
        # There is no completed_at column; a completed task's updated_at is
        # the closest stored fact for when it was finished.
        completed = [
            {"id": task.id, "text": task.text, "priority": task.priority}
            for task in tasks
            if task.status == TASK_COMPLETED and in_window(task.updated_at)
        ]
        open_task_count = sum(1 for task in tasks if task.status == TASK_OPEN)

        insights = {}
        linked_item_ids: set[int] = set()
        if item_ids:
            insights = {
                insight.item_id: insight
                for insight in session.scalars(
                    _owned_insights(owner_id).where(
                        ItemInsightRecord.item_id.in_(item_ids)
                    )
                )
            }
            linked_item_ids = set(
                session.scalars(
                    select(TaskSourceItemRecord.item_id)
                    .join(TaskRecord, TaskRecord.id == TaskSourceItemRecord.task_id)
                    .where(TaskRecord.owner_user_id == owner_id)
                    .where(TaskSourceItemRecord.item_id.in_(item_ids))
                )
            )

        owned_topics = {
            topic.id: topic.name
            for topic in session.scalars(
                select(TopicRecord).where(TopicRecord.owner_user_id == owner_id)
            )
        }
        topic_counts: dict[str, int] = {}
        for insight in insights.values():
            topic_id = (
                insight.user_topic_id
                if insight.user_topic_id in owned_topics
                else insight.topic_id
            )
            name = owned_topics.get(topic_id)
            if name:
                topic_counts[name] = topic_counts.get(name, 0) + 1
        top_topics = [
            {"name": name, "count": count}
            for name, count in sorted(
                topic_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )[:3]
        ]

        # "Forgotten" = captured this week but never organized and never
        # turned into a task.
        untouched = [
            {
                "id": item.id,
                "item_type": item.item_type,
                "text": (
                    item.title
                    or item.raw_text
                    or item.original_filename
                    or item.source_url
                    or ""
                ).strip()[:160],
                "created_at": item.created_at,
            }
            for item in items
            if item.id not in insights and item.id not in linked_item_ids
        ]

    return {
        "since": since.isoformat(),
        "until": now.isoformat(),
        "days": WEEKLY_REVIEW_DAYS,
        "captured": {"total": len(items), "by_type": captured_by_type},
        "completed_tasks": completed,
        "open_task_count": open_task_count,
        "top_topics": top_topics,
        "untouched_items": untouched[:10],
        "untouched_count": len(untouched),
    }


def save_calendar_receipt(
    *,
    draft_id: str,
    task_id: int,
    provider: str,
    status: str,
    payload: dict,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    owner_id = require_owner_id()
    with SessionLocal() as session:
        if _owned_task(session, task_id, owner_id) is None:
            raise ValueError("Task not found")
        receipt = CalendarActionReceiptRecord(
            draft_id=draft_id,
            task_id=task_id,
            provider=provider,
            status=status,
            payload_json=json.dumps(payload),
            created_at=now,
        )
        session.add(receipt)
        session.commit()
        return {
            "id": receipt.id,
            "draft_id": receipt.draft_id,
            "task_id": receipt.task_id,
            "provider": receipt.provider,
            "status": receipt.status,
            "payload": payload,
            "created_at": receipt.created_at,
        }


def _topic_to_dict(topic: TopicRecord, item_count: int = 0) -> dict:
    return {
        "id": topic.id,
        "name": topic.name,
        "description": topic.description,
        "archived": bool(topic.archived),
        "item_count": item_count,
        "created_at": topic.created_at,
        "updated_at": topic.updated_at,
    }


def list_topics_from_db(include_archived: bool = False) -> list[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        ensure_default_topics(session, owner_user_id=owner_id)
        session.commit()
        statement = (
            select(TopicRecord)
            .where(TopicRecord.owner_user_id == owner_id)
            .order_by(TopicRecord.name.asc())
        )
        if not include_archived:
            statement = statement.where(TopicRecord.archived == 0)
        topics = session.scalars(statement).all()
        owned_topic_ids = _owned_topic_ids(session, owner_id)
        counts = {}
        for insight in session.scalars(_owned_insights(owner_id)).all():
            effective_topic = _insight_to_dict(insight, owned_topic_ids)[
                "effective_topic_id"
            ]
            if effective_topic is None:
                continue
            counts[effective_topic] = counts.get(effective_topic, 0) + 1
        return [
            _topic_to_dict(topic, counts.get(topic.id, 0)) for topic in topics
        ]


def create_topic_in_db(name: str, description: Optional[str] = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    owner_id = require_owner_id()
    with SessionLocal() as session:
        ensure_default_topics(session, owner_user_id=owner_id)
        existing = session.scalars(
            select(TopicRecord).where(
                TopicRecord.name == name,
                TopicRecord.owner_user_id == owner_id,
            )
        ).first()
        if existing is not None:
            if existing.archived:
                existing.archived = 0
                existing.description = description
                existing.updated_at = now
                session.commit()
                return _topic_to_dict(existing)
            raise ValueError("Topic already exists")
        topic = TopicRecord(
            name=name,
            description=description,
            owner_user_id=owner_id,
            created_at=now,
            updated_at=now,
            archived=0,
        )
        session.add(topic)
        session.commit()
        return _topic_to_dict(topic)


def update_topic_in_db(
    topic_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    archived: Optional[bool] = None,
) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        topic = session.get(TopicRecord, topic_id)
        if topic is not None and topic.owner_user_id != owner_id:
            return None
        if topic is None:
            return None
        if name is not None:
            topic.name = name
        if description is not None:
            topic.description = description
        if archived is not None:
            topic.archived = 1 if archived else 0
        topic.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _topic_to_dict(topic)


def _parse_tags(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(tag) for tag in value]


def _owned_insights(owner_id: int):
    return select(ItemInsightRecord).where(
        ItemInsightRecord.item_id.in_(_owned_item_ids(owner_id))
    )


def _insight_to_dict(
    insight: ItemInsightRecord,
    owned_topic_ids: Optional[set[int]] = None,
) -> dict:
    """Serialize an insight; topic references outside the owner are dropped."""

    def _own_topic(topic_id: Optional[int]) -> Optional[int]:
        if topic_id is None or owned_topic_ids is None:
            return topic_id
        return topic_id if topic_id in owned_topic_ids else None

    topic_id = _own_topic(insight.topic_id)
    user_topic_id = _own_topic(insight.user_topic_id)
    effective_title = insight.user_title or insight.concise_title
    effective_priority = insight.user_priority or insight.priority
    effective_topic_id = user_topic_id if user_topic_id is not None else topic_id
    effective_tags = (
        _parse_tags(insight.user_tags_json)
        if insight.user_tags_json is not None
        else _parse_tags(insight.tags_json)
    )
    return {
        "item_id": insight.item_id,
        "analysis_run_id": insight.analysis_run_id,
        "category": insight.category,
        "concise_title": insight.concise_title,
        "priority": insight.priority,
        "topic_id": topic_id,
        "tags": _parse_tags(insight.tags_json),
        "rationale": insight.rationale,
        "user_title": insight.user_title,
        "user_topic_id": user_topic_id,
        "user_priority": insight.user_priority,
        "user_tags": (
            _parse_tags(insight.user_tags_json)
            if insight.user_tags_json is not None
            else None
        ),
        "effective_title": effective_title,
        "effective_priority": effective_priority,
        "effective_topic_id": effective_topic_id,
        "effective_tags": effective_tags,
        "needs_review": bool(insight.needs_review),
        "updated_at": insight.updated_at,
        "has_user_overrides": any(
            [
                insight.user_title is not None,
                user_topic_id is not None,
                insight.user_priority is not None,
                insight.user_tags_json is not None,
            ]
        ),
    }


def get_item_insight(item_id: int) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        if _owned_item(session, item_id, owner_id) is None:
            return None
        insight = session.get(ItemInsightRecord, item_id)
        if insight is None:
            return None
        return _insight_to_dict(insight, _owned_topic_ids(session, owner_id))


def update_item_insight_overrides(
    item_id: int,
    user_title: Optional[str] = None,
    user_topic_id: Optional[int] = None,
    user_priority: Optional[str] = None,
    user_tags: Optional[list[str]] = None,
    clear_overrides: bool = False,
    needs_review: Optional[bool] = None,
) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = _owned_item(session, item_id, owner_id)
        if item is None:
            return None
        insight = session.get(ItemInsightRecord, item_id)
        if insight is None:
            return None
        if clear_overrides:
            insight.user_title = None
            insight.user_topic_id = None
            insight.user_priority = None
            insight.user_tags_json = None
        else:
            if user_title is not None:
                insight.user_title = user_title
            if user_topic_id is not None:
                if _owned_topic(session, user_topic_id, owner_id) is None:
                    raise ValueError("Topic not found")
                insight.user_topic_id = user_topic_id
            if user_priority is not None:
                insight.user_priority = user_priority
            if user_tags is not None:
                insight.user_tags_json = json.dumps(
                    user_tags, ensure_ascii=False
                )
        if needs_review is not None:
            insight.needs_review = 1 if needs_review else 0
        insight.updated_at = datetime.now(timezone.utc).isoformat()
        if insight.user_title:
            item.title = insight.user_title
        session.commit()
        return _insight_to_dict(insight, _owned_topic_ids(session, owner_id))


def _relation_to_dict(row: ItemRelationRecord) -> dict:
    return {
        "id": row.id,
        "item_id_a": row.item_id_a,
        "item_id_b": row.item_id_b,
        "relation_type": row.relation_type,
        "score": float(row.score),
        "dismissed": bool(row.dismissed),
        "created_at": row.created_at,
    }


def _owned_relations(owner_id: int):
    """Relations whose two endpoints both belong to this owner."""
    owned_ids = _owned_item_ids(owner_id)
    return select(ItemRelationRecord).where(
        ItemRelationRecord.item_id_a.in_(owned_ids),
        ItemRelationRecord.item_id_b.in_(owned_ids),
    )


def list_relations_from_db(
    include_dismissed: bool = False,
) -> list[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        statement = _owned_relations(owner_id).order_by(
            ItemRelationRecord.id.asc()
        )
        if not include_dismissed:
            statement = statement.where(ItemRelationRecord.dismissed == 0)
        rows = session.scalars(statement).all()
        return [_relation_to_dict(row) for row in rows]


def dismiss_relation_in_db(relation_id: int) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        row = session.scalars(
            _owned_relations(owner_id).where(
                ItemRelationRecord.id == relation_id
            )
        ).first()
        if row is None:
            return None
        row.dismissed = 1
        session.commit()
        return _relation_to_dict(row)


def get_organization_dashboard() -> dict:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        ensure_default_topics(session, owner_user_id=owner_id)
        session.commit()
        topics = list_topics_from_db()
        owned_topic_ids = _owned_topic_ids(session, owner_id)
        insights = {
            insight.item_id: _insight_to_dict(insight, owned_topic_ids)
            for insight in session.scalars(_owned_insights(owner_id)).all()
        }
        items = [
            _item_to_dict(item)
            for item in session.scalars(
                select(InboxItemRecord)
                .where(InboxItemRecord.owner_user_id == owner_id)
                .order_by(InboxItemRecord.id.desc())
            ).all()
        ]
        high_priority = []
        needs_review = []
        for item in items:
            insight = insights.get(item["id"])
            if insight is None:
                needs_review.append(
                    {
                        **item,
                        "reason": "Not yet organized",
                    }
                )
                continue
            card = {
                **item,
                "effective_title": insight["effective_title"],
                "effective_priority": insight["effective_priority"],
                "effective_topic_id": insight["effective_topic_id"],
                "rationale": insight["rationale"],
                "has_user_overrides": insight["has_user_overrides"],
            }
            if insight["effective_priority"] == "High":
                high_priority.append(card)
            if insight["needs_review"]:
                needs_review.append({**card, "reason": "Marked for review"})

        latest = get_latest_successful_analysis()
        if latest and latest.get("is_stale"):
            for item in items:
                if item["id"] in insights:
                    needs_review.append(
                        {
                            **item,
                            "effective_title": insights[item["id"]][
                                "effective_title"
                            ],
                            "reason": "Analysis stale — re-analyze recommended",
                        }
                    )
                    break

        open_tasks = list_tasks_from_db(TASK_OPEN)
        relations = list_relations_from_db()
        return {
            "topics": topics,
            "high_priority": high_priority[:20],
            "open_tasks": open_tasks[:20],
            "recently_captured": items[:10],
            "needs_review": needs_review[:20],
            "related_items": relations[:20],
            "analysis": latest,
        }
