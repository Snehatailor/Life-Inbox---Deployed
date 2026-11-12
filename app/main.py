import logging
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlencode

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles

from app.capture.image_extract import process_image_bytes, validate_image_upload
from app.capture.pdf_extract import extract_pdf_text, validate_pdf_upload
from app.capture.storage import (
    read_stored_bytes,
    resolve_storage_path,
    store_audio_bytes,
    store_image_bytes,
    store_pdf_bytes,
    store_thumbnail_bytes,
    thumbnail_relative_path,
)
from app.capture.url_fetch import fetch_url, validate_public_http_url
from app.capture.voice_extract import process_voice_bytes, validate_audio_upload
from app.database import (
    add_image_item_to_db,
    add_item_to_db,
    add_note_to_db,
    add_pdf_item_to_db,
    add_url_item_to_db,
    add_voice_item_to_db,
    complete_image_item_processing,
    complete_pdf_item_processing,
    complete_voice_item_processing,
    complete_analysis_run,
    complete_url_item_processing,
    confirm_task_timing,
    create_topic_in_db,
    delete_item_from_db,
    delete_note_from_db,
    dismiss_relation_in_db,
    fail_analysis_run,
    fail_item_processing,
    get_attention_board,
    get_daily_briefing,
    get_item_from_db,
    get_item_insight,
    get_latest_successful_analysis,
    get_organization_dashboard,
    init_db,
    OwnerRequiredError,
    require_owner_id,
    list_items_from_db,
    list_notes_from_db,
    list_relations_from_db,
    list_tasks_from_db,
    list_topics_from_db,
    mark_item_processing,
    save_calendar_receipt,
    set_task_reminder_in_db,
    set_task_status,
    snooze_task_in_db,
    start_analysis_run,
    update_item_extracted_text,
    update_item_in_db,
    update_item_insight_overrides,
    update_note_in_db,
    update_topic_in_db,
)
from app.integrations.google_calendar import CalendarConnectionError
from app.integrations.calendar import (
    CalendarWriteBlockedError,
    get_calendar_adapter,
    get_draft,
    store_draft,
)
from app.organizer import analyze_inbox_with_openai, validate_analysis_result
from app.retrieval.ask import build_grounded_answer
from app.retrieval.search import search_passages
from app.schemas import (
    AskRequest,
    AskResponse,
    CalendarConfirmRequest,
    CalendarPreviewRequest,
    ExtractedTextUpdate,
    InboxItem,
    InboxItemCreate,
    InboxItemUpdate,
    InsightOverrideUpdate,
    ItemInsight,
    ItemRelation,
    Note,
    NoteCreate,
    NoteUpdate,
    PersistedAnalysis,
    Priority,
    SearchHit,
    Task,
    TaskListStatus,
    TaskReminderRequest,
    TaskSnoozeRequest,
    TaskTimingConfirm,
    Topic,
    TopicCreate,
    TopicUpdate,
    UrlItemCreate,
)


APP_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)

app = FastAPI(title="Life Inbox")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

init_db()

_OPEN_API_PATHS = ("/api/health", "/api/auth/")


def _is_protected_api_path(path: str) -> bool:
    if not path.startswith("/api/"):
        return False
    return not any(
        path == open_path or path.startswith(open_path)
        for open_path in _OPEN_API_PATHS
    )


def _session_owner_id(request) -> Optional[int]:
    """Owner id from a valid signed session whose user still exists."""
    from app.auth import SESSION_COOKIE, parse_session_token
    from app.database import get_user_by_id

    token = request.cookies.get(SESSION_COOKIE)
    user_id = parse_session_token(token) if token else None
    if user_id is None or get_user_by_id(user_id) is None:
        return None
    return user_id


def _is_local_environment() -> bool:
    from app.config import load_config

    return load_config(strict=False).environment == "local"


@app.exception_handler(OwnerRequiredError)
async def owner_required_handler(request, exc):
    return JSONResponse(status_code=401, content={"detail": "Authentication required."})


@app.middleware("http")
async def bind_owner_from_session(request, call_next):
    from app.database import (
        get_or_create_default_owner_id,
        set_current_owner_id,
    )

    owner_id = _session_owner_id(request)
    if owner_id is None and _is_local_environment():
        # Single-user local mode: anonymous requests act as Local Owner.
        owner_id = get_or_create_default_owner_id()
    if owner_id is None and _is_protected_api_path(request.url.path):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required."},
        )
    set_current_owner_id(owner_id)
    try:
        response = await call_next(request)
    finally:
        set_current_owner_id(None)
    return response


@app.get("/api/health")
def health():
    from app.config import config_warnings, load_config

    try:
        config = load_config(strict=False)
        return {
            "status": "ok",
            "environment": config.environment,
            "database": "postgres" if config.is_postgres else "sqlite",
            "auth_mode": config.auth_mode,
            "warnings": config_warnings(config),
        }
    except Exception as exc:
        logger.exception("Health config check failed")
        return {"status": "degraded", "error": str(exc)}


@app.get("/api/auth/me")
def auth_me(request: Request):
    from app.database import get_or_create_default_owner_id, get_user_by_id

    user_id = _session_owner_id(request)
    if user_id is not None:
        return get_user_by_id(user_id)
    if not _is_local_environment():
        raise HTTPException(status_code=401, detail="Authentication required.")
    return get_user_by_id(get_or_create_default_owner_id())


@app.post("/api/auth/dev-login")
def auth_dev_login(payload: dict, response: Response):
    from app.auth import dev_login_user, set_session_cookie

    email = str(payload.get("email", "")).strip()
    display_name = payload.get("display_name")
    user = dev_login_user(email, display_name=display_name)
    set_session_cookie(response, user["id"])
    return user


@app.get("/api/auth/config")
def auth_config():
    """What the sign-in UI should offer. Contains no user data."""
    from app.auth import PASSWORD_MIN_LENGTH
    from app.config import load_config
    from app.google_auth import google_login_enabled

    config = load_config(strict=False)
    return {
        "environment": config.environment,
        "allow_dev_login": config.allow_dev_login,
        "password_login": True,
        "google_login": google_login_enabled(),
        "password_min_length": PASSWORD_MIN_LENGTH,
        "anonymous_local_owner": config.environment == "local",
    }


@app.post("/api/auth/register")
def auth_register(payload: dict, response: Response):
    from app.auth import register_password_user, set_session_cookie

    user = register_password_user(
        str(payload.get("email", "")),
        str(payload.get("password", "")),
        display_name=payload.get("display_name"),
    )
    set_session_cookie(response, user["id"])
    return user


@app.post("/api/auth/login")
def auth_login(payload: dict, response: Response):
    from app.auth import password_login_user, set_session_cookie

    user = password_login_user(
        str(payload.get("email", "")),
        str(payload.get("password", "")),
    )
    set_session_cookie(response, user["id"])
    return user


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    from app.auth import clear_session_cookie

    clear_session_cookie(response)
    return {"status": "logged_out"}


@app.get("/api/auth/google/start")
def auth_google_start(request: Request):
    """Send the browser to Google's account chooser."""
    from app import google_auth

    if not google_auth.google_login_enabled():
        raise HTTPException(
            status_code=501,
            detail=(
                "Google sign-in is not configured (OAuth client ID and secret "
                "are not set). Use email and password instead."
            ),
        )
    state = google_auth.new_state()
    callback_url = google_auth.redirect_uri(str(request.base_url))
    response = RedirectResponse(
        google_auth.authorization_url(state=state, callback_url=callback_url),
        status_code=302,
    )
    response.set_cookie(
        key=google_auth.STATE_COOKIE,
        value=state,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=google_auth.STATE_TTL_SECONDS,
        path="/api/auth/google",
    )
    return response


@app.get("/api/auth/google/callback")
def auth_google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Google sends the browser back here after the user picks an account."""
    from app import google_auth
    from app.auth import set_session_cookie

    def fail(message: str) -> RedirectResponse:
        response = RedirectResponse(
            "/?" + urlencode({"auth_error": message}), status_code=302
        )
        response.delete_cookie(google_auth.STATE_COOKIE, path="/api/auth/google")
        return response

    if not google_auth.google_login_enabled():
        return fail("Google sign-in is not configured.")
    if error:
        return fail("Google sign-in was cancelled.")
    expected_state = request.cookies.get(google_auth.STATE_COOKIE)
    if not google_auth.states_match(expected_state, state) or not code:
        return fail("Google sign-in expired. Try again.")

    try:
        profile = google_auth.fetch_google_profile(
            code=code,
            callback_url=google_auth.redirect_uri(str(request.base_url)),
        )
        user = google_auth.find_or_create_google_user(profile)
    except google_auth.GoogleLoginError as exc:
        return fail(str(exc))
    except Exception:
        logger.exception("Google sign-in failed")
        return fail("Google sign-in failed. Try again.")

    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(google_auth.STATE_COOKIE, path="/api/auth/google")
    set_session_cookie(response, user["id"])
    return response


def _process_url_item(item_id: int) -> dict:
    mark_item_processing(item_id)
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    try:
        fetched = fetch_url(item["source_url"])
        processed = complete_url_item_processing(
            item_id,
            title=fetched["title"],
            raw_text=fetched["raw_text"],
            mime_type=fetched.get("mime_type"),
            final_url=fetched.get("final_url"),
        )
        if processed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return processed
    except ValueError as exc:
        failed = fail_item_processing(item_id, str(exc))
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed
    except Exception as exc:
        logger.exception("URL processing failed")
        failed = fail_item_processing(
            item_id,
            "Unable to fetch or extract this URL.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed


def _process_pdf_item(item_id: int) -> dict:
    mark_item_processing(item_id)
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    storage_path = item.get("storage_path")
    if not storage_path:
        failed = fail_item_processing(
            item_id,
            "Stored PDF file is missing.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    try:
        data = read_stored_bytes(storage_path)
        extracted = extract_pdf_text(
            data,
            original_filename=item.get("original_filename"),
        )
        processed = complete_pdf_item_processing(
            item_id,
            title=extracted["title"],
            raw_text=extracted["raw_text"],
            extracted_text=extracted["extracted_text"],
            mime_type=extracted.get("mime_type"),
        )
        if processed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return processed
    except FileNotFoundError:
        failed = fail_item_processing(
            item_id,
            "Stored PDF file is missing.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    except ValueError as exc:
        failed = fail_item_processing(item_id, str(exc))
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed
    except Exception as exc:
        logger.exception("PDF processing failed")
        failed = fail_item_processing(
            item_id,
            "Unable to extract text from this PDF.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed


def _process_image_item(item_id: int) -> dict:
    mark_item_processing(item_id)
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    storage_path = item.get("storage_path")
    if not storage_path:
        failed = fail_item_processing(item_id, "Stored image file is missing.")
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    try:
        data = read_stored_bytes(storage_path)
        processed_payload = process_image_bytes(
            data,
            original_filename=item.get("original_filename") or "image.png",
            mime_type=item.get("mime_type") or "image/png",
        )
        store_thumbnail_bytes(storage_path, processed_payload["thumbnail_bytes"])
        processed = complete_image_item_processing(
            item_id,
            title=processed_payload["title"],
            raw_text=processed_payload["raw_text"],
            extracted_text=processed_payload["extracted_text"],
            ai_description=processed_payload["ai_description"],
            mime_type=processed_payload.get("mime_type"),
        )
        if processed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return processed
    except FileNotFoundError:
        failed = fail_item_processing(item_id, "Stored image file is missing.")
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    except ValueError as exc:
        failed = fail_item_processing(item_id, str(exc))
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed
    except Exception as exc:
        logger.exception("Image processing failed")
        failed = fail_item_processing(
            item_id,
            "Unable to process this image.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed


def _process_voice_item(item_id: int) -> dict:
    mark_item_processing(item_id)
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    storage_path = item.get("storage_path")
    if not storage_path:
        failed = fail_item_processing(item_id, "Stored audio file is missing.")
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    try:
        data = read_stored_bytes(storage_path)
        processed_payload = process_voice_bytes(
            data,
            original_filename=item.get("original_filename") or "voice-note.webm",
            mime_type=item.get("mime_type") or "audio/webm",
        )
        processed = complete_voice_item_processing(
            item_id,
            title=processed_payload["title"],
            raw_text=processed_payload["raw_text"],
            extracted_text=processed_payload["extracted_text"],
            mime_type=processed_payload.get("mime_type"),
        )
        if processed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return processed
    except FileNotFoundError:
        failed = fail_item_processing(item_id, "Stored audio file is missing.")
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return failed
    except ValueError as exc:
        failed = fail_item_processing(item_id, str(exc))
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed
    except Exception as exc:
        logger.exception("Voice processing failed")
        failed = fail_item_processing(
            item_id,
            "Unable to process this voice note.",
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Item not found.") from exc
        return failed


@app.post("/api/items", response_model=InboxItem)
def create_item(payload: InboxItemCreate):
    try:
        return add_item_to_db(payload.raw_text)
    except Exception as exc:
        logger.exception("Failed to save inbox item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save item. Please try again.",
        ) from exc


@app.post("/api/items/url", response_model=InboxItem)
def create_url_item(payload: UrlItemCreate):
    try:
        url = validate_public_http_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        item = add_url_item_to_db(url)
    except Exception as exc:
        logger.exception("Failed to save URL item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save URL. Please try again.",
        ) from exc

    return _process_url_item(item["id"])


@app.post("/api/items/pdf", response_model=InboxItem)
async def create_pdf_item(file: UploadFile = File(...)):
    data = await file.read()
    try:
        safe_filename = validate_pdf_upload(
            file.filename or "document.pdf",
            file.content_type,
            data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        storage_path = store_pdf_bytes(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to store PDF upload")
        raise HTTPException(
            status_code=500,
            detail="Unable to store PDF. Please try again.",
        ) from exc

    mime_type = (file.content_type or "application/pdf").split(";", 1)[0].strip()
    try:
        item = add_pdf_item_to_db(safe_filename, storage_path, mime_type)
    except Exception as exc:
        logger.exception("Failed to save PDF item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save PDF. Please try again.",
        ) from exc

    return _process_pdf_item(item["id"])


@app.post("/api/items/image", response_model=InboxItem)
async def create_image_item(file: UploadFile = File(...)):
    data = await file.read()
    try:
        safe_filename, detected_mime, extension = validate_image_upload(
            file.filename or "image.png",
            file.content_type,
            data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        storage_path = store_image_bytes(data, extension)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to store image upload")
        raise HTTPException(
            status_code=500,
            detail="Unable to store image. Please try again.",
        ) from exc

    mime_type = detected_mime
    if file.content_type:
        declared = file.content_type.split(";", 1)[0].strip().lower()
        if declared in {
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/webp",
            "image/gif",
        }:
            mime_type = declared
    try:
        item = add_image_item_to_db(safe_filename, storage_path, mime_type)
    except Exception as exc:
        logger.exception("Failed to save image item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save image. Please try again.",
        ) from exc

    return _process_image_item(item["id"])


@app.post("/api/items/voice", response_model=InboxItem)
async def create_voice_item(file: UploadFile = File(...)):
    data = await file.read()
    try:
        safe_filename, detected_mime, extension = validate_audio_upload(
            file.filename or "voice-note.webm",
            file.content_type,
            data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        storage_path = store_audio_bytes(data, extension)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to store voice upload")
        raise HTTPException(
            status_code=500,
            detail="Unable to store voice note. Please try again.",
        ) from exc

    mime_type = detected_mime
    if file.content_type:
        declared = file.content_type.split(";", 1)[0].strip().lower()
        if declared in {
            "audio/webm",
            "audio/wav",
            "audio/x-wav",
            "audio/wave",
            "audio/mpeg",
            "audio/mp3",
            "audio/mp4",
            "audio/m4a",
            "audio/x-m4a",
            "audio/ogg",
            "video/webm",
        }:
            mime_type = declared if declared != "video/webm" else "audio/webm"
    try:
        item = add_voice_item_to_db(safe_filename, storage_path, mime_type)
    except Exception as exc:
        logger.exception("Failed to save voice item")
        raise HTTPException(
            status_code=500,
            detail="Unable to save voice note. Please try again.",
        ) from exc

    return _process_voice_item(item["id"])


@app.get("/api/items/{item_id}/file")
def get_item_source_file(
    item_id: int,
    variant: Optional[str] = Query(None, max_length=20),
):
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    if item["item_type"] not in {"pdf", "image", "voice"} or not item.get(
        "storage_path"
    ):
        raise HTTPException(
            status_code=404,
            detail="No stored file for this item.",
        )
    relative = item["storage_path"]
    media_type = item.get("mime_type") or "application/octet-stream"
    filename = item.get("original_filename") or "download"
    if variant == "thumb" and item["item_type"] == "image":
        relative = thumbnail_relative_path(item["storage_path"])
        media_type = "image/jpeg"
        filename = f"thumb_{Path(filename).stem}.jpg"
    try:
        path = resolve_storage_path(relative)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Stored file not found.") from exc
    if item["item_type"] == "pdf" and not media_type:
        media_type = "application/pdf"
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
    )


@app.patch("/api/items/{item_id}/extracted-text", response_model=InboxItem)
def patch_extracted_text(item_id: int, payload: ExtractedTextUpdate):
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    if item["item_type"] not in {"image", "voice", "pdf"}:
        raise HTTPException(
            status_code=400,
            detail="Extracted text can only be edited for image, voice, or PDF items.",
        )
    updated = update_item_extracted_text(item_id, payload.extracted_text)
    if updated is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    return updated


@app.post("/api/items/{item_id}/retry", response_model=InboxItem)
def retry_item_processing(item_id: int):
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    if item["item_type"] not in {"url", "pdf", "image", "voice"}:
        raise HTTPException(
            status_code=400,
            detail="Only capture items (URL/PDF/image/voice) can be retried here.",
        )
    if item["processing_status"] == "ready":
        return item
    if item["item_type"] == "url":
        return _process_url_item(item_id)
    if item["item_type"] == "pdf":
        return _process_pdf_item(item_id)
    if item["item_type"] == "image":
        return _process_image_item(item_id)
    return _process_voice_item(item_id)


@app.get("/api/items", response_model=List[InboxItem])
def get_items(
    search: Optional[str] = Query(None, alias="q", max_length=200),
    item_type: Optional[str] = Query(None, max_length=100),
    category: Optional[str] = Query(None, max_length=100),
    priority: Optional[Priority] = Query(None),
    processing_status: Optional[str] = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    try:
        return list_items_from_db(
            search=search,
            item_type=item_type,
            category=category,
            priority=priority,
            processing_status=processing_status,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.exception("Failed to load inbox items")
        raise HTTPException(
            status_code=500,
            detail="Unable to load items. Please try again.",
        ) from exc


@app.get("/api/items/{item_id}", response_model=InboxItem)
def read_item(item_id: int):
    item = get_item_from_db(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    return item


@app.put("/api/items/{item_id}", response_model=InboxItem)
def update_item(item_id: int, payload: InboxItemUpdate):
    try:
        item = update_item_in_db(item_id, payload.raw_text)
    except Exception as exc:
        logger.exception("Failed to update inbox item")
        raise HTTPException(
            status_code=500,
            detail="Unable to update item. Please try again.",
        ) from exc

    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    return item


@app.delete(
    "/api/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_item(item_id: int):
    try:
        deleted = delete_item_from_db(item_id)
    except Exception as exc:
        logger.exception("Failed to delete inbox item")
        raise HTTPException(
            status_code=500,
            detail="Unable to delete item. Please try again.",
        ) from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/notes", response_model=Note, deprecated=True)
def create_note(payload: NoteCreate):
    try:
        return add_note_to_db(payload.text)
    except Exception as exc:
        logger.exception("Failed to save note")
        raise HTTPException(
            status_code=500,
            detail="Unable to save note. Please try again.",
        ) from exc


@app.get("/api/notes", response_model=List[Note], deprecated=True)
def get_notes():
    try:
        return list_notes_from_db()
    except Exception as exc:
        logger.exception("Failed to load notes")
        raise HTTPException(
            status_code=500,
            detail="Unable to load notes. Please try again.",
        ) from exc


@app.put("/api/notes/{note_id}", response_model=Note, deprecated=True)
def update_note(note_id: int, payload: NoteUpdate):
    try:
        note = update_note_in_db(note_id, payload.text)
    except Exception as exc:
        logger.exception("Failed to update note")
        raise HTTPException(
            status_code=500,
            detail="Unable to update note. Please try again.",
        ) from exc

    if note is None:
        raise HTTPException(status_code=404, detail="Note not found.")
    return note


@app.delete(
    "/api/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    deprecated=True,
)
def delete_note(note_id: int):
    try:
        deleted = delete_note_from_db(note_id)
    except Exception as exc:
        logger.exception("Failed to delete note")
        raise HTTPException(
            status_code=500,
            detail="Unable to delete note. Please try again.",
        ) from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/tasks", response_model=List[Task])
def get_tasks(
    task_status: TaskListStatus = Query("open", alias="status"),
):
    try:
        return list_tasks_from_db(task_status)
    except Exception as exc:
        logger.exception("Failed to load tasks")
        raise HTTPException(
            status_code=500,
            detail="Unable to load tasks. Please try again.",
        ) from exc


def _transition_task(task_id: int, task_status: str):
    try:
        task = set_task_status(task_id, task_status)
    except Exception as exc:
        logger.exception("Failed to update task status")
        raise HTTPException(
            status_code=500,
            detail="Unable to update task. Please try again.",
        ) from exc

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.post("/api/tasks/{task_id}/complete", response_model=Task)
def complete_task(task_id: int):
    return _transition_task(task_id, "completed")


@app.post("/api/tasks/{task_id}/reopen", response_model=Task)
def reopen_task(task_id: int):
    return _transition_task(task_id, "open")


@app.post("/api/tasks/{task_id}/dismiss", response_model=Task)
def dismiss_task(task_id: int):
    return _transition_task(task_id, "dismissed")


@app.post("/api/tasks/{task_id}/confirm-timing", response_model=Task)
def confirm_timing(task_id: int, payload: TaskTimingConfirm):
    try:
        task = confirm_task_timing(task_id, payload.timing_text)
    except Exception as exc:
        logger.exception("Failed to confirm task timing")
        raise HTTPException(
            status_code=500,
            detail="Unable to confirm task timing. Please try again.",
        ) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.post("/api/tasks/{task_id}/snooze", response_model=Task)
def snooze_task(task_id: int, payload: TaskSnoozeRequest):
    try:
        task = snooze_task_in_db(task_id, payload.until.strip())
    except Exception as exc:
        logger.exception("Failed to snooze task")
        raise HTTPException(
            status_code=500,
            detail="Unable to snooze task. Please try again.",
        ) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.post("/api/tasks/{task_id}/reminder", response_model=Task)
def set_task_reminder(task_id: int, payload: TaskReminderRequest):
    try:
        task = set_task_reminder_in_db(task_id, payload.reminder_at.strip())
    except Exception as exc:
        logger.exception("Failed to set reminder")
        raise HTTPException(
            status_code=500,
            detail="Unable to set reminder. Please try again.",
        ) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.get("/api/attention")
def attention_board():
    try:
        return get_attention_board()
    except Exception as exc:
        logger.exception("Failed to load attention board")
        raise HTTPException(
            status_code=500,
            detail="Unable to load attention board. Please try again.",
        ) from exc


@app.get("/api/briefing")
def daily_briefing():
    try:
        return get_daily_briefing()
    except Exception as exc:
        logger.exception("Failed to load daily briefing")
        raise HTTPException(
            status_code=500,
            detail="Unable to load daily briefing. Please try again.",
        ) from exc


@app.get("/api/calendar/status")
def calendar_status():
    adapter = get_calendar_adapter()
    status = adapter.status()
    return {
        "provider": status.provider,
        "configured": status.configured,
        "oauth_connected": status.oauth_connected,
        "writes_enabled": status.writes_enabled,
        "mode": status.mode,
        "message": status.message,
    }


@app.post("/api/calendar/preview")
def calendar_preview(payload: CalendarPreviewRequest):
    from datetime import date as date_cls

    from app.attention.dates import configured_timezone, parse_timing_phrase

    task = None
    for candidate in list_tasks_from_db(status_filter="all"):
        if candidate["id"] == payload.task_id:
            task = candidate
            break
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    title = (payload.title or task["text"]).strip()
    if payload.start_date:
        try:
            start = date_cls.fromisoformat(payload.start_date.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="start_date must be YYYY-MM-DD.",
            ) from exc
    elif task.get("due_on"):
        start = date_cls.fromisoformat(task["due_on"])
    else:
        parsed = parse_timing_phrase(task.get("timing_text"))
        if parsed.due_date is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Task has no normalized date. Confirm timing before "
                    "previewing a calendar event."
                ),
            )
        start = parsed.due_date

    if not task.get("timing_confirmed"):
        parsed = parse_timing_phrase(task.get("timing_text"))
        if parsed.needs_confirmation:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Confirm the task date before creating a calendar preview. "
                    "Ambiguous timing requires explicit confirmation."
                ),
            )

    adapter = get_calendar_adapter()
    draft = adapter.preview_event(
        task_id=task["id"],
        title=title,
        start_date=start,
        description=payload.description or "",
        timezone_name=str(configured_timezone()),
    )
    store_draft(draft, require_owner_id())
    return {
        "draft_id": draft.draft_id,
        "task_id": draft.task_id,
        "title": draft.title,
        "start_date": draft.start_date,
        "end_date": draft.end_date,
        "description": draft.description,
        "timezone": draft.timezone_name,
        "provider": draft.provider,
        "status": draft.status,
        "confirmation_required": draft.confirmation_required,
        "notes": draft.notes,
    }


@app.post("/api/calendar/confirm")
def calendar_confirm(payload: CalendarConfirmRequest):
    owner_id = require_owner_id()
    draft = get_draft(payload.draft_id, owner_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail="Calendar draft not found. Create a preview first.",
        )
    adapter = get_calendar_adapter()
    try:
        confirmed = adapter.confirm_event(draft)
    except CalendarWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CalendarConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Calendar confirm failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to confirm calendar action.",
        ) from exc

    try:
        receipt = save_calendar_receipt(
            draft_id=confirmed.draft_id,
            task_id=confirmed.task_id,
            provider=confirmed.provider,
            status=confirmed.status,
            payload={
                "title": confirmed.title,
                "start_date": confirmed.start_date,
                "end_date": confirmed.end_date,
                "timezone": confirmed.timezone_name,
                "notes": confirmed.notes,
                "external_event_id": confirmed.external_event_id,
                "external_link": confirmed.external_link,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Task not found.") from exc
    store_draft(confirmed, owner_id)
    return {
        "draft_id": confirmed.draft_id,
        "task_id": confirmed.task_id,
        "status": confirmed.status,
        "provider": confirmed.provider,
        "notes": confirmed.notes,
        "link": confirmed.external_link,
        "receipt": receipt,
    }


# ---------- Settings: bring-your-own AI ----------

def _ai_settings_view(owner_id: int) -> dict:
    from app.ai_provider import PRESETS, resolve_ai_config
    from app.database import get_user_settings
    from app.secret_box import decrypt_secret, key_hint

    settings = get_user_settings(owner_id)
    provider = settings.get("ai_provider")
    preset = PRESETS.get(provider or "", {})
    active = resolve_ai_config()
    return {
        "provider": provider,
        "base_url": settings.get("ai_base_url") or preset.get("base_url"),
        "model": settings.get("ai_model") or preset.get("model"),
        "has_key": bool(settings.get("ai_api_key_enc")),
        "key_hint": key_hint(decrypt_secret(settings.get("ai_api_key_enc"))),
        "active": (
            {"source": active.source, "label": active.label, "model": active.model}
            if active
            else {"source": "none", "label": "Built-in rules (no AI)", "model": None}
        ),
    }


@app.get("/api/settings")
def get_settings():
    from app.ai_provider import PRESETS
    from app.integrations.google_calendar import connection_status

    owner_id = require_owner_id()
    return {
        "ai": _ai_settings_view(owner_id),
        "presets": [
            {
                "id": key,
                "label": value["label"],
                "base_url": value["base_url"],
                "model": value["model"],
                "needs_key": value["needs_key"],
                "key_help": value["key_help"],
            }
            for key, value in PRESETS.items()
        ],
        "calendar": connection_status(owner_id),
    }


@app.put("/api/settings/ai")
def save_ai_settings(payload: dict):
    from app.ai_provider import PRESETS, validate_base_url
    from app.database import get_user_settings, update_user_settings
    from app.secret_box import encrypt_secret

    owner_id = require_owner_id()
    provider = str(payload.get("provider") or "").strip()
    if provider not in PRESETS:
        raise HTTPException(status_code=400, detail="Choose an AI provider.")
    preset = PRESETS[provider]
    base_url = str(payload.get("base_url") or preset["base_url"]).strip()[:500]
    model = str(payload.get("model") or preset["model"]).strip()[:200]
    if not base_url:
        raise HTTPException(status_code=400, detail="Enter the provider's base URL.")
    if not model:
        raise HTTPException(status_code=400, detail="Enter a model name.")
    try:
        base_url = validate_base_url(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    changes = {"ai_provider": provider, "ai_base_url": base_url, "ai_model": model}
    api_key = payload.get("api_key")
    if isinstance(api_key, str) and api_key.strip():
        key = api_key.strip()
        if len(key) > 500:
            raise HTTPException(status_code=400, detail="That API key is too long.")
        changes["ai_api_key_enc"] = encrypt_secret(key)
    elif payload.get("clear_key"):
        changes["ai_api_key_enc"] = None

    current = get_user_settings(owner_id)
    has_key = bool(changes.get("ai_api_key_enc", current.get("ai_api_key_enc")))
    if preset["needs_key"] and not has_key:
        raise HTTPException(
            status_code=400, detail=f"Paste your {preset['label']} API key."
        )
    update_user_settings(owner_id, **changes)
    return _ai_settings_view(owner_id)


@app.delete("/api/settings/ai")
def delete_ai_settings():
    from app.database import update_user_settings

    owner_id = require_owner_id()
    update_user_settings(
        owner_id, ai_provider=None, ai_base_url=None, ai_model=None, ai_api_key_enc=None
    )
    return _ai_settings_view(owner_id)


@app.post("/api/settings/ai/test")
def test_ai_settings():
    from app.ai_provider import AIProviderError, check_connection, user_ai_config

    owner_id = require_owner_id()
    config = user_ai_config(owner_id)
    if config is None:
        raise HTTPException(status_code=400, detail="Save a provider and key first.")
    try:
        reply = check_connection(config)
    except (AIProviderError, ValueError) as exc:
        return {"ok": False, "message": str(exc)}
    except Exception:
        logger.exception("AI connection test failed")
        return {"ok": False, "message": f"Could not connect to {config.label}."}
    return {
        "ok": True,
        "message": f"Connected to {config.label} ({config.model}).",
        "reply": reply,
    }


# ---------- Settings: Google Calendar ----------

def _calendar_redirect(status_key: str, message: str = "") -> RedirectResponse:
    from app.integrations.google_calendar import STATE_COOKIE, STATE_COOKIE_PATH

    query = {"calendar": status_key}
    if message:
        query["calendar_message"] = message
    response = RedirectResponse("/?" + urlencode(query) + "#settings", status_code=302)
    response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)
    return response


@app.get("/api/integrations/google-calendar/connect")
def google_calendar_connect(request: Request):
    from app.database import get_user_by_id
    from app.google_auth import new_state
    from app.integrations import google_calendar as gcal

    owner_id = require_owner_id()
    if not gcal.google_calendar_available():
        raise HTTPException(
            status_code=501,
            detail="Google Calendar is not set up on this server yet "
            "(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET).",
        )
    state = new_state()
    user = get_user_by_id(owner_id) or {}
    callback_url = gcal.redirect_uri(str(request.base_url))
    response = RedirectResponse(
        gcal.authorization_url(
            state=state, callback_url=callback_url, login_hint=user.get("email", "")
        ),
        status_code=302,
    )
    # Bind the state to this user so a different account cannot finish the flow.
    response.set_cookie(
        key=gcal.STATE_COOKIE,
        value=f"{state}.{owner_id}",
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=10 * 60,
        path=gcal.STATE_COOKIE_PATH,
    )
    return response


@app.get("/api/integrations/google-calendar/callback")
def google_calendar_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    from app.database import get_current_owner_id
    from app.google_auth import states_match
    from app.integrations import google_calendar as gcal

    owner_id = get_current_owner_id()
    if owner_id is None:
        return _calendar_redirect("error", "Sign in again, then reconnect your calendar.")
    if error:
        return _calendar_redirect("error", "Calendar connection was cancelled.")
    cookie = request.cookies.get(gcal.STATE_COOKIE, "")
    expected_state, _, cookie_owner = cookie.rpartition(".")
    if (
        not states_match(expected_state, state)
        or cookie_owner != str(owner_id)
        or not code
    ):
        return _calendar_redirect("error", "Calendar connection expired. Try again.")
    try:
        gcal.connect_with_code(
            owner_id, code=code, callback_url=gcal.redirect_uri(str(request.base_url))
        )
    except gcal.CalendarConnectionError as exc:
        return _calendar_redirect("error", str(exc))
    except Exception:
        logger.exception("Google Calendar connect failed")
        return _calendar_redirect("error", "Could not connect Google Calendar.")
    return _calendar_redirect("connected")


@app.post("/api/integrations/google-calendar/disconnect")
def google_calendar_disconnect():
    from app.integrations.google_calendar import connection_status, disconnect

    owner_id = require_owner_id()
    disconnect(owner_id)
    return connection_status(owner_id)


@app.get("/api/topics", response_model=List[Topic])
def get_topics(include_archived: bool = Query(False)):
    try:
        return list_topics_from_db(include_archived=include_archived)
    except Exception as exc:
        logger.exception("Failed to load topics")
        raise HTTPException(
            status_code=500,
            detail="Unable to load topics. Please try again.",
        ) from exc


@app.post("/api/topics", response_model=Topic)
def create_topic(payload: TopicCreate):
    try:
        return create_topic_in_db(payload.name.strip(), payload.description)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to create topic")
        raise HTTPException(
            status_code=500,
            detail="Unable to create topic. Please try again.",
        ) from exc


@app.patch("/api/topics/{topic_id}", response_model=Topic)
def patch_topic(topic_id: int, payload: TopicUpdate):
    try:
        topic = update_topic_in_db(
            topic_id,
            name=payload.name.strip() if payload.name else None,
            description=payload.description,
            archived=payload.archived,
        )
    except Exception as exc:
        logger.exception("Failed to update topic")
        raise HTTPException(
            status_code=500,
            detail="Unable to update topic. Please try again.",
        ) from exc
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found.")
    return topic


@app.get("/api/items/{item_id}/insight", response_model=ItemInsight)
def read_item_insight(item_id: int):
    try:
        insight = get_item_insight(item_id)
    except Exception as exc:
        logger.exception("Failed to load item insight")
        raise HTTPException(
            status_code=500,
            detail="Unable to load insight. Please try again.",
        ) from exc
    if insight is None:
        raise HTTPException(status_code=404, detail="Insight not found.")
    return insight


@app.patch("/api/items/{item_id}/insight", response_model=ItemInsight)
def patch_item_insight(item_id: int, payload: InsightOverrideUpdate):
    try:
        insight = update_item_insight_overrides(
            item_id,
            user_title=payload.user_title,
            user_topic_id=payload.user_topic_id,
            user_priority=payload.user_priority,
            user_tags=payload.user_tags,
            clear_overrides=payload.clear_overrides,
            needs_review=payload.needs_review,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to update item insight")
        raise HTTPException(
            status_code=500,
            detail="Unable to update insight. Please try again.",
        ) from exc
    if insight is None:
        raise HTTPException(status_code=404, detail="Insight not found.")
    return insight


@app.get("/api/relations", response_model=List[ItemRelation])
def get_relations(include_dismissed: bool = Query(False)):
    try:
        return list_relations_from_db(include_dismissed=include_dismissed)
    except Exception as exc:
        logger.exception("Failed to load relations")
        raise HTTPException(
            status_code=500,
            detail="Unable to load related items. Please try again.",
        ) from exc


@app.post("/api/relations/{relation_id}/dismiss", response_model=ItemRelation)
def dismiss_relation(relation_id: int):
    try:
        relation = dismiss_relation_in_db(relation_id)
    except Exception as exc:
        logger.exception("Failed to dismiss relation")
        raise HTTPException(
            status_code=500,
            detail="Unable to dismiss relation. Please try again.",
        ) from exc
    if relation is None:
        raise HTTPException(status_code=404, detail="Relation not found.")
    return relation


@app.get("/api/search", response_model=list[SearchHit])
def search_inbox(
    q: str = Query(..., min_length=1, max_length=200),
    item_type: Optional[str] = Query(None, max_length=100),
    limit: int = Query(8, ge=1, le=25),
):
    try:
        ranked = search_passages(
            q,
            limit=limit,
            item_type=item_type,
        )
    except Exception as exc:
        logger.exception("Search failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to search inbox. Please try again.",
        ) from exc
    return [
        SearchHit(
            item_id=row.passage.item_id,
            item_type=row.passage.item_type,
            title=row.passage.title,
            excerpt=row.passage.passage[:320],
            source_kind=row.passage.source_kind,
            preview_url=row.passage.preview_url,
            score=round(row.score, 4),
            keyword_score=round(row.keyword_score, 4),
            semantic_score=round(row.semantic_score, 4),
        )
        for row in ranked
    ]


@app.post("/api/ask", response_model=AskResponse)
def ask_my_inbox(payload: AskRequest):
    try:
        return build_grounded_answer(
            payload.question.strip(),
            item_type=payload.item_type,
        )
    except Exception as exc:
        logger.exception("Ask My Inbox failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to answer from your inbox. Please try again.",
        ) from exc


@app.get("/api/dashboard")
def organization_dashboard():
    try:
        return get_organization_dashboard()
    except Exception as exc:
        logger.exception("Failed to load organization dashboard")
        raise HTTPException(
            status_code=500,
            detail="Unable to load dashboard. Please try again.",
        ) from exc


@app.get(
    "/api/analyze/latest",
    response_model=PersistedAnalysis,
)
def get_latest_analysis():
    try:
        result = get_latest_successful_analysis()
    except Exception as exc:
        logger.exception("Failed to load latest analysis")
        raise HTTPException(
            status_code=500,
            detail="Unable to load the latest analysis. Please try again.",
        ) from exc

    if result is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return result


@app.post("/api/analyze", response_model=PersistedAnalysis)
def analyze_inbox():
    run_id = None
    try:
        run_id = start_analysis_run()
        notes = list_notes_from_db()
        raw_result = analyze_inbox_with_openai(notes)
        result = validate_analysis_result(raw_result, notes)
        return complete_analysis_run(run_id, result)
    except Exception as exc:
        if run_id is not None:
            try:
                fail_analysis_run(run_id)
            except Exception:
                logger.exception("Failed to mark analysis run as failed")
        logger.exception("Failed to analyze inbox")
        raise HTTPException(
            status_code=500,
            detail="Unable to analyze inbox. Please try again.",
        ) from exc


@app.get("/", response_class=HTMLResponse)
def index():
    return (APP_DIR / "templates" / "index.html").read_text(encoding="utf-8")
