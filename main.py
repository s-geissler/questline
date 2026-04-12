import json
import ipaddress
import logging
import os
import re
import time
import threading
from datetime import UTC, date, datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List as PyList, Union

import models
from database import engine, SessionLocal, get_db
from routes.auth import (
    LoginRequest,
    PasswordRecoveryRequest,
    ProfileUpdate,
    RegisterRequest,
    auth_login,
    auth_logout,
    auth_me,
    auth_password_recovery_request,
    auth_register,
    auth_update_profile,
    router as auth_router,
)
from routes.boards import (
    BoardCreate,
    BoardMemberCreate,
    BoardMemberUpdate,
    BoardUpdate,
    add_board_member as _add_board_member_route,
    create_board as _create_board_route,
    delete_board as _delete_board_route,
    delete_board_member as _delete_board_member_route,
    get_board_members as _get_board_members_route,
    get_boards as _get_boards_route,
    router as boards_router,
    update_board as _update_board_route,
    update_board_member as _update_board_member_route,
)
from routes.stages import (
    ReorderStages,
    StageConfigUpdate,
    StageCreate,
    StageUpdate,
    _validate_stage_grid,
    clear_completed_stage_tasks as _clear_completed_stage_tasks_route,
    create_stage as _create_stage_route,
    delete_stage as _delete_stage_route,
    get_stages as _get_stages_route,
    reorder_stages as _reorder_stages_route,
    router as stages_router,
    update_stage as _update_stage_route,
    update_stage_config as _update_stage_config_route,
)
from routes.tasks import (
    ChecklistItemCreate,
    ChecklistItemUpdate,
    ReorderTasks,
    TaskCreate,
    TaskMove,
    TaskRecurrenceUpdate,
    TaskUpdate,
    add_checklist_item as _add_checklist_item_route,
    create_task as _create_task_route,
    delete_checklist_item as _delete_checklist_item_route,
    delete_task as _delete_task_route,
    delete_task_recurrence as _delete_task_recurrence_route,
    get_task as _get_task_route,
    move_task as _move_task_route,
    reorder_tasks as _reorder_tasks_route,
    router as tasks_router,
    task_to_dict,
    update_checklist_item as _update_checklist_item_route,
    update_task as _update_task_route,
    upsert_task_recurrence as _upsert_task_recurrence_route,
)
from services.automation import apply_automation, run_automations
from services.audit import _audit_log, _configure_audit_logger, _request_client_ip
from services.notifications import (
    create_notification,
    generate_due_notifications_for_user,
    notification_to_dict,
    recurrence_to_dict,
)
from services.recurrence import (
    _advance_recurrence_date,
    _clone_task_from_recurrence,
    _parse_iso_date,
    _resolve_recurrence_stage,
    _reuse_task_from_recurrence,
    process_due_recurrences,
    recurrence_worker_loop,
    recurrence_worker_stop_event,
)
from services.settings import (
    INSTANCE_SETTINGS_DEFAULTS,
    RECURRENCE_MIN_INTERVAL_SECONDS,
    get_instance_settings,
)
from services.tasks import (
    _create_checklist_item_internal,
    _sync_checklist_item_title_from_spawned_task,
    _sync_spawned_task_title_from_checklist_item,
    collect_descendant_task_ids,
    delete_tasks_by_ids,
)
from authz import (
    CSRF_COOKIE,
    SESSION_MAX_AGE,
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
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_NAME_LENGTH = 120
MAX_EMAIL_LENGTH = 255
MAX_PASSWORD_LENGTH = 4096
MAX_DISPLAY_NAME_LENGTH = 120
MAX_TASK_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 10000
MAX_OPTION_COUNT = 100
MAX_FILTER_JSON_LENGTH = 20000
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Content-Type-Options": "nosniff",
}


def _parse_trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    configured = os.getenv("QUESTLINE_TRUSTED_PROXIES", "")
    networks = []
    for raw_value in configured.split(","):
        value = raw_value.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError as exc:
            raise RuntimeError(f"Invalid QUESTLINE_TRUSTED_PROXIES entry: {value}") from exc
    return tuple(networks)


TRUSTED_PROXY_NETWORKS = _parse_trusted_proxy_networks()


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
        ("users", "password_reset_requested", "BOOLEAN"),
        ("instance_settings", "key", "VARCHAR"),
        ("instance_settings", "value", "TEXT"),
        ("task_recurrences", "mode", "VARCHAR"),
        ("user_sessions", "csrf_token_hash", "VARCHAR"),
        ("user_sessions", "expires_at", "DATETIME"),
    ]
    with engine.begin() as conn:
        for table, col, col_type in migrations:
            if not SAFE_IDENTIFIER_RE.fullmatch(table) or not SAFE_IDENTIFIER_RE.fullmatch(col):
                raise RuntimeError(f"Unsafe migration identifier: {table}.{col}")
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
        ("ix_users_password_reset_requested", "CREATE INDEX IF NOT EXISTS ix_users_password_reset_requested ON users(password_reset_requested)"),
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


def _backfill_session_expirations():
    db = SessionLocal()
    try:
        expiration_cutoff = _utcnow() + SESSION_MAX_AGE
        db.query(models.UserSession).filter(models.UserSession.expires_at.is_(None)).update(
            {"expires_at": expiration_cutoff},
            synchronize_session=False,
        )
        db.commit()
    finally:
        db.close()


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
        db.query(models.User).filter(models.User.password_reset_requested.is_(None)).update({"password_reset_requested": False})
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
_backfill_session_expirations()
_configure_audit_logger()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.state.trusted_proxy_networks = TRUSTED_PROXY_NETWORKS
app.include_router(auth_router)
app.include_router(boards_router)
app.include_router(stages_router)
app.include_router(tasks_router)
templates = Jinja2Templates(directory="templates")
SESSION_COOKIE = "questline_session"
PASSWORD_HASH_ITERATIONS = 120_000
BOARD_ROLE_ORDER = {"viewer": 1, "editor": 2, "owner": 3}
RECURRENCE_FREQUENCIES = {"daily", "weekly", "monthly"}
RECURRENCE_MODES = {"create_new", "reuse_existing"}
recurrence_worker_thread = None


def _apply_security_headers(response: Response) -> Response:
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    return response


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

    if request.url.path in {"/api/auth/login", "/api/auth/register", "/api/auth/password-recovery-request"}:
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
        return _apply_security_headers(Response(
            content=json.dumps({"detail": exc.detail}),
            status_code=exc.status_code,
            media_type="application/json",
        ))
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms >= 250:
        logger.warning("slow_request %.1fms %s %s -> %s", elapsed_ms, request.method, request.url.path, response.status_code)
    return _apply_security_headers(response)


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

class TaskTypeCreate(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    is_epic: bool = False
    board_id: int
    color: Optional[str] = Field(default=None, max_length=7)
    show_description_on_card: bool = False
    show_checklist_on_card: bool = False

class TaskTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    is_epic: Optional[bool] = None
    spawn_stage_id: Optional[int] = None
    color: Optional[str] = Field(default=None, max_length=7)
    show_description_on_card: Optional[bool] = None
    show_checklist_on_card: Optional[bool] = None

class CustomFieldCreate(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    field_type: str = "text"
    show_on_card: bool = False
    options: Optional[PyList[Union[str, dict]]] = None
    color: Optional[str] = Field(default=None, max_length=7)

class AutomationCreate(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    trigger_type: str
    trigger_stage_id: Optional[int] = None
    action_type: str
    action_stage_id: Optional[int] = None
    action_task_type_id: Optional[int] = None
    action_color: Optional[str] = Field(default=None, max_length=7)
    action_days_offset: Optional[int] = None
    board_id: int

class AutomationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    enabled: Optional[bool] = None
    trigger_stage_id: Optional[int] = None
    action_stage_id: Optional[int] = None
    action_task_type_id: Optional[int] = None
    action_color: Optional[str] = Field(default=None, max_length=7)
    action_days_offset: Optional[int] = None


class SavedFilterCreate(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    board_id: int
    definition: dict


class SavedFilterUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    definition: Optional[dict] = None


class AdminUserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password_reset_requested: Optional[bool] = None
    password: Optional[str] = Field(default=None, max_length=MAX_PASSWORD_LENGTH)


class AdminBoardOwnerUpdate(BaseModel):
    user_id: int


class AdminSettingsUpdate(BaseModel):
    registration_enabled: bool
    default_board_color: Optional[str] = None
    new_accounts_active_by_default: bool
    instance_theme_color: Optional[str] = None
    recurrence_worker_interval_seconds: int = 60


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
    if not HEX_COLOR_RE.fullmatch(color):
        raise HTTPException(status_code=400, detail=detail)
    return color


def _validated_optional_hex_color(value: Optional[str], detail: str) -> Optional[str]:
    color = (value or "").strip()
    if not color:
        return None
    if not HEX_COLOR_RE.fullmatch(color):
        raise HTTPException(status_code=400, detail=detail)
    return color


def _validate_filter_definition_size(definition: Optional[dict]):
    if definition is None:
        return
    if len(json.dumps(definition, separators=(",", ":"))) > MAX_FILTER_JSON_LENGTH:
        raise HTTPException(status_code=400, detail="Filter definition is too large")


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


# ---------------------------------------------------------------------------
# Authentication API
# ---------------------------------------------------------------------------

def _validate_membership_role(role: str) -> str:
    if role not in BOARD_ROLE_ORDER:
        raise HTTPException(status_code=400, detail="Invalid membership role")
    return role


def get_boards(request: Request, db: Session = Depends(get_db)):
    return _get_boards_route(request, db)


def create_board(data: BoardCreate, db: Session = Depends(get_db), request: Request = None):
    return _create_board_route(request, data, db)


def update_board(board_id: int, data: BoardUpdate, db: Session = Depends(get_db), request: Request = None):
    return _update_board_route(board_id, request, data, db)


def delete_board(board_id: int, db: Session = Depends(get_db), request: Request = None):
    return _delete_board_route(board_id, request, db)


def get_board_members(board_id: int, db: Session = Depends(get_db), request: Request = None):
    return _get_board_members_route(board_id, request, db)


def add_board_member(board_id: int, data: BoardMemberCreate, db: Session = Depends(get_db), request: Request = None):
    return _add_board_member_route(board_id, request, data, db)


def update_board_member(
    board_id: int,
    user_id: int,
    data: BoardMemberUpdate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    return _update_board_member_route(board_id, user_id, request, data, db)


def delete_board_member(board_id: int, user_id: int, db: Session = Depends(get_db), request: Request = None):
    return _delete_board_member_route(board_id, user_id, request, db)


def get_stages(board_id: int, db: Session = Depends(get_db), request: Request = None):
    return _get_stages_route(board_id, request, db)


def create_stage(data: StageCreate, db: Session = Depends(get_db), request: Request = None):
    return _create_stage_route(request, data, db)


def reorder_stages(data: ReorderStages, db: Session = Depends(get_db), request: Request = None):
    return _reorder_stages_route(request, data, db)


def update_stage(stage_id: int, data: StageUpdate, db: Session = Depends(get_db), request: Request = None):
    return _update_stage_route(stage_id, request, data, db)


def update_stage_config(stage_id: int, data: StageConfigUpdate, db: Session = Depends(get_db), request: Request = None):
    return _update_stage_config_route(stage_id, request, data, db)


def delete_stage(stage_id: int, db: Session = Depends(get_db), request: Request = None):
    return _delete_stage_route(stage_id, request, db)


def clear_completed_stage_tasks(stage_id: int, db: Session = Depends(get_db), request: Request = None):
    return _clear_completed_stage_tasks_route(stage_id, request, db)


def create_task(data: TaskCreate, db: Session = Depends(get_db), request: Request = None):
    return _create_task_route(data, db, request)


def get_task(task_id: int, db: Session = Depends(get_db), request: Request = None):
    return _get_task_route(task_id, db, request)


def reorder_tasks(data: ReorderTasks, db: Session = Depends(get_db), request: Request = None):
    return _reorder_tasks_route(data, db, request)


def update_task(task_id: int, data: TaskUpdate, db: Session = Depends(get_db), request: Request = None):
    return _update_task_route(task_id, data, db, request)


def move_task(task_id: int, data: TaskMove, db: Session = Depends(get_db), request: Request = None):
    return _move_task_route(task_id, data, db, request)


def delete_task(task_id: int, db: Session = Depends(get_db), request: Request = None):
    return _delete_task_route(task_id, db, request)


def upsert_task_recurrence(
    task_id: int,
    data: TaskRecurrenceUpdate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    return _upsert_task_recurrence_route(task_id, data, db, request)


def delete_task_recurrence(task_id: int, db: Session = Depends(get_db), request: Request = None):
    return _delete_task_recurrence_route(task_id, db, request)


def add_checklist_item(
    task_id: int,
    data: ChecklistItemCreate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    return _add_checklist_item_route(task_id, data, db, request)


def update_checklist_item(
    task_id: int,
    item_id: int,
    data: ChecklistItemUpdate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    return _update_checklist_item_route(task_id, item_id, data, db, request)


def delete_checklist_item(task_id: int, item_id: int, db: Session = Depends(get_db), request: Request = None):
    return _delete_checklist_item_route(task_id, item_id, db, request)


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

def _list_boards_internal(db: Session):
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
            "password_reset_requested": user.password_reset_requested,
            "board_count": board_count_map.get(user.id, 0),
        }
        for user in users
    ]


@app.get("/api/admin/boards")
def get_admin_boards(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    boards = (
        db.query(models.Board)
        .order_by(models.Board.owner_user_id.is_(None).desc(), models.Board.position, models.Board.id)
        .all()
    )
    board_ids = [board.id for board in boards]
    member_count_rows = (
        db.query(models.BoardMembership.board_id, func.count(models.BoardMembership.id))
        .filter(models.BoardMembership.board_id.in_(board_ids))
        .group_by(models.BoardMembership.board_id)
        .all()
        if board_ids
        else []
    )
    member_count_map = {board_id: count for board_id, count in member_count_rows}
    owner_ids = [board.owner_user_id for board in boards if board.owner_user_id is not None]
    owners = (
        db.query(models.User.id, models.User.display_name, models.User.email)
        .filter(models.User.id.in_(owner_ids))
        .all()
        if owner_ids
        else []
    )
    owner_map = {
        owner_id: {"display_name": display_name, "email": email}
        for owner_id, display_name, email in owners
    }
    return [
        {
            "id": board.id,
            "name": board.name,
            "color": board.color,
            "owner_user_id": board.owner_user_id,
            "owner_display_name": owner_map.get(board.owner_user_id, {}).get("display_name"),
            "owner_email": owner_map.get(board.owner_user_id, {}).get("email"),
            "member_count": member_count_map.get(board.id, 0),
            "is_orphan": board.owner_user_id is None,
        }
        for board in boards
    ]


@app.post("/api/admin/actions/delete-orphaned-boards")
def delete_admin_orphaned_boards(request: Request, db: Session = Depends(get_db)):
    current_user = require_admin(request, db)
    orphaned_boards = (
        db.query(models.Board)
        .filter(models.Board.owner_user_id.is_(None))
        .all()
    )
    deleted_board_ids = [board.id for board in orphaned_boards]
    deleted_count = len(deleted_board_ids)
    for board in orphaned_boards:
        db.delete(board)
    db.commit()
    _audit_log(
        "admin_orphaned_boards_deleted",
        request=request,
        actor_user_id=current_user.id,
        details={
            "deleted_board_ids": deleted_board_ids,
            "deleted_count": deleted_count,
        },
    )
    return {"ok": True, "deleted_count": deleted_count}


@app.put("/api/admin/boards/{board_id}/owner")
def assign_admin_board_owner(board_id: int, data: AdminBoardOwnerUpdate, request: Request, db: Session = Depends(get_db)):
    current_user = require_admin(request, db)
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    user = db.query(models.User).filter(models.User.id == data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    previous_owner_user_id = board.owner_user_id
    board.owner_user_id = user.id
    ensure_board_membership(board, user, "owner", db)
    db.commit()
    _audit_log(
        "admin_board_owner_assigned",
        request=request,
        actor_user_id=current_user.id,
        target_user_id=user.id,
        details={
            "board_id": board.id,
            "previous_owner_user_id": previous_owner_user_id,
            "new_owner_user_id": user.id,
        },
    )
    return {"ok": True}


@app.get("/api/admin/settings")
def get_admin_settings(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    return get_instance_settings(db)


@app.put("/api/admin/settings")
def update_admin_settings(data: AdminSettingsUpdate, request: Request, db: Session = Depends(get_db)):
    current_user = require_admin(request, db)
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
    updated = set_instance_settings(
        db,
        {
            "registration_enabled": "true" if data.registration_enabled else "false",
            "default_board_color": default_board_color,
            "new_accounts_active_by_default": "true" if data.new_accounts_active_by_default else "false",
            "instance_theme_color": instance_theme_color,
            "recurrence_worker_interval_seconds": str(data.recurrence_worker_interval_seconds),
        },
    )
    _audit_log(
        "admin_settings_updated",
        request=request,
        actor_user_id=current_user.id,
        details={
            "registration_enabled": updated["registration_enabled"],
            "new_accounts_active_by_default": updated["new_accounts_active_by_default"],
            "recurrence_worker_interval_seconds": updated["recurrence_worker_interval_seconds"],
        },
    )
    return updated


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
    previous_role = user.role
    previous_is_active = user.is_active
    previous_password_reset_requested = user.password_reset_requested
    password_changed = False
    user.role = target_role
    if data.is_active is not None:
        if user.id == current_user.id and data.is_active is False:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
        user.is_active = data.is_active
        if data.is_active is False:
            db.query(models.UserSession).filter(models.UserSession.user_id == user.id).delete()
    if data.password is not None:
        if len(data.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        user.password_hash = hash_password(data.password)
        user.password_reset_requested = False
        password_changed = True
        db.query(models.UserSession).filter(models.UserSession.user_id == user.id).delete()
    if data.password_reset_requested is not None:
        user.password_reset_requested = data.password_reset_requested
    db.commit()
    if (
        previous_role != user.role
        or previous_is_active != user.is_active
        or previous_password_reset_requested != user.password_reset_requested
        or password_changed
    ):
        _audit_log(
            "admin_user_updated",
            request=request,
            actor_user_id=current_user.id,
            target_user_id=user.id,
            details={
                "previous_role": previous_role,
                "new_role": user.role,
                "previous_is_active": previous_is_active,
                "new_is_active": user.is_active,
                "previous_password_reset_requested": previous_password_reset_requested,
                "new_password_reset_requested": user.password_reset_requested,
                "password_changed": password_changed,
            },
    )
    return user_to_dict(user)


@app.delete("/api/admin/users/{user_id}")
def delete_admin_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = require_admin(request, db)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if user.role == "admin":
        admin_count = db.query(models.User).filter(models.User.role == "admin").count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Questline must have at least one admin")
    deleted_email = user.email
    deleted_display_name = user.display_name
    deleted_role = user.role

    owned_board_ids = [
        board_id
        for (board_id,) in (
            db.query(models.Board.id)
            .filter(models.Board.owner_user_id == user.id)
            .all()
        )
    ]
    if owned_board_ids:
        replacements = (
            db.query(models.BoardMembership.board_id, models.BoardMembership.user_id)
            .filter(
                models.BoardMembership.board_id.in_(owned_board_ids),
                models.BoardMembership.role == "owner",
                models.BoardMembership.user_id != user.id,
            )
            .order_by(models.BoardMembership.board_id, models.BoardMembership.id)
            .all()
        )
        replacement_map = {}
        for board_id, replacement_user_id in replacements:
            replacement_map.setdefault(board_id, replacement_user_id)

        boards = db.query(models.Board).filter(models.Board.id.in_(owned_board_ids)).all()
        for board in boards:
            board.owner_user_id = replacement_map.get(board.id)

    db.delete(user)
    db.commit()
    _audit_log(
        "admin_user_deleted",
        request=request,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        details={
            "deleted_email": deleted_email,
            "deleted_display_name": deleted_display_name,
            "deleted_role": deleted_role,
            "owned_board_count": len(owned_board_ids),
        },
    )
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
    _validate_filter_definition_size(data.definition)
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
        _validate_filter_definition_size(data.definition)
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

def normalize_field_options(options) -> list[dict]:
    if len(options or []) > MAX_OPTION_COUNT:
        raise HTTPException(status_code=400, detail="Too many custom field options")
    normalized = []
    for option in options or []:
        if isinstance(option, str):
            label = option.strip()[:MAX_NAME_LENGTH]
            if label:
                normalized.append({"label": label, "color": None})
            continue
        if isinstance(option, dict):
            label = str(option.get("label") or option.get("value") or "").strip()[:MAX_NAME_LENGTH]
            if label:
                normalized.append(
                    {
                        "label": label,
                        "color": _validated_optional_hex_color(
                            option.get("color"),
                            "Custom field option color must be a valid hex color",
                        ),
                    }
                )
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
        color=_validated_optional_hex_color(data.color, "Task type color must be a valid hex color"),
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
        tt.color = _validated_optional_hex_color(data.color, "Task type color must be a valid hex color")
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
        color=_validated_optional_hex_color(data.color, "Custom field color must be a valid hex color"),
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
        field.color = _validated_optional_hex_color(data.color, "Custom field color must be a valid hex color")
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
        action_color=_validated_optional_hex_color(data.action_color, "Automation color must be a valid hex color"),
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
        auto.action_color = _validated_optional_hex_color(data.action_color, "Automation color must be a valid hex color")
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
