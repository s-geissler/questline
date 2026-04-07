import json
import logging
import time
import threading
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List as PyList, Union

import models
from database import engine, SessionLocal, get_db
from authz import (
    CSRF_COOKIE,
    _authorize_board_request,
    _board_id_for_automation,
    _board_id_for_saved_filter,
    _board_id_for_stage,
    _board_id_for_task,
    _board_id_for_task_type,
    _boards_for_nav,
    _board_role_map,
    _board_shared_map,
    _clear_session_cookie,
    _hash_csrf_token,
    _hash_session_token,
    _normalize_email,
    _owner_membership_count,
    _require_stage_in_board,
    _require_task_in_board,
    _require_task_type_in_board,
    _set_session_cookie,
    board_is_shared,
    board_membership_to_dict,
    require_admin,
    claim_legacy_boards_for_first_user,
    create_user_session,
    ensure_board_membership,
    get_accessible_boards,
    get_board_membership,
    get_board_role,
    get_optional_current_user,
    hash_password,
    login_redirect_response,
    require_board_access,
    require_current_user,
    user_to_dict,
    validate_runtime_security_config,
    verify_password,
)
from filters_logic import (
    _task_matches_filter,
    _validated_filter_definition,
    default_filter_definition,
    get_stage_tasks,
    parse_filter_definition,
    saved_filter_to_dict,
    stage_to_dict,
)

# ---------------------------------------------------------------------------
# Schema migrations (add board_id columns to existing tables if missing)
# ---------------------------------------------------------------------------
logger = logging.getLogger("questline.app")
LOGIN_WINDOW_SECONDS = 60
LOGIN_MAX_ATTEMPTS = 5
login_attempt_lock = threading.Lock()
login_attempts = defaultdict(deque)


def _run_column_migrations():
    migrations = [
        ("boards",           "owner_user_id", "INTEGER REFERENCES users(id)"),
        ("lists",       "board_id", "INTEGER REFERENCES boards(id)"),
        ("task_types",  "board_id", "INTEGER REFERENCES boards(id)"),
        ("automations", "board_id", "INTEGER REFERENCES boards(id)"),
        ("boards",           "color",   "VARCHAR"),
        ("task_types",       "color",   "VARCHAR"),
        ("task_types",       "show_description_on_card", "BOOLEAN"),
        ("task_types",       "show_checklist_on_card", "BOOLEAN"),
        ("lists",            "row", "INTEGER"),
        ("lists",            "is_log", "BOOLEAN"),
        ("lists",            "filter_id", "INTEGER REFERENCES saved_filters(id)"),
        ("tasks",            "color",   "VARCHAR"),
        ("tasks",            "due_date", "VARCHAR"),
        ("tasks",            "parent_task_id", "INTEGER REFERENCES tasks(id)"),
        ("tasks",            "assignee_user_id", "INTEGER REFERENCES users(id)"),
        ("tasks",            "show_description_on_card", "BOOLEAN"),
        ("tasks",            "show_checklist_on_card", "BOOLEAN"),
        ("automations",      "action_task_type_id", "INTEGER REFERENCES task_types(id)"),
        ("automations",      "action_color", "VARCHAR"),
        ("automations",      "action_days_offset", "INTEGER"),
        ("custom_field_defs", "options", "TEXT"),
        ("custom_field_defs", "color",   "VARCHAR"),
        ("board_memberships", "role", "VARCHAR"),
        ("users", "role", "VARCHAR"),
        ("users", "is_active", "BOOLEAN"),
        ("instance_settings", "key", "VARCHAR"),
        ("instance_settings", "value", "TEXT"),
        ("task_recurrences", "mode", "VARCHAR"),
        ("user_sessions", "csrf_token_hash", "VARCHAR"),
    ]
    with engine.begin() as conn:
        for table, col, col_type in migrations:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            if rows and col not in [r[1] for r in rows]:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))


def _run_index_migrations():
    indexes = [
        ("ix_boards_position", "CREATE INDEX IF NOT EXISTS ix_boards_position ON boards(position)"),
        ("ix_boards_owner_user_id", "CREATE INDEX IF NOT EXISTS ix_boards_owner_user_id ON boards(owner_user_id)"),
        ("ix_lists_board_row_position", "CREATE INDEX IF NOT EXISTS ix_lists_board_row_position ON lists(board_id, row, position)"),
        ("ix_lists_board_position", "CREATE INDEX IF NOT EXISTS ix_lists_board_position ON lists(board_id, position)"),
        ("ix_lists_filter_id", "CREATE INDEX IF NOT EXISTS ix_lists_filter_id ON lists(filter_id)"),
        ("ix_saved_filters_board_id", "CREATE INDEX IF NOT EXISTS ix_saved_filters_board_id ON saved_filters(board_id)"),
        ("ix_user_sessions_token_hash", "CREATE INDEX IF NOT EXISTS ix_user_sessions_token_hash ON user_sessions(token_hash)"),
        ("ix_user_sessions_user_id", "CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions(user_id)"),
        ("ix_board_memberships_board_user", "CREATE INDEX IF NOT EXISTS ix_board_memberships_board_user ON board_memberships(board_id, user_id)"),
        ("ix_board_memberships_user_id", "CREATE INDEX IF NOT EXISTS ix_board_memberships_user_id ON board_memberships(user_id)"),
        ("ix_board_memberships_board_role", "CREATE INDEX IF NOT EXISTS ix_board_memberships_board_role ON board_memberships(board_id, role)"),
        ("ix_task_types_board_id", "CREATE INDEX IF NOT EXISTS ix_task_types_board_id ON task_types(board_id)"),
        ("ix_task_types_spawn_stage_id", "CREATE INDEX IF NOT EXISTS ix_task_types_spawn_stage_id ON task_types(spawn_list_id)"),
        ("ix_custom_field_defs_task_type_id", "CREATE INDEX IF NOT EXISTS ix_custom_field_defs_task_type_id ON custom_field_defs(task_type_id)"),
        ("ix_tasks_stage_position", "CREATE INDEX IF NOT EXISTS ix_tasks_stage_position ON tasks(list_id, position)"),
        ("ix_tasks_task_type_id", "CREATE INDEX IF NOT EXISTS ix_tasks_task_type_id ON tasks(task_type_id)"),
        ("ix_tasks_parent_task_id", "CREATE INDEX IF NOT EXISTS ix_tasks_parent_task_id ON tasks(parent_task_id)"),
        ("ix_tasks_assignee_user_id", "CREATE INDEX IF NOT EXISTS ix_tasks_assignee_user_id ON tasks(assignee_user_id)"),
        ("ix_tasks_done", "CREATE INDEX IF NOT EXISTS ix_tasks_done ON tasks(done)"),
        ("ix_tasks_due_date", "CREATE INDEX IF NOT EXISTS ix_tasks_due_date ON tasks(due_date)"),
        ("ix_tasks_created_at", "CREATE INDEX IF NOT EXISTS ix_tasks_created_at ON tasks(created_at)"),
        ("ix_custom_field_values_task_field", "CREATE INDEX IF NOT EXISTS ix_custom_field_values_task_field ON custom_field_values(task_id, field_def_id)"),
        ("ix_custom_field_values_field_def_id", "CREATE INDEX IF NOT EXISTS ix_custom_field_values_field_def_id ON custom_field_values(field_def_id)"),
        ("ix_checklist_items_task_id", "CREATE INDEX IF NOT EXISTS ix_checklist_items_task_id ON checklist_items(task_id)"),
        ("ix_checklist_items_spawned_task_id", "CREATE INDEX IF NOT EXISTS ix_checklist_items_spawned_task_id ON checklist_items(spawned_task_id)"),
        ("ix_automations_board_enabled_trigger", "CREATE INDEX IF NOT EXISTS ix_automations_board_enabled_trigger ON automations(board_id, enabled, trigger_type)"),
        ("ix_automations_trigger_stage_id", "CREATE INDEX IF NOT EXISTS ix_automations_trigger_stage_id ON automations(trigger_list_id)"),
        ("ix_automations_action_stage_id", "CREATE INDEX IF NOT EXISTS ix_automations_action_stage_id ON automations(action_list_id)"),
        ("ix_users_is_active", "CREATE INDEX IF NOT EXISTS ix_users_is_active ON users(is_active)"),
        ("uq_board_memberships_board_user", "CREATE UNIQUE INDEX IF NOT EXISTS uq_board_memberships_board_user ON board_memberships(board_id, user_id)"),
        ("ix_notifications_user_read_created", "CREATE INDEX IF NOT EXISTS ix_notifications_user_read_created ON notifications(user_id, read_at, created_at)"),
        ("ix_notifications_dedupe_key", "CREATE UNIQUE INDEX IF NOT EXISTS ix_notifications_dedupe_key ON notifications(dedupe_key) WHERE dedupe_key IS NOT NULL"),
        ("ix_task_recurrences_next_run_on", "CREATE INDEX IF NOT EXISTS ix_task_recurrences_next_run_on ON task_recurrences(enabled, next_run_on)"),
        ("ix_task_recurrences_spawn_stage_id", "CREATE INDEX IF NOT EXISTS ix_task_recurrences_spawn_stage_id ON task_recurrences(spawn_stage_id)"),
        ("uq_task_recurrences_task_id", "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_recurrences_task_id ON task_recurrences(task_id)"),
    ]
    with engine.begin() as conn:
        for _, sql in indexes:
            conn.execute(text(sql))


def _migrate_orphan_data():
    """Assign any pre-existing stages/task_types/automations to a default board."""
    db = SessionLocal()
    try:
        has_orphans = (
            db.query(models.Stage).filter(models.Stage.board_id.is_(None)).count() > 0
            or db.query(models.TaskType).filter(models.TaskType.board_id.is_(None)).count() > 0
            or db.query(models.Automation).filter(models.Automation.board_id.is_(None)).count() > 0
        )
        if has_orphans:
            pos = db.query(models.Board).count()
            board = models.Board(name="My Board", position=pos)
            db.add(board)
            db.flush()
            db.query(models.Stage).filter(models.Stage.board_id.is_(None)).update({"board_id": board.id})
            db.query(models.TaskType).filter(models.TaskType.board_id.is_(None)).update({"board_id": board.id})
            db.query(models.Automation).filter(models.Automation.board_id.is_(None)).update({"board_id": board.id})
        db.query(models.Stage).filter(models.Stage.is_log.is_(None)).update({"is_log": False})
        db.query(models.Stage).filter(models.Stage.row.is_(None)).update({"row": 0})
        db.commit()
    finally:
        db.close()


def _migrate_board_memberships():
    db = SessionLocal()
    try:
        owner_rows = (
            db.query(models.Board)
            .filter(models.Board.owner_user_id.is_not(None))
            .all()
        )
        for board in owner_rows:
            existing = (
                db.query(models.BoardMembership)
                .filter(
                    models.BoardMembership.board_id == board.id,
                    models.BoardMembership.user_id == board.owner_user_id,
                )
                .first()
            )
            if not existing:
                db.add(
                    models.BoardMembership(
                        board_id=board.id,
                        user_id=board.owner_user_id,
                        role="owner",
                    )
                )
        db.commit()
    finally:
        db.close()


def _migrate_admin_role():
    db = SessionLocal()
    try:
        db.query(models.User).filter(models.User.role.is_(None)).update({"role": "user"})
        db.query(models.User).filter(models.User.is_active.is_(None)).update({"is_active": True})
        admin_count = db.query(models.User).filter(models.User.role == "admin").count()
        if admin_count == 0:
            first_user = db.query(models.User).order_by(models.User.id).first()
            if first_user:
                first_user.role = "admin"
        db.commit()
    finally:
        db.close()


def _dedupe_board_memberships():
    db = SessionLocal()
    try:
        duplicate_pairs = (
            db.query(
                models.BoardMembership.board_id,
                models.BoardMembership.user_id,
                func.count(models.BoardMembership.id),
            )
            .group_by(models.BoardMembership.board_id, models.BoardMembership.user_id)
            .having(func.count(models.BoardMembership.id) > 1)
            .all()
        )
        for board_id, user_id, _ in duplicate_pairs:
            memberships = (
                db.query(models.BoardMembership)
                .filter(
                    models.BoardMembership.board_id == board_id,
                    models.BoardMembership.user_id == user_id,
                )
                .order_by(models.BoardMembership.id.asc())
                .all()
            )
            keeper = memberships[0]
            preferred_role = next((m.role for m in memberships if m.role == "owner"), None) or next(
                (m.role for m in memberships if m.role == "editor"),
                None,
            ) or keeper.role
            keeper.role = preferred_role
            for membership in memberships[1:]:
                db.delete(membership)
        db.commit()
    finally:
        db.close()


models.Base.metadata.create_all(bind=engine)
_run_column_migrations()
_migrate_orphan_data()
_migrate_board_memberships()
_migrate_admin_role()
_dedupe_board_memberships()
_run_index_migrations()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
SESSION_COOKIE = "questline_session"
PASSWORD_HASH_ITERATIONS = 120_000
BOARD_ROLE_ORDER = {"viewer": 1, "editor": 2, "owner": 3}
INSTANCE_SETTINGS_DEFAULTS = {
    "registration_enabled": "true",
    "default_board_color": "#2563eb",
    "new_accounts_active_by_default": "true",
    "instance_theme_color": "#1d4ed8",
    "recurrence_worker_interval_seconds": "60",
}

RECURRENCE_FREQUENCIES = {"daily", "weekly", "monthly"}
RECURRENCE_MODES = {"create_new", "reuse_existing"}
RECURRENCE_MIN_INTERVAL_SECONDS = 5
recurrence_worker_stop_event = threading.Event()
recurrence_worker_thread = None


def _request_client_ip(request: Optional[Request]) -> str:
    if request is None:
        return "unknown"
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    client = getattr(request, "client", None)
    return client.host if client and client.host else "unknown"


def _login_rate_limit_key(email: str, request: Optional[Request]) -> str:
    return f"{_request_client_ip(request)}:{email}"


def _purge_login_attempts(attempts: deque, now: float):
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()


def _enforce_login_rate_limit(email: str, request: Optional[Request]):
    key = _login_rate_limit_key(email, request)
    now = time.time()
    with login_attempt_lock:
        attempts = login_attempts[key]
        _purge_login_attempts(attempts, now)
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")


def _record_login_failure(email: str, request: Optional[Request]):
    key = _login_rate_limit_key(email, request)
    now = time.time()
    with login_attempt_lock:
        attempts = login_attempts[key]
        _purge_login_attempts(attempts, now)
        attempts.append(now)


def _clear_login_failures(email: str, request: Optional[Request]):
    key = _login_rate_limit_key(email, request)
    with login_attempt_lock:
        login_attempts.pop(key, None)


def _request_origin_is_same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    expected_origin = str(request.base_url).rstrip("/")
    return origin.rstrip("/") == expected_origin


def _require_api_csrf(request: Request):
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    if not request.url.path.startswith("/api/"):
        return
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    if not _request_origin_is_same_origin(request):
        raise HTTPException(status_code=403, detail="CSRF validation failed")

    if request.url.path in {"/api/auth/login", "/api/auth/register"}:
        return

    session_token = request.cookies.get(SESSION_COOKIE)
    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    csrf_header = request.headers.get("x-csrf-token")
    if not session_token or not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
        raise HTTPException(status_code=403, detail="CSRF validation failed")

    db = SessionLocal()
    try:
        session = (
            db.query(models.UserSession)
            .filter(models.UserSession.token_hash == _hash_session_token(session_token))
            .first()
        )
        if not session or not session.csrf_token_hash:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        if session.csrf_token_hash != _hash_csrf_token(csrf_header):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
    finally:
        db.close()


@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    started = time.perf_counter()
    try:
        _require_api_csrf(request)
    except HTTPException as exc:
        return Response(
            content=json.dumps({"detail": exc.detail}),
            status_code=exc.status_code,
            media_type="application/json",
        )
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms >= 250:
        logger.warning("slow_request %.1fms %s %s -> %s", elapsed_ms, request.method, request.url.path, response.status_code)
    return response


@app.on_event("startup")
def start_recurrence_worker():
    global recurrence_worker_thread
    validate_runtime_security_config()
    recurrence_worker_stop_event.clear()
    if recurrence_worker_thread and recurrence_worker_thread.is_alive():
        return
    recurrence_worker_thread = threading.Thread(
        target=recurrence_worker_loop,
        name="questline-recurrence-worker",
        daemon=True,
    )
    recurrence_worker_thread.start()


@app.on_event("shutdown")
def stop_recurrence_worker():
    recurrence_worker_stop_event.set()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class BoardCreate(BaseModel):
    name: str
    color: Optional[str] = None

class BoardUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None

class StageCreate(BaseModel):
    name: str
    board_id: int
    row: int = 0

class StageUpdate(BaseModel):
    name: str

class StageConfigUpdate(BaseModel):
    is_log: Optional[bool] = None
    filter_id: Optional[int] = None

class ReorderStages(BaseModel):
    ids: Optional[PyList[int]] = None
    stages: Optional[PyList[dict]] = None

class TaskCreate(BaseModel):
    title: str
    stage_id: int
    task_type_id: Optional[int] = None
    due_date: Optional[str] = None

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    task_type_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    color: Optional[str] = None
    show_description_on_card: Optional[bool] = None
    show_checklist_on_card: Optional[bool] = None
    done: Optional[bool] = None
    custom_fields: Optional[dict] = None

class TaskRecurrenceUpdate(BaseModel):
    enabled: bool = True
    mode: str = "create_new"
    frequency: str
    interval: int = 1
    next_run_on: str
    spawn_stage_id: int

class TaskMove(BaseModel):
    stage_id: int
    position: int

class ReorderTasks(BaseModel):
    stage_id: int
    ids: PyList[int]

class TaskTypeCreate(BaseModel):
    name: str
    is_epic: bool = False
    board_id: int
    color: Optional[str] = None
    show_description_on_card: bool = False
    show_checklist_on_card: bool = False

class TaskTypeUpdate(BaseModel):
    name: Optional[str] = None
    is_epic: Optional[bool] = None
    spawn_stage_id: Optional[int] = None
    color: Optional[str] = None
    show_description_on_card: Optional[bool] = None
    show_checklist_on_card: Optional[bool] = None

class CustomFieldCreate(BaseModel):
    name: str
    field_type: str = "text"
    show_on_card: bool = False
    options: Optional[PyList[Union[str, dict]]] = None
    color: Optional[str] = None

class ChecklistItemCreate(BaseModel):
    title: str

class ChecklistItemUpdate(BaseModel):
    title: Optional[str] = None
    done: Optional[bool] = None

class AutomationCreate(BaseModel):
    name: str
    trigger_type: str
    trigger_stage_id: Optional[int] = None
    action_type: str
    action_stage_id: Optional[int] = None
    action_task_type_id: Optional[int] = None
    action_color: Optional[str] = None
    action_days_offset: Optional[int] = None
    board_id: int

class AutomationUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    trigger_stage_id: Optional[int] = None
    action_stage_id: Optional[int] = None
    action_task_type_id: Optional[int] = None
    action_color: Optional[str] = None
    action_days_offset: Optional[int] = None


class SavedFilterCreate(BaseModel):
    name: str
    board_id: int
    definition: dict


class SavedFilterUpdate(BaseModel):
    name: Optional[str] = None
    definition: Optional[dict] = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    display_name: str
    password: Optional[str] = None


class BoardMemberCreate(BaseModel):
    email: str
    role: str = "viewer"


class BoardMemberUpdate(BaseModel):
    role: str


class AdminUserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


class AdminSettingsUpdate(BaseModel):
    registration_enabled: bool
    default_board_color: Optional[str] = None
    new_accounts_active_by_default: bool
    instance_theme_color: Optional[str] = None
    recurrence_worker_interval_seconds: int = 60


def _validate_custom_fields_for_task(
    custom_fields: dict,
    effective_task_type_id: Optional[int],
    board_id: int,
    db: Session,
):
    if not custom_fields:
        return
    if effective_task_type_id is None:
        raise HTTPException(status_code=400, detail="Custom fields require a task type")
    for field_def_id_str in custom_fields.keys():
        field_def_id = int(field_def_id_str)
        field_def = (
            db.query(models.CustomFieldDef)
            .filter(models.CustomFieldDef.id == field_def_id)
            .first()
        )
        if not field_def:
            raise HTTPException(status_code=404, detail="Custom field not found")
        if field_def.task_type_id != effective_task_type_id:
            raise HTTPException(status_code=400, detail="Custom field does not belong to the selected task type")
        if not field_def.task_type or field_def.task_type.board_id != board_id:
            raise HTTPException(status_code=400, detail="Custom field belongs to a different board")


def _validate_assignee_for_task(board_id: int, assignee_user_id: Optional[int], db: Session):
    if assignee_user_id is None:
        return None
    assignee = db.query(models.User).filter(models.User.id == assignee_user_id).first()
    if not assignee or not assignee.is_active:
        raise HTTPException(status_code=400, detail="Assignee must be an active user")
    membership = (
        db.query(models.BoardMembership)
        .filter(
            models.BoardMembership.board_id == board_id,
            models.BoardMembership.user_id == assignee_user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=400, detail="Assignee must be a board member")
    return assignee


def _parse_iso_date(value: str, detail: str = "Invalid date") -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=detail)


def _advance_recurrence_date(current: date, frequency: str, interval: int) -> date:
    if frequency == "daily":
        return current + timedelta(days=interval)
    if frequency == "weekly":
        return current + timedelta(weeks=interval)
    if frequency == "monthly":
        month_index = current.month - 1 + interval
        year = current.year + month_index // 12
        month = month_index % 12 + 1
        month_lengths = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        day = min(current.day, month_lengths[month - 1])
        return date(year, month, day)
    raise HTTPException(status_code=400, detail="Invalid recurrence frequency")


def _validate_task_recurrence_input(task: models.Task, data: TaskRecurrenceUpdate, db: Session) -> models.Stage:
    if data.mode not in RECURRENCE_MODES:
        raise HTTPException(status_code=400, detail="Invalid recurrence mode")
    if data.frequency not in RECURRENCE_FREQUENCIES:
        raise HTTPException(status_code=400, detail="Invalid recurrence frequency")
    if data.interval < 1:
        raise HTTPException(status_code=400, detail="Recurrence interval must be at least 1")
    _parse_iso_date(data.next_run_on, "Recurrence next run date must be YYYY-MM-DD")
    spawn_stage = db.query(models.Stage).filter(models.Stage.id == data.spawn_stage_id).first()
    if not spawn_stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if spawn_stage.board_id != task.stage.board_id:
        raise HTTPException(status_code=400, detail="Recurrence stage belongs to a different board")
    if spawn_stage.is_log:
        raise HTTPException(status_code=400, detail="Cannot recur into a log stage")
    return spawn_stage


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return login_redirect_response()
    instance_settings = get_instance_settings(db)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "board": None,
            "boards": [],
            "current_user": current_user,
            "page_theme_color": instance_settings["instance_theme_color"],
        },
    )

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if get_optional_current_user(request, db):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"board": None, "boards": [], "current_user": None},
    )


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    if get_optional_current_user(request, db):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "register.html",
        {"board": None, "boards": [], "current_user": None},
    )

@app.get("/board/{board_id}", response_class=HTMLResponse)
def board_page(request: Request, board_id: int, db: Session = Depends(get_db)):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return login_redirect_response()
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    board_role = require_board_access(board_id, current_user, db, "viewer")
    return templates.TemplateResponse(request, "board.html", {
        "board": {"id": board.id, "name": board.name, "color": board.color},
        "boards": _boards_for_nav(db, current_user),
        "current_user": current_user,
        "board_role": board_role,
    })

@app.get("/board/{board_id}/task-types", response_class=HTMLResponse)
def task_types_page(request: Request, board_id: int, db: Session = Depends(get_db)):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return login_redirect_response()
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    board_role = require_board_access(board_id, current_user, db, "viewer")
    return templates.TemplateResponse(request, "task_types.html", {
        "board": {"id": board.id, "name": board.name, "color": board.color},
        "boards": _boards_for_nav(db, current_user),
        "current_user": current_user,
        "board_role": board_role,
    })

@app.get("/board/{board_id}/filters", response_class=HTMLResponse)
def filters_page(request: Request, board_id: int, db: Session = Depends(get_db)):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return login_redirect_response()
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    board_role = require_board_access(board_id, current_user, db, "viewer")
    memberships = (
        db.query(models.BoardMembership)
        .filter(models.BoardMembership.board_id == board_id)
        .order_by(models.BoardMembership.created_at, models.BoardMembership.id)
        .all()
    )
    assignee_options = [
        {
            "user_id": membership.user_id,
            "display_name": membership.user.display_name,
            "email": membership.user.email,
        }
        for membership in memberships
    ]
    if current_user.role == "admin" and not any(option["user_id"] == current_user.id for option in assignee_options):
        assignee_options.insert(
            0,
            {
                "user_id": current_user.id,
                "display_name": current_user.display_name,
                "email": current_user.email,
            },
        )
    return templates.TemplateResponse(request, "filters.html", {
        "board": {"id": board.id, "name": board.name, "color": board.color},
        "boards": _boards_for_nav(db, current_user),
        "current_user": current_user,
        "filter_current_user": user_to_dict(current_user),
        "filter_assignee_options": assignee_options,
        "board_role": board_role,
    })

@app.get("/board/{board_id}/automations", response_class=HTMLResponse)
def automations_page(request: Request, board_id: int, db: Session = Depends(get_db)):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return login_redirect_response()
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    board_role = require_board_access(board_id, current_user, db, "viewer")
    return templates.TemplateResponse(request, "automations.html", {
        "board": {"id": board.id, "name": board.name, "color": board.color},
        "boards": _boards_for_nav(db, current_user),
        "current_user": current_user,
        "board_role": board_role,
    })


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db), board_id: Optional[int] = None):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return login_redirect_response()
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access denied")
    instance_settings = get_instance_settings(db)
    nav_board = None
    if board_id is not None:
        board = db.query(models.Board).filter(models.Board.id == board_id).first()
        if board:
            require_board_access(board_id, current_user, db, "viewer")
            nav_board = {"id": board.id, "name": board.name, "color": board.color}
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "board": nav_board,
            "boards": _boards_for_nav(db, current_user),
            "current_user": current_user,
            "page_theme_color": instance_settings["instance_theme_color"],
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_instance_settings(db: Session) -> dict:
    values = dict(INSTANCE_SETTINGS_DEFAULTS)
    rows = db.query(models.InstanceSetting).all()
    for row in rows:
        values[row.key] = row.value
    if not values.get("instance_theme_color") and values.get("overview_theme_color"):
        values["instance_theme_color"] = values["overview_theme_color"]
    return {
        "registration_enabled": str(values.get("registration_enabled", "true")).lower() == "true",
        "default_board_color": (values.get("default_board_color") or INSTANCE_SETTINGS_DEFAULTS["default_board_color"]).strip(),
        "new_accounts_active_by_default": str(values.get("new_accounts_active_by_default", "true")).lower() == "true",
        "instance_theme_color": (values.get("instance_theme_color") or INSTANCE_SETTINGS_DEFAULTS["instance_theme_color"]).strip(),
        "recurrence_worker_interval_seconds": max(
            RECURRENCE_MIN_INTERVAL_SECONDS,
            int(str(values.get("recurrence_worker_interval_seconds", INSTANCE_SETTINGS_DEFAULTS["recurrence_worker_interval_seconds"])).strip() or INSTANCE_SETTINGS_DEFAULTS["recurrence_worker_interval_seconds"]),
        ),
    }


def set_instance_settings(db: Session, updates: dict) -> dict:
    for key, value in updates.items():
        row = db.query(models.InstanceSetting).filter(models.InstanceSetting.key == key).first()
        if not row:
            row = models.InstanceSetting(key=key)
            db.add(row)
        row.value = value
    db.commit()
    return get_instance_settings(db)


def _validated_hex_color(value: Optional[str], fallback: str, detail: str) -> str:
    color = (value or "").strip() or fallback
    if not color.startswith("#") or len(color) not in {4, 7}:
        raise HTTPException(status_code=400, detail=detail)
    return color


def notification_to_dict(notification: models.Notification) -> dict:
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "body": notification.body or "",
        "link_url": notification.link_url,
        "board_id": notification.board_id,
        "task_id": notification.task_id,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }


def recurrence_to_dict(recurrence: Optional[models.TaskRecurrence]) -> Optional[dict]:
    if not recurrence:
        return None
    return {
        "enabled": recurrence.enabled,
        "mode": recurrence.mode,
        "frequency": recurrence.frequency,
        "interval": recurrence.interval,
        "next_run_on": recurrence.next_run_on,
        "spawn_stage_id": recurrence.spawn_stage_id,
    }


def create_notification(
    user_id: int,
    notification_type: str,
    title: str,
    body: Optional[str],
    db: Session,
    *,
    link_url: Optional[str] = None,
    board_id: Optional[int] = None,
    task_id: Optional[int] = None,
    dedupe_key: Optional[str] = None,
):
    if dedupe_key:
        existing = (
            db.query(models.Notification)
            .filter(models.Notification.dedupe_key == dedupe_key)
            .first()
        )
        if existing:
            return existing
    notification = models.Notification(
        user_id=user_id,
        type=notification_type,
        title=title,
        body=body or "",
        link_url=link_url,
        board_id=board_id,
        task_id=task_id,
        dedupe_key=dedupe_key,
    )
    db.add(notification)
    db.flush()
    return notification


def generate_due_notifications_for_user(user: models.User, db: Session):
    today = date.today().isoformat()
    query = (
        db.query(models.Task)
        .join(models.Stage, models.Task.stage_id == models.Stage.id)
        .filter(
            models.Task.assignee_user_id == user.id,
            models.Task.done == False,
            models.Task.due_date.is_not(None),
            models.Task.due_date != "",
        )
    )
    if user.role != "admin":
        query = query.join(
            models.BoardMembership,
            models.BoardMembership.board_id == models.Stage.board_id,
        ).filter(models.BoardMembership.user_id == user.id)
    tasks = query.all()
    created = False
    for task in tasks:
        if not task.stage or not task.stage.board:
            continue
        notification_type = None
        if task.due_date == today:
            notification_type = "task_due_today"
        elif task.due_date < today:
            notification_type = "task_overdue"
        if not notification_type:
            continue
        dedupe_key = f"{notification_type}:task:{task.id}:user:{user.id}:date:{today}"
        title = "Task due today" if notification_type == "task_due_today" else "Task overdue"
        body = task.title
        create_notification(
            user.id,
            notification_type,
            title,
            body,
            db,
            link_url=f"/board/{task.stage.board_id}?task_id={task.id}",
            board_id=task.stage.board_id,
            task_id=task.id,
            dedupe_key=dedupe_key,
        )
        created = True
    if created:
        db.commit()


def task_to_dict(task: models.Task) -> dict:
    custom_values = {str(cfv.field_def_id): cfv.value for cfv in task.custom_field_values}
    checklist = [
        {
            "id": item.id,
            "title": item.title,
            "done": item.done,
            "spawned_task_id": item.spawned_task_id,
        }
        for item in task.checklist_items
    ]
    task_type = None
    if task.task_type:
        task_type = {
            "id": task.task_type.id,
            "name": task.task_type.name,
            "color": task.task_type.color,
            "is_epic": task.task_type.is_epic,
            "show_description_on_card": task.task_type.show_description_on_card,
            "show_checklist_on_card": task.task_type.show_checklist_on_card,
            "custom_fields": [field_to_dict(f) for f in task.task_type.custom_fields],
        }
    display_color = task.color or (task.task_type.color if task.task_type else None)
    effective_show_description_on_card = (
        task.show_description_on_card
        if task.show_description_on_card is not None
        else (task.task_type.show_description_on_card if task.task_type else False)
    )
    effective_show_checklist_on_card = (
        task.show_checklist_on_card
        if task.show_checklist_on_card is not None
        else (task.task_type.show_checklist_on_card if task.task_type else False)
    )
    parent_task = None
    if task.parent_task:
        parent_task = {
            "id": task.parent_task.id,
            "title": task.parent_task.title,
            "board_id": task.parent_task.stage.board_id if task.parent_task.stage else None,
        }
    assignee = None
    if task.assignee:
        assignee = {
            "id": task.assignee.id,
            "display_name": task.assignee.display_name,
            "email": task.assignee.email,
        }
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description or "",
        "due_date": task.due_date,
        "board_id": task.stage.board_id if task.stage else None,
        "board_name": task.stage.board.name if task.stage and task.stage.board else None,
        "stage_name": task.stage.name if task.stage else None,
        "parent_task": parent_task,
        "assignee": assignee,
        "assignee_user_id": task.assignee_user_id,
        "show_description_on_card": task.show_description_on_card,
        "effective_show_description_on_card": effective_show_description_on_card,
        "show_checklist_on_card": task.show_checklist_on_card,
        "effective_show_checklist_on_card": effective_show_checklist_on_card,
        "stage_id": task.stage_id,
        "task_type": task_type,
        "task_type_id": task.task_type_id,
        "color": display_color,
        "position": task.position,
        "done": task.done,
        "custom_field_values": custom_values,
        "checklist": checklist,
        "recurrence": recurrence_to_dict(task.recurrence),
    }


def _create_checklist_item_internal(task: models.Task, title: str, db: Session) -> models.ChecklistItem:
    item = models.ChecklistItem(task_id=task.id, title=title)
    db.add(item)
    db.flush()

    if task.task_type and task.task_type.is_epic:
        target_stage_id = task.task_type.spawn_stage_id or task.stage_id
        target_stage = db.query(models.Stage).filter(models.Stage.id == target_stage_id).first()
        if target_stage and target_stage.is_log:
            raise HTTPException(status_code=400, detail="Cannot spawn tasks into a log stage")
        new_pos = (
            db.query(models.Task).filter(models.Task.stage_id == target_stage_id).count()
        )
        spawned = models.Task(
            title=title,
            stage_id=target_stage_id,
            position=new_pos,
            color=task.task_type.color,
            parent_task_id=task.id,
        )
        db.add(spawned)
        db.flush()
        item.spawned_task_id = spawned.id
    return item


def _sync_spawned_task_title_from_checklist_item(item: models.ChecklistItem, db: Session):
    if not item.spawned_task_id:
        return
    spawned = db.query(models.Task).filter(models.Task.id == item.spawned_task_id).first()
    if spawned:
        spawned.title = item.title


def _sync_checklist_item_title_from_spawned_task(task: models.Task, db: Session):
    linked_item = (
        db.query(models.ChecklistItem)
        .filter(models.ChecklistItem.spawned_task_id == task.id)
        .first()
    )
    if linked_item:
        linked_item.title = task.title


def _resolve_recurrence_stage(source_task: models.Task, recurrence: models.TaskRecurrence, db: Session) -> Optional[models.Stage]:
    target_stage = db.query(models.Stage).filter(models.Stage.id == recurrence.spawn_stage_id).first()
    if not target_stage or target_stage.is_log or target_stage.board_id != source_task.stage.board_id:
        recurrence.enabled = False
        db.commit()
        logger.warning(
            "disabled_recurrence task_id=%s recurrence_stage_id=%s",
            source_task.id,
            recurrence.spawn_stage_id,
        )
        return None
    return target_stage


def _clone_task_from_recurrence(source_task: models.Task, recurrence: models.TaskRecurrence, db: Session) -> models.Task:
    target_stage = _resolve_recurrence_stage(source_task, recurrence, db)
    if target_stage is None:
        return None

    occurrence_date = _parse_iso_date(recurrence.next_run_on, "Invalid recurrence next run date")
    new_pos = db.query(models.Task).filter(models.Task.stage_id == target_stage.id).count()
    cloned_task = models.Task(
        title=source_task.title,
        description=source_task.description,
        due_date=occurrence_date.isoformat(),
        stage_id=target_stage.id,
        task_type_id=source_task.task_type_id,
        assignee_user_id=source_task.assignee_user_id,
        position=new_pos,
        color=source_task.color,
        show_description_on_card=source_task.show_description_on_card,
        show_checklist_on_card=source_task.show_checklist_on_card,
        done=False,
    )
    db.add(cloned_task)
    db.flush()

    for cfv in source_task.custom_field_values:
        db.add(
            models.CustomFieldValue(
                task_id=cloned_task.id,
                field_def_id=cfv.field_def_id,
                value=cfv.value,
            )
        )

    source_checklist_titles = [item.title for item in source_task.checklist_items]
    for title in source_checklist_titles:
        _create_checklist_item_internal(cloned_task, title, db)

    recurrence.next_run_on = _advance_recurrence_date(
        occurrence_date,
        recurrence.frequency,
        recurrence.interval,
    ).isoformat()
    db.commit()
    db.refresh(cloned_task)
    run_automations(cloned_task, "task_created", db)
    db.commit()
    return cloned_task


def _reuse_task_from_recurrence(source_task: models.Task, recurrence: models.TaskRecurrence, db: Session) -> models.Task:
    target_stage = _resolve_recurrence_stage(source_task, recurrence, db)
    if target_stage is None:
        return None

    occurrence_date = _parse_iso_date(recurrence.next_run_on, "Invalid recurrence next run date")
    new_pos = db.query(models.Task).filter(models.Task.stage_id == target_stage.id).count()
    source_task.stage_id = target_stage.id
    source_task.position = new_pos
    source_task.done = False
    source_task.due_date = occurrence_date.isoformat()
    for checklist_item in source_task.checklist_items:
        checklist_item.done = False
    recurrence.next_run_on = _advance_recurrence_date(
        occurrence_date,
        recurrence.frequency,
        recurrence.interval,
    ).isoformat()
    db.commit()
    db.refresh(source_task)
    return source_task


def process_due_recurrences(db: Session, today: Optional[date] = None) -> int:
    today = today or date.today()
    due_recurrences = (
        db.query(models.TaskRecurrence)
        .join(models.Task, models.TaskRecurrence.task_id == models.Task.id)
        .join(models.Stage, models.Task.stage_id == models.Stage.id)
        .filter(
            models.TaskRecurrence.enabled == True,
            models.TaskRecurrence.next_run_on <= today.isoformat(),
        )
        .order_by(models.TaskRecurrence.next_run_on.asc(), models.TaskRecurrence.id.asc())
        .all()
    )
    created_count = 0
    for recurrence in due_recurrences:
        if not recurrence.task or not recurrence.task.stage:
            continue
        if recurrence.mode == "reuse_existing":
            processed_task = _reuse_task_from_recurrence(recurrence.task, recurrence, db)
        else:
            processed_task = _clone_task_from_recurrence(recurrence.task, recurrence, db)
        if processed_task is not None:
            created_count += 1
    return created_count


def recurrence_worker_loop():
    while not recurrence_worker_stop_event.is_set():
        db = SessionLocal()
        interval_seconds = RECURRENCE_MIN_INTERVAL_SECONDS
        try:
            interval_seconds = get_instance_settings(db)["recurrence_worker_interval_seconds"]
            process_due_recurrences(db)
        except Exception:
            logger.exception("recurrence_worker_failed")
        finally:
            db.close()
        recurrence_worker_stop_event.wait(max(RECURRENCE_MIN_INTERVAL_SECONDS, interval_seconds))

def apply_automation(task: models.Task, automation: models.Automation, db: Session):
    if automation.action_type == "move_to_stage" and automation.action_stage_id:
        target_stage = db.query(models.Stage).filter(models.Stage.id == automation.action_stage_id).first()
        if target_stage and target_stage.is_log:
            return
        new_pos = (
            db.query(models.Task)
            .filter(models.Task.stage_id == automation.action_stage_id)
            .count()
        )
        task.stage_id = automation.action_stage_id
        task.position = new_pos
    elif automation.action_type == "set_done":
        task.done = True
    elif automation.action_type == "set_task_type":
        task.task_type_id = automation.action_task_type_id
    elif automation.action_type == "set_color":
        task.color = automation.action_color or None
    elif automation.action_type == "set_due_in_days" and automation.action_days_offset is not None:
        task.due_date = (date.today() + timedelta(days=automation.action_days_offset)).isoformat()


def collect_descendant_task_ids(root_task_ids: list[int], db: Session) -> set[int]:
    all_ids = set(root_task_ids)
    frontier = set(root_task_ids)

    while frontier:
        child_ids = {
            task_id
            for (task_id,) in db.query(models.ChecklistItem.spawned_task_id)
            .filter(
                models.ChecklistItem.task_id.in_(frontier),
                models.ChecklistItem.spawned_task_id.is_not(None),
            )
            .all()
        }
        child_ids -= all_ids
        if not child_ids:
            break
        all_ids.update(child_ids)
        frontier = child_ids

    return all_ids


def delete_tasks_by_ids(task_ids: set[int], db: Session):
    if not task_ids:
        return 0

    linked_items = (
        db.query(models.ChecklistItem)
        .filter(models.ChecklistItem.spawned_task_id.in_(task_ids))
        .all()
    )
    for item in linked_items:
        db.delete(item)

    tasks = db.query(models.Task).filter(models.Task.id.in_(task_ids)).all()
    for task in tasks:
        db.delete(task)
    db.commit()
    return len(tasks)


def run_automations(task: models.Task, event_type: str, db: Session):
    board_id = task.stage.board_id if task.stage else None
    query = db.query(models.Automation).filter(
        models.Automation.enabled == True,
        models.Automation.trigger_type == event_type,
    )
    if board_id is not None:
        query = query.filter(models.Automation.board_id == board_id)
    for automation in query.all():
        if automation.trigger_stage_id and task.stage_id != automation.trigger_stage_id:
            continue
        apply_automation(task, automation, db)


# ---------------------------------------------------------------------------
# Authentication API
# ---------------------------------------------------------------------------

def _validate_membership_role(role: str) -> str:
    if role not in BOARD_ROLE_ORDER:
        raise HTTPException(status_code=400, detail="Invalid membership role")
    return role


@app.get("/api/auth/me")
def auth_me(request: Request, db: Session = Depends(get_db)):
    user = get_optional_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_to_dict(user)


@app.post("/api/auth/register")
def auth_register(data: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    email = _normalize_email(data.email)
    password = data.password or ""
    display_name = (data.display_name or "").strip() or email.split("@", 1)[0]
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Registration failed")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    existing = db.query(models.User).filter(models.User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Registration failed")
    existing_user_count = db.query(models.User).count()
    if existing_user_count > 0 and not get_instance_settings(db)["registration_enabled"]:
        raise HTTPException(status_code=403, detail="Registration is currently disabled")
    user_role = "admin" if existing_user_count == 0 else "user"
    is_active = True if existing_user_count == 0 else get_instance_settings(db)["new_accounts_active_by_default"]
    user = models.User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        role=user_role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    claim_legacy_boards_for_first_user(user, db)
    if user.is_active:
        token, csrf_token = create_user_session(user, db)
        _set_session_cookie(response, token, csrf_token)
    return user_to_dict(user)


@app.post("/api/auth/login")
def auth_login(
    data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    request: Request = None,
):
    email = _normalize_email(data.email)
    _enforce_login_rate_limit(email, request)
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(data.password or "", user.password_hash):
        _record_login_failure(email, request)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        _record_login_failure(email, request)
        raise HTTPException(status_code=403, detail="Account is awaiting activation")
    _clear_login_failures(email, request)
    token, csrf_token = create_user_session(user, db)
    _set_session_cookie(response, token, csrf_token)
    return user_to_dict(user)


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.query(models.UserSession).filter(
            models.UserSession.token_hash == _hash_session_token(token)
        ).delete()
        db.commit()
    _clear_session_cookie(response)
    return {"ok": True}


@app.put("/api/auth/profile")
def auth_update_profile(data: ProfileUpdate, request: Request, response: Response, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    display_name = (data.display_name or "").strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="Display name is required")
    user.display_name = display_name
    if data.password is not None and data.password != "":
        if len(data.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        user.password_hash = hash_password(data.password)
        db.query(models.UserSession).filter(models.UserSession.user_id == user.id).delete()
    db.commit()
    if data.password is not None and data.password != "":
        token, csrf_token = create_user_session(user, db)
        _set_session_cookie(response, token, csrf_token)
    db.refresh(user)
    return user_to_dict(user)


@app.get("/api/notifications")
def get_notifications(request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    generate_due_notifications_for_user(user, db)
    notifications = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == user.id)
        .order_by(models.Notification.created_at.desc(), models.Notification.id.desc())
        .limit(20)
        .all()
    )
    unread_count = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user.id,
            models.Notification.read_at.is_(None),
        )
        .count()
    )
    return {
        "items": [notification_to_dict(notification) for notification in notifications],
        "unread_count": unread_count,
    }


@app.post("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    notification = (
        db.query(models.Notification)
        .filter(
            models.Notification.id == notification_id,
            models.Notification.user_id == user.id,
        )
        .first()
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.utcnow()
        db.commit()
    return {"ok": True}


@app.post("/api/notifications/read-all")
def mark_all_notifications_read(request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    db.query(models.Notification).filter(
        models.Notification.user_id == user.id,
        models.Notification.read_at.is_(None),
    ).update({"read_at": datetime.utcnow()}, synchronize_session=False)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Boards API
# ---------------------------------------------------------------------------

@app.get("/api/boards")
def get_boards(request: Request = None, db: Session = Depends(get_db)):
    if request is None:
        boards = db.query(models.Board).order_by(models.Board.position).all()
        board_ids = [board.id for board in boards]
        shared_map = _board_shared_map(board_ids, db)
        return [
            {
                "id": b.id,
                "name": b.name,
                "color": b.color,
                "position": b.position,
                "is_shared": shared_map.get(b.id, False),
            }
            for b in boards
        ]
    else:
        user = require_current_user(request, db)
        boards = get_accessible_boards(user, db)
        board_ids = [board.id for board in boards]
        role_map = _board_role_map(board_ids, user, db)
        shared_map = _board_shared_map(board_ids, db)
        return [
            {
                "id": b.id,
                "name": b.name,
                "color": b.color,
                "position": b.position,
                "role": role_map.get(b.id),
                "is_shared": shared_map.get(b.id, False),
            }
            for b in boards
        ]

@app.post("/api/boards")
def create_board(data: BoardCreate, db: Session = Depends(get_db), request: Request = None):
    owner_user = require_current_user(request, db) if request is not None else None
    instance_settings = get_instance_settings(db)
    pos = db.query(models.Board).count()
    board = models.Board(
        name=data.name,
        color=data.color or instance_settings["default_board_color"] or None,
        position=pos,
        owner_user_id=owner_user.id if owner_user else None,
    )
    db.add(board)
    db.commit()
    db.refresh(board)
    if owner_user:
        ensure_board_membership(board, owner_user, "owner", db)
        db.commit()
    return {
        "id": board.id,
        "name": board.name,
        "color": board.color,
        "position": board.position,
        "role": "owner" if owner_user else None,
        "is_shared": False,
    }


@app.get("/api/admin/users")
def get_admin_users(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    users = db.query(models.User).order_by(models.User.created_at, models.User.id).all()
    user_ids = [user.id for user in users]
    board_count_rows = (
        db.query(models.BoardMembership.user_id, func.count(models.BoardMembership.id))
        .filter(models.BoardMembership.user_id.in_(user_ids))
        .group_by(models.BoardMembership.user_id)
        .all()
        if user_ids
        else []
    )
    board_count_map = {user_id: count for user_id, count in board_count_rows}
    return [
        {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "is_active": user.is_active,
            "board_count": board_count_map.get(user.id, 0),
        }
        for user in users
    ]


@app.get("/api/admin/settings")
def get_admin_settings(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    return get_instance_settings(db)


@app.put("/api/admin/settings")
def update_admin_settings(data: AdminSettingsUpdate, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    default_board_color = _validated_hex_color(
        data.default_board_color,
        INSTANCE_SETTINGS_DEFAULTS["default_board_color"],
        "Default board color must be a valid hex color",
    )
    instance_theme_color = _validated_hex_color(
        data.instance_theme_color,
        INSTANCE_SETTINGS_DEFAULTS["instance_theme_color"],
        "Instance theme color must be a valid hex color",
    )
    if data.recurrence_worker_interval_seconds < RECURRENCE_MIN_INTERVAL_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"Recurrence worker interval must be at least {RECURRENCE_MIN_INTERVAL_SECONDS} seconds",
        )
    return set_instance_settings(
        db,
        {
            "registration_enabled": "true" if data.registration_enabled else "false",
            "default_board_color": default_board_color,
            "new_accounts_active_by_default": "true" if data.new_accounts_active_by_default else "false",
            "instance_theme_color": instance_theme_color,
            "recurrence_worker_interval_seconds": str(data.recurrence_worker_interval_seconds),
        },
    )


@app.put("/api/admin/users/{user_id}")
def update_admin_user(user_id: int, data: AdminUserUpdate, request: Request, db: Session = Depends(get_db)):
    current_user = require_admin(request, db)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if data.role is not None and data.role not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid admin role")
    target_role = data.role if data.role is not None else user.role
    if user.role == "admin" and target_role != "admin":
        admin_count = db.query(models.User).filter(models.User.role == "admin").count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Questline must have at least one admin")
    user.role = target_role
    if data.is_active is not None:
        if user.id == current_user.id and data.is_active is False:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
        user.is_active = data.is_active
        if data.is_active is False:
            db.query(models.UserSession).filter(models.UserSession.user_id == user.id).delete()
    db.commit()
    return user_to_dict(user)

@app.put("/api/boards/{board_id}")
def update_board(board_id: int, data: BoardUpdate, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, board_id, "owner")
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    if data.name is not None:
        board.name = data.name
    if "color" in data.model_fields_set:
        board.color = data.color or None
    db.commit()
    return {"id": board.id, "name": board.name, "color": board.color}

@app.delete("/api/boards/{board_id}")
def delete_board(board_id: int, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, board_id, "owner")
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    db.delete(board)
    db.commit()
    return {"ok": True}


@app.get("/api/boards/{board_id}/members")
def get_board_members(board_id: int, db: Session = Depends(get_db), request: Request = None):
    current_user = _authorize_board_request(request, db, board_id, "viewer")
    memberships = (
        db.query(models.BoardMembership)
        .filter(models.BoardMembership.board_id == board_id)
        .order_by(models.BoardMembership.created_at, models.BoardMembership.id)
        .all()
    )
    return {
        "current_role": get_board_role(board_id, current_user, db) if current_user else None,
        "members": [board_membership_to_dict(membership) for membership in memberships],
    }


@app.post("/api/boards/{board_id}/members")
def add_board_member(board_id: int, data: BoardMemberCreate, db: Session = Depends(get_db), request: Request = None):
    actor = _authorize_board_request(request, db, board_id, "owner")
    role = _validate_membership_role(data.role)
    email = _normalize_email(data.email)
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    existing_membership = (
        db.query(models.BoardMembership)
        .filter(
            models.BoardMembership.board_id == board_id,
            models.BoardMembership.user_id == user.id,
        )
        .first()
    )
    membership = ensure_board_membership(board, user, role, db)
    db.commit()
    db.refresh(membership)
    if existing_membership is None and actor and actor.id != user.id:
        create_notification(
            user.id,
            "board_shared",
            "Hub shared with you",
            f"{actor.display_name} shared {board.name} with you",
            db,
            link_url=f"/board/{board.id}",
            board_id=board.id,
            dedupe_key=f"board_shared:board:{board.id}:user:{user.id}",
        )
        db.commit()
    return board_membership_to_dict(membership)


@app.put("/api/boards/{board_id}/members/{user_id}")
def update_board_member(board_id: int, user_id: int, data: BoardMemberUpdate, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, board_id, "owner")
    role = _validate_membership_role(data.role)
    membership = (
        db.query(models.BoardMembership)
        .filter(
            models.BoardMembership.board_id == board_id,
            models.BoardMembership.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Board membership not found")
    if membership.role == "owner" and role != "owner" and _owner_membership_count(board_id, db) <= 1:
        raise HTTPException(status_code=400, detail="Board must have at least one owner")
    membership.role = role
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if board and role == "owner":
        board.owner_user_id = user_id
    elif board and board.owner_user_id == user_id and role != "owner":
        replacement = (
            db.query(models.BoardMembership)
            .filter(
                models.BoardMembership.board_id == board_id,
                models.BoardMembership.role == "owner",
                models.BoardMembership.user_id != user_id,
            )
            .first()
        )
        board.owner_user_id = replacement.user_id if replacement else None
    db.commit()
    db.refresh(membership)
    return board_membership_to_dict(membership)


@app.delete("/api/boards/{board_id}/members/{user_id}")
def delete_board_member(board_id: int, user_id: int, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, board_id, "owner")
    membership = (
        db.query(models.BoardMembership)
        .filter(
            models.BoardMembership.board_id == board_id,
            models.BoardMembership.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Board membership not found")
    if membership.role == "owner" and _owner_membership_count(board_id, db) <= 1:
        raise HTTPException(status_code=400, detail="Board must have at least one owner")
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    db.delete(membership)
    if board and board.owner_user_id == user_id:
        replacement = (
            db.query(models.BoardMembership)
            .filter(
                models.BoardMembership.board_id == board_id,
                models.BoardMembership.role == "owner",
                models.BoardMembership.user_id != user_id,
            )
            .first()
        )
        board.owner_user_id = replacement.user_id if replacement else None
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Saved Filters API
# ---------------------------------------------------------------------------

@app.get("/api/filters")
def get_saved_filters(board_id: int, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, board_id, "viewer")
    filters = (
        db.query(models.SavedFilter)
        .filter(models.SavedFilter.board_id == board_id)
        .order_by(models.SavedFilter.name)
        .all()
    )
    return [saved_filter_to_dict(saved_filter) for saved_filter in filters]


@app.post("/api/filters")
def create_saved_filter(data: SavedFilterCreate, db: Session = Depends(get_db), request: Request = None):
    current_user = _authorize_board_request(request, db, data.board_id, "editor")
    definition = _validated_filter_definition(data.definition, data.board_id, db, current_user)
    saved_filter = models.SavedFilter(
        name=data.name,
        board_id=data.board_id,
        definition=json.dumps(definition),
    )
    db.add(saved_filter)
    db.commit()
    db.refresh(saved_filter)
    return saved_filter_to_dict(saved_filter)


@app.put("/api/filters/{filter_id}")
def update_saved_filter(filter_id: int, data: SavedFilterUpdate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_saved_filter(filter_id, db)
    if board_id is not None:
        current_user = _authorize_board_request(request, db, board_id, "editor")
    else:
        current_user = None
    saved_filter = db.query(models.SavedFilter).filter(models.SavedFilter.id == filter_id).first()
    if not saved_filter:
        raise HTTPException(status_code=404, detail="Saved filter not found")
    if data.name is not None:
        saved_filter.name = data.name
    if "definition" in data.model_fields_set:
        saved_filter.definition = json.dumps(
            _validated_filter_definition(data.definition, saved_filter.board_id, db, current_user)
        )
    db.commit()
    db.refresh(saved_filter)
    return saved_filter_to_dict(saved_filter)


@app.delete("/api/filters/{filter_id}")
def delete_saved_filter(filter_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_saved_filter(filter_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    saved_filter = db.query(models.SavedFilter).filter(models.SavedFilter.id == filter_id).first()
    if not saved_filter:
        raise HTTPException(status_code=404, detail="Saved filter not found")
    db.query(models.Stage).filter(models.Stage.filter_id == filter_id).update({"filter_id": None})
    db.delete(saved_filter)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Stages API
# ---------------------------------------------------------------------------

@app.get("/api/stages")
def get_stages(board_id: int, db: Session = Depends(get_db), request: Request = None):
    current_user = _authorize_board_request(request, db, board_id, "viewer")
    stages = (
        db.query(models.Stage)
        .filter(models.Stage.board_id == board_id)
        .order_by(models.Stage.row, models.Stage.position)
        .all()
    )
    result = []
    for stage in stages:
        tasks = get_stage_tasks(stage, db, current_user)
        result.append(
            {
                **stage_to_dict(stage),
                "tasks": [task_to_dict(t) for t in tasks],
            }
        )
    return result

@app.post("/api/stages")
def create_stage(data: StageCreate, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, data.board_id, "editor")
    row = max(0, data.row)
    max_position = (
        db.query(models.Stage)
        .filter(models.Stage.board_id == data.board_id, models.Stage.row == row)
        .with_entities(func.max(models.Stage.position))
        .scalar()
    )
    pos = 0 if max_position is None else max_position + 1
    stage = models.Stage(name=data.name, board_id=data.board_id, row=row, position=pos)
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return {**stage_to_dict(stage), "tasks": []}

# NOTE: /api/stages/reorder must be declared before /api/stages/{stage_id}
@app.put("/api/stages/reorder")
def reorder_stages(data: ReorderStages, db: Session = Depends(get_db), request: Request = None):
    placements = []
    if data.stages:
        for index, stage_data in enumerate(data.stages):
            stage_id = stage_data.get("id")
            if not isinstance(stage_id, int):
                raise HTTPException(status_code=400, detail="Invalid stage reorder payload")
            placements.append(
                {
                    "id": stage_id,
                    "row": max(0, int(stage_data.get("row", 0))),
                    "position": max(0, int(stage_data.get("position", index))),
                }
            )
    elif data.ids:
        placements = [{"id": stage_id, "row": 0, "position": i} for i, stage_id in enumerate(data.ids)]

    if placements:
        board_id = _board_id_for_stage(placements[0]["id"], db)
        if board_id is not None:
            _authorize_board_request(request, db, board_id, "editor")
            for placement in placements:
                stage_id = placement["id"]
                _require_stage_in_board(stage_id, board_id, db)
    for placement in placements:
        db.query(models.Stage).filter(models.Stage.id == placement["id"]).update(
            {"row": placement["row"], "position": placement["position"]}
        )
    db.commit()
    return {"ok": True}

@app.put("/api/stages/{stage_id}")
def update_stage(stage_id: int, data: StageUpdate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_stage(stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    stage = db.query(models.Stage).filter(models.Stage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    stage.name = data.name
    db.commit()
    return {"id": stage.id, "name": stage.name}


@app.put("/api/stages/{stage_id}/config")
def update_stage_config(stage_id: int, data: StageConfigUpdate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_stage(stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    stage = db.query(models.Stage).filter(models.Stage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if "is_log" in data.model_fields_set:
        if data.is_log and not stage.is_log and stage.tasks:
            raise HTTPException(status_code=400, detail="Cannot convert a non-empty stage into a log")
        stage.is_log = bool(data.is_log)
    if "filter_id" in data.model_fields_set:
        if data.filter_id is not None:
            saved_filter = db.query(models.SavedFilter).filter(models.SavedFilter.id == data.filter_id).first()
            if not saved_filter or saved_filter.board_id != stage.board_id:
                raise HTTPException(status_code=400, detail="Invalid saved filter")
        stage.filter_id = data.filter_id
    if not stage.is_log:
        stage.filter_id = None
    db.commit()
    db.refresh(stage)
    return stage_to_dict(stage)

@app.delete("/api/stages/{stage_id}")
def delete_stage(stage_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_stage(stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    stage = db.query(models.Stage).filter(models.Stage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    task_ids = [t.id for t in stage.tasks]
    if task_ids:
        delete_tasks_by_ids(collect_descendant_task_ids(task_ids, db), db)
        db.refresh(stage)
    db.delete(stage)
    db.commit()
    return {"ok": True}


@app.post("/api/stages/{stage_id}/clear-completed")
def clear_completed_stage_tasks(stage_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_stage(stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    stage = db.query(models.Stage).filter(models.Stage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if stage.is_log:
        raise HTTPException(status_code=400, detail="Cannot clear tasks from a log stage")

    completed_task_ids = [
        task.id
        for task in db.query(models.Task)
        .filter(models.Task.stage_id == stage_id, models.Task.done == True)
        .all()
    ]
    task_ids_to_delete = collect_descendant_task_ids(completed_task_ids, db)
    deleted_count = delete_tasks_by_ids(task_ids_to_delete, db)
    return {"ok": True, "deleted": deleted_count}


# ---------------------------------------------------------------------------
# Tasks API
# ---------------------------------------------------------------------------

@app.post("/api/tasks")
def create_task(data: TaskCreate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_stage(data.stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    stage = db.query(models.Stage).filter(models.Stage.id == data.stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if stage.is_log:
        raise HTTPException(status_code=400, detail="Cannot add tasks to a log stage")
    if data.task_type_id is not None:
        _require_task_type_in_board(data.task_type_id, stage.board_id, db)
    pos = (
        db.query(models.Task).filter(models.Task.stage_id == data.stage_id).count()
    )
    task = models.Task(
        title=data.title,
        stage_id=data.stage_id,
        task_type_id=data.task_type_id,
        due_date=data.due_date,
        position=pos,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    run_automations(task, "task_created", db)
    db.commit()
    db.refresh(task)
    return task_to_dict(task)

@app.get("/api/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "viewer")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_to_dict(task)

# NOTE: /api/tasks/reorder before /api/tasks/{task_id}
@app.put("/api/tasks/reorder")
def reorder_tasks(data: ReorderTasks, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_stage(data.stage_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    target_stage = db.query(models.Stage).filter(models.Stage.id == data.stage_id).first()
    if not target_stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if target_stage.is_log:
        raise HTTPException(status_code=400, detail="Cannot move tasks into a log stage")
    moved_tasks = []
    for i, task_id in enumerate(data.ids):
        task = _require_task_in_board(task_id, target_stage.board_id, db)
        previous_stage_id = task.stage_id
        task.stage_id = data.stage_id
        task.position = i
        if previous_stage_id != data.stage_id:
            moved_tasks.append(task)
    db.commit()
    for task in moved_tasks:
        run_automations(task, "task_moved_to_stage", db)
    if moved_tasks:
        db.commit()
    return {"ok": True}

@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, data: TaskUpdate, db: Session = Depends(get_db), request: Request = None):
    current_user = None
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        current_user = _authorize_board_request(request, db, board_id, "editor")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if "task_type_id" in data.model_fields_set and data.task_type_id is not None:
        _require_task_type_in_board(data.task_type_id, task.stage.board_id, db)
    if "assignee_user_id" in data.model_fields_set:
        _validate_assignee_for_task(task.stage.board_id, data.assignee_user_id, db)

    effective_task_type_id = data.task_type_id if "task_type_id" in data.model_fields_set else task.task_type_id
    _validate_custom_fields_for_task(data.custom_fields, effective_task_type_id, task.stage.board_id, db)

    prev_done = task.done
    prev_assignee_user_id = task.assignee_user_id

    if data.title is not None:
        task.title = data.title
        _sync_checklist_item_title_from_spawned_task(task, db)
    if data.description is not None:
        task.description = data.description
    if "due_date" in data.model_fields_set:
        task.due_date = data.due_date or None
    if "task_type_id" in data.model_fields_set:
        task.task_type_id = data.task_type_id
    if "assignee_user_id" in data.model_fields_set:
        task.assignee_user_id = data.assignee_user_id
    if "color" in data.model_fields_set:
        task.color = data.color or None
    if "show_description_on_card" in data.model_fields_set:
        task.show_description_on_card = data.show_description_on_card
    if "show_checklist_on_card" in data.model_fields_set:
        task.show_checklist_on_card = data.show_checklist_on_card
    if data.done is not None:
        task.done = data.done

    if data.custom_fields:
        for field_def_id_str, value in data.custom_fields.items():
            field_def_id = int(field_def_id_str)
            existing = (
                db.query(models.CustomFieldValue)
                .filter(
                    models.CustomFieldValue.task_id == task_id,
                    models.CustomFieldValue.field_def_id == field_def_id,
                )
                .first()
            )
            if existing:
                existing.value = value
            else:
                db.add(
                    models.CustomFieldValue(
                        task_id=task_id, field_def_id=field_def_id, value=value
                    )
                )

    db.commit()

    if data.done is not None:
        ref_item = (
            db.query(models.ChecklistItem)
            .filter(models.ChecklistItem.spawned_task_id == task_id)
            .first()
        )
        if ref_item:
            ref_item.done = data.done
        for checklist_item in task.checklist_items:
            checklist_item.done = data.done
        spawned_children = (
            db.query(models.Task)
            .join(models.ChecklistItem, models.ChecklistItem.spawned_task_id == models.Task.id)
            .filter(models.ChecklistItem.task_id == task_id)
            .all()
        )
        children_newly_done = []
        for child in spawned_children:
            was_done = child.done
            child.done = data.done
            if data.done and not was_done:
                children_newly_done.append(child)
        db.commit()
        for child in children_newly_done:
            run_automations(child, "task_done", db)
        if children_newly_done:
            db.commit()

    if data.done is True and not prev_done:
        run_automations(task, "task_done", db)
        db.commit()

    if (
        "assignee_user_id" in data.model_fields_set
        and task.assignee_user_id
        and task.assignee_user_id != prev_assignee_user_id
        and current_user
        and current_user.id != task.assignee_user_id
        and task.stage
    ):
        create_notification(
            task.assignee_user_id,
            "task_assigned",
            "Assigned to an objective",
            f"{current_user.display_name} assigned you to {task.title}",
            db,
            link_url=f"/board/{task.stage.board_id}?task_id={task.id}",
            board_id=task.stage.board_id,
            task_id=task.id,
        )
        db.commit()

    db.refresh(task)
    return task_to_dict(task)

@app.put("/api/tasks/{task_id}/move")
def move_task(task_id: int, data: TaskMove, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    target_stage = db.query(models.Stage).filter(models.Stage.id == data.stage_id).first()
    if not target_stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if not task.stage or task.stage.board_id != target_stage.board_id:
        raise HTTPException(status_code=400, detail="Cannot move tasks across boards")
    if target_stage.is_log:
        raise HTTPException(status_code=400, detail="Cannot move tasks into a log stage")
    previous_stage_id = task.stage_id
    task.stage_id = data.stage_id
    task.position = data.position
    db.commit()
    if previous_stage_id != data.stage_id:
        run_automations(task, "task_moved_to_stage", db)
        db.commit()
    db.refresh(task)
    return task_to_dict(task)

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    delete_tasks_by_ids(collect_descendant_task_ids([task_id], db), db)
    return {"ok": True}


@app.put("/api/tasks/{task_id}/recurrence")
def upsert_task_recurrence(
    task_id: int,
    data: TaskRecurrenceUpdate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.stage:
        raise HTTPException(status_code=400, detail="Task has no stage")

    _validate_task_recurrence_input(task, data, db)
    recurrence = task.recurrence
    if recurrence is None:
        recurrence = models.TaskRecurrence(task_id=task.id)
        db.add(recurrence)
    recurrence.enabled = data.enabled
    recurrence.mode = data.mode
    recurrence.frequency = data.frequency
    recurrence.interval = data.interval
    recurrence.next_run_on = data.next_run_on
    recurrence.spawn_stage_id = data.spawn_stage_id
    db.commit()
    db.refresh(task)
    return recurrence_to_dict(task.recurrence)


@app.delete("/api/tasks/{task_id}/recurrence")
def delete_task_recurrence(task_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    recurrence = (
        db.query(models.TaskRecurrence)
        .filter(models.TaskRecurrence.task_id == task_id)
        .first()
    )
    if not recurrence:
        raise HTTPException(status_code=404, detail="Task recurrence not found")
    db.delete(recurrence)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Checklist API
# ---------------------------------------------------------------------------

@app.post("/api/tasks/{task_id}/checklist")
def add_checklist_item(
    task_id: int, data: ChecklistItemCreate, db: Session = Depends(get_db), request: Request = None
):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    item = _create_checklist_item_internal(task, data.title, db)

    db.commit()
    if item.spawned_task_id:
        spawned = db.query(models.Task).filter(models.Task.id == item.spawned_task_id).first()
        if spawned:
            run_automations(spawned, "task_created", db)
            db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "title": item.title,
        "done": item.done,
        "spawned_task_id": item.spawned_task_id,
    }

@app.put("/api/tasks/{task_id}/checklist/{item_id}")
def update_checklist_item(
    task_id: int, item_id: int, data: ChecklistItemUpdate, db: Session = Depends(get_db), request: Request = None
):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    item = (
        db.query(models.ChecklistItem)
        .filter(
            models.ChecklistItem.id == item_id,
            models.ChecklistItem.task_id == task_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    was_complete = bool(item.task.checklist_items) and all(ci.done for ci in item.task.checklist_items)
    if data.title is not None:
        item.title = data.title
        _sync_spawned_task_title_from_checklist_item(item, db)
    if data.done is not None:
        item.done = data.done
        if item.spawned_task_id:
            spawned = db.query(models.Task).filter(models.Task.id == item.spawned_task_id).first()
            if spawned:
                prev_done = spawned.done
                spawned.done = data.done
                db.commit()
                if data.done and not prev_done:
                    run_automations(spawned, "task_done", db)
    is_complete = bool(item.task.checklist_items) and all(ci.done for ci in item.task.checklist_items)
    if is_complete and not was_complete:
        run_automations(item.task, "checklist_completed", db)
    db.commit()
    return {
        "id": item.id,
        "title": item.title,
        "done": item.done,
        "spawned_task_id": item.spawned_task_id,
    }

@app.delete("/api/tasks/{task_id}/checklist/{item_id}")
def delete_checklist_item(
    task_id: int, item_id: int, db: Session = Depends(get_db), request: Request = None
):
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    item = (
        db.query(models.ChecklistItem)
        .filter(
            models.ChecklistItem.id == item_id,
            models.ChecklistItem.task_id == task_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    spawned_task_id = item.spawned_task_id
    db.delete(item)
    db.commit()
    if spawned_task_id is not None:
        delete_tasks_by_ids(collect_descendant_task_ids([spawned_task_id], db), db)
    return {"ok": True}


def normalize_field_options(options) -> list[dict]:
    normalized = []
    for option in options or []:
        if isinstance(option, str):
            label = option.strip()
            if label:
                normalized.append({"label": label, "color": None})
            continue
        if isinstance(option, dict):
            label = str(option.get("label") or option.get("value") or "").strip()
            if label:
                normalized.append({"label": label, "color": option.get("color") or None})
    return normalized


# ---------------------------------------------------------------------------
# Task Types API
# ---------------------------------------------------------------------------

def field_to_dict(f: models.CustomFieldDef) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "field_type": f.field_type,
        "color": f.color,
        "show_on_card": f.show_on_card,
        "options": normalize_field_options(json.loads(f.options) if f.options else []),
    }

def task_type_to_dict(tt: models.TaskType) -> dict:
    return {
        "id": tt.id,
        "name": tt.name,
        "color": tt.color,
        "is_epic": tt.is_epic,
        "show_description_on_card": tt.show_description_on_card,
        "show_checklist_on_card": tt.show_checklist_on_card,
        "spawn_stage_id": tt.spawn_stage_id,
        "custom_fields": [field_to_dict(f) for f in tt.custom_fields],
    }

@app.get("/api/task-types")
def get_task_types(board_id: int, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, board_id, "viewer")
    types = db.query(models.TaskType).filter(models.TaskType.board_id == board_id).all()
    return [task_type_to_dict(tt) for tt in types]

@app.post("/api/task-types")
def create_task_type(data: TaskTypeCreate, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, data.board_id, "editor")
    tt = models.TaskType(
        name=data.name,
        is_epic=data.is_epic,
        board_id=data.board_id,
        color=data.color or None,
        show_description_on_card=data.show_description_on_card,
        show_checklist_on_card=data.show_checklist_on_card,
    )
    db.add(tt)
    db.commit()
    db.refresh(tt)
    return task_type_to_dict(tt)

@app.put("/api/task-types/{type_id}")
def update_task_type(type_id: int, data: TaskTypeUpdate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task_type(type_id, db)
    if board_id is not None:
        current_user = _authorize_board_request(request, db, board_id, "editor")
    else:
        current_user = None
    tt = db.query(models.TaskType).filter(models.TaskType.id == type_id).first()
    if not tt:
        raise HTTPException(status_code=404, detail="Task type not found")
    if data.name is not None:
        tt.name = data.name
    if data.is_epic is not None:
        tt.is_epic = data.is_epic
    if "spawn_stage_id" in data.model_fields_set:
        if data.spawn_stage_id is not None:
            target_stage = db.query(models.Stage).filter(models.Stage.id == data.spawn_stage_id).first()
            if not target_stage:
                raise HTTPException(status_code=404, detail="Stage not found")
            if target_stage.is_log:
                raise HTTPException(status_code=400, detail="Cannot spawn tasks into a log stage")
            if request is not None and current_user is not None:
                require_board_access(target_stage.board_id, current_user, db, "editor")
        tt.spawn_stage_id = data.spawn_stage_id
    if "color" in data.model_fields_set:
        tt.color = data.color or None
    if "show_description_on_card" in data.model_fields_set:
        tt.show_description_on_card = data.show_description_on_card
    if "show_checklist_on_card" in data.model_fields_set:
        tt.show_checklist_on_card = data.show_checklist_on_card
    db.commit()
    db.refresh(tt)
    return task_type_to_dict(tt)

@app.delete("/api/task-types/{type_id}")
def delete_task_type(type_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task_type(type_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    tt = db.query(models.TaskType).filter(models.TaskType.id == type_id).first()
    if not tt:
        raise HTTPException(status_code=404, detail="Task type not found")
    db.delete(tt)
    db.commit()
    return {"ok": True}

@app.post("/api/task-types/{type_id}/fields")
def add_custom_field(
    type_id: int, data: CustomFieldCreate, db: Session = Depends(get_db), request: Request = None
):
    board_id = _board_id_for_task_type(type_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    tt = db.query(models.TaskType).filter(models.TaskType.id == type_id).first()
    if not tt:
        raise HTTPException(status_code=404, detail="Task type not found")
    field = models.CustomFieldDef(
        task_type_id=type_id,
        name=data.name,
        field_type=data.field_type,
        show_on_card=data.show_on_card,
        options=json.dumps(normalize_field_options(data.options)) if data.options else None,
        color=data.color or None,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return field_to_dict(field)

@app.put("/api/task-types/{type_id}/fields/{field_id}")
def update_custom_field(type_id: int, field_id: int, data: CustomFieldCreate, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task_type(type_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    field = (
        db.query(models.CustomFieldDef)
        .filter(
            models.CustomFieldDef.id == field_id,
            models.CustomFieldDef.task_type_id == type_id,
        )
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    field.show_on_card = data.show_on_card
    if "options" in data.model_fields_set:
        field.options = json.dumps(normalize_field_options(data.options)) if data.options else None
    if "color" in data.model_fields_set:
        field.color = data.color or None
    db.commit()
    return field_to_dict(field)

@app.delete("/api/task-types/{type_id}/fields/{field_id}")
def delete_custom_field(type_id: int, field_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_task_type(type_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    field = (
        db.query(models.CustomFieldDef)
        .filter(
            models.CustomFieldDef.id == field_id,
            models.CustomFieldDef.task_type_id == type_id,
        )
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    db.delete(field)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Automations API
# ---------------------------------------------------------------------------

def automation_to_dict(a: models.Automation) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "trigger_type": a.trigger_type,
        "trigger_stage_id": a.trigger_stage_id,
        "action_type": a.action_type,
        "action_stage_id": a.action_stage_id,
        "action_task_type_id": a.action_task_type_id,
        "action_color": a.action_color,
        "action_days_offset": a.action_days_offset,
        "enabled": a.enabled,
    }

@app.get("/api/automations")
def get_automations(board_id: int, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, board_id, "viewer")
    autos = db.query(models.Automation).filter(models.Automation.board_id == board_id).all()
    return [automation_to_dict(a) for a in autos]

@app.post("/api/automations")
def create_automation(data: AutomationCreate, db: Session = Depends(get_db), request: Request = None):
    _authorize_board_request(request, db, data.board_id, "editor")
    if data.trigger_stage_id is not None:
        _require_stage_in_board(data.trigger_stage_id, data.board_id, db)
    if data.action_stage_id is not None:
        _require_stage_in_board(data.action_stage_id, data.board_id, db)
    if data.action_task_type_id is not None:
        _require_task_type_in_board(data.action_task_type_id, data.board_id, db)
    auto = models.Automation(
        name=data.name,
        trigger_type=data.trigger_type,
        trigger_stage_id=data.trigger_stage_id or None,
        action_type=data.action_type,
        action_stage_id=data.action_stage_id or None,
        action_task_type_id=data.action_task_type_id or None,
        action_color=data.action_color or None,
        action_days_offset=data.action_days_offset,
        board_id=data.board_id,
    )
    db.add(auto)
    db.commit()
    db.refresh(auto)
    return automation_to_dict(auto)

@app.put("/api/automations/{auto_id}")
def update_automation(
    auto_id: int, data: AutomationUpdate, db: Session = Depends(get_db), request: Request = None
):
    board_id = _board_id_for_automation(auto_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    auto = db.query(models.Automation).filter(models.Automation.id == auto_id).first()
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    if data.name is not None:
        auto.name = data.name
    if data.enabled is not None:
        auto.enabled = data.enabled
    if "trigger_stage_id" in data.model_fields_set:
        if data.trigger_stage_id is not None:
            _require_stage_in_board(data.trigger_stage_id, auto.board_id, db)
        auto.trigger_stage_id = data.trigger_stage_id or None
    if "action_stage_id" in data.model_fields_set:
        if data.action_stage_id is not None:
            _require_stage_in_board(data.action_stage_id, auto.board_id, db)
        auto.action_stage_id = data.action_stage_id or None
    if "action_task_type_id" in data.model_fields_set:
        if data.action_task_type_id is not None:
            _require_task_type_in_board(data.action_task_type_id, auto.board_id, db)
        auto.action_task_type_id = data.action_task_type_id or None
    if "action_color" in data.model_fields_set:
        auto.action_color = data.action_color or None
    if "action_days_offset" in data.model_fields_set:
        auto.action_days_offset = data.action_days_offset
    db.commit()
    db.refresh(auto)
    return automation_to_dict(auto)

@app.delete("/api/automations/{auto_id}")
def delete_automation(auto_id: int, db: Session = Depends(get_db), request: Request = None):
    board_id = _board_id_for_automation(auto_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    auto = db.query(models.Automation).filter(models.Automation.id == auto_id).first()
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    db.delete(auto)
    db.commit()
    return {"ok": True}
