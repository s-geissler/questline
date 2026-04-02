import json
import hashlib
import hmac
import secrets
from datetime import date, timedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy import or_
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List as PyList, Union

import models
from database import engine, SessionLocal, get_db

# ---------------------------------------------------------------------------
# Schema migrations (add board_id columns to existing tables if missing)
# ---------------------------------------------------------------------------

def _run_column_migrations():
    migrations = [
        ("boards",           "owner_user_id", "INTEGER REFERENCES users(id)"),
        ("lists",       "board_id", "INTEGER REFERENCES boards(id)"),
        ("task_types",  "board_id", "INTEGER REFERENCES boards(id)"),
        ("automations", "board_id", "INTEGER REFERENCES boards(id)"),
        ("boards",           "color",   "VARCHAR"),
        ("task_types",       "color",   "VARCHAR"),
        ("task_types",       "show_description_on_card", "BOOLEAN"),
        ("lists",            "is_log", "BOOLEAN"),
        ("lists",            "filter_id", "INTEGER REFERENCES saved_filters(id)"),
        ("tasks",            "color",   "VARCHAR"),
        ("tasks",            "due_date", "VARCHAR"),
        ("tasks",            "parent_task_id", "INTEGER REFERENCES tasks(id)"),
        ("tasks",            "show_description_on_card", "BOOLEAN"),
        ("automations",      "action_task_type_id", "INTEGER REFERENCES task_types(id)"),
        ("automations",      "action_color", "VARCHAR"),
        ("automations",      "action_days_offset", "INTEGER"),
        ("custom_field_defs", "options", "TEXT"),
        ("custom_field_defs", "color",   "VARCHAR"),
        ("board_memberships", "role", "VARCHAR"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in migrations:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            if rows and col not in [r[1] for r in rows]:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
        conn.commit()


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


models.Base.metadata.create_all(bind=engine)
_run_column_migrations()
_migrate_orphan_data()
_migrate_board_memberships()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
SESSION_COOKIE = "questline_session"
PASSWORD_HASH_ITERATIONS = 120_000
BOARD_ROLE_ORDER = {"viewer": 1, "editor": 2, "owner": 3}


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

class StageUpdate(BaseModel):
    name: str

class StageConfigUpdate(BaseModel):
    is_log: Optional[bool] = None
    filter_id: Optional[int] = None

class ReorderStages(BaseModel):
    ids: PyList[int]

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
    color: Optional[str] = None
    show_description_on_card: Optional[bool] = None
    done: Optional[bool] = None
    custom_fields: Optional[dict] = None

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

class TaskTypeUpdate(BaseModel):
    name: Optional[str] = None
    is_epic: Optional[bool] = None
    spawn_stage_id: Optional[int] = None
    color: Optional[str] = None
    show_description_on_card: Optional[bool] = None

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


class BoardMemberCreate(BaseModel):
    email: str
    role: str = "viewer"


class BoardMemberUpdate(BaseModel):
    role: str


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def get_accessible_boards(user: Optional[models.User], db: Session):
    if not user:
        return []
    return (
        db.query(models.Board)
        .join(models.BoardMembership, models.BoardMembership.board_id == models.Board.id)
        .filter(models.BoardMembership.user_id == user.id)
        .order_by(models.Board.position)
        .all()
    )


def board_is_shared(board_id: int, db: Session) -> bool:
    return (
        db.query(models.BoardMembership)
        .filter(models.BoardMembership.board_id == board_id)
        .count()
        > 1
    )


def _boards_for_nav(db: Session, user: Optional[models.User] = None):
    return [
        {
            "id": b.id,
            "name": b.name,
            "color": b.color,
            "role": get_board_role(b.id, user, db) if user else None,
            "is_shared": board_is_shared(b.id, db),
        }
        for b in get_accessible_boards(user, db)
    ]


def login_redirect_response():
    return RedirectResponse(url="/login", status_code=303)


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, digest = password_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    computed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    ).hex()
    return hmac.compare_digest(computed, digest)


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _set_session_cookie(response: Response, token: str):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def _clear_session_cookie(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")


def create_user_session(user: models.User, db: Session) -> str:
    token = secrets.token_urlsafe(32)
    session = models.UserSession(user_id=user.id, token_hash=_hash_session_token(token))
    db.add(session)
    db.commit()
    return token


def ensure_board_membership(board: models.Board, user: models.User, role: str, db: Session):
    existing = (
        db.query(models.BoardMembership)
        .filter(
            models.BoardMembership.board_id == board.id,
            models.BoardMembership.user_id == user.id,
        )
        .first()
    )
    if existing:
        existing.role = role
        return existing
    membership = models.BoardMembership(board_id=board.id, user_id=user.id, role=role)
    db.add(membership)
    return membership


def claim_legacy_boards_for_first_user(user: models.User, db: Session):
    if db.query(models.User).count() != 1:
        return
    legacy_boards = db.query(models.Board).filter(models.Board.owner_user_id.is_(None)).all()
    for board in legacy_boards:
        board.owner_user_id = user.id
        ensure_board_membership(board, user, "owner", db)
    db.commit()


def get_optional_current_user(request: Request, db: Session) -> Optional[models.User]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = (
        db.query(models.UserSession)
        .filter(models.UserSession.token_hash == _hash_session_token(token))
        .first()
    )
    return session.user if session else None


def require_current_user(request: Request, db: Session) -> models.User:
    user = get_optional_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def get_board_membership(board_id: int, user: models.User, db: Session) -> Optional[models.BoardMembership]:
    return (
        db.query(models.BoardMembership)
        .filter(
            models.BoardMembership.board_id == board_id,
            models.BoardMembership.user_id == user.id,
        )
        .first()
    )


def get_board_role(board_id: int, user: models.User, db: Session) -> Optional[str]:
    membership = get_board_membership(board_id, user, db)
    return membership.role if membership else None


def require_board_access(board_id: int, user: models.User, db: Session, min_role: str = "viewer") -> str:
    role = get_board_role(board_id, user, db)
    if not role:
        raise HTTPException(status_code=403, detail="Board access denied")
    if BOARD_ROLE_ORDER.get(role, 0) < BOARD_ROLE_ORDER.get(min_role, 0):
        raise HTTPException(status_code=403, detail="Board access denied")
    return role


def _authorize_board_request(request: Optional[Request], db: Session, board_id: int, min_role: str = "viewer"):
    if request is None:
        return None
    user = require_current_user(request, db)
    require_board_access(board_id, user, db, min_role)
    return user


def _board_id_for_stage(stage_id: int, db: Session) -> Optional[int]:
    stage = db.query(models.Stage).filter(models.Stage.id == stage_id).first()
    return stage.board_id if stage else None


def _board_id_for_task(task_id: int, db: Session) -> Optional[int]:
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    return task.stage.board_id if task and task.stage else None


def _board_id_for_task_type(type_id: int, db: Session) -> Optional[int]:
    task_type = db.query(models.TaskType).filter(models.TaskType.id == type_id).first()
    return task_type.board_id if task_type else None


def _board_id_for_saved_filter(filter_id: int, db: Session) -> Optional[int]:
    saved_filter = db.query(models.SavedFilter).filter(models.SavedFilter.id == filter_id).first()
    return saved_filter.board_id if saved_filter else None


def _board_id_for_automation(auto_id: int, db: Session) -> Optional[int]:
    automation = db.query(models.Automation).filter(models.Automation.id == auto_id).first()
    return automation.board_id if automation else None


def _require_stage_in_board(stage_id: int, board_id: int, db: Session) -> models.Stage:
    stage = db.query(models.Stage).filter(models.Stage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if stage.board_id != board_id:
        raise HTTPException(status_code=400, detail="Stage belongs to a different board")
    return stage


def _require_task_in_board(task_id: int, board_id: int, db: Session) -> models.Task:
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.stage or task.stage.board_id != board_id:
        raise HTTPException(status_code=400, detail="Task belongs to a different board")
    return task


def _require_task_type_in_board(task_type_id: int, board_id: int, db: Session) -> models.TaskType:
    task_type = db.query(models.TaskType).filter(models.TaskType.id == task_type_id).first()
    if not task_type:
        raise HTTPException(status_code=404, detail="Task type not found")
    if task_type.board_id != board_id:
        raise HTTPException(status_code=400, detail="Task type belongs to a different board")
    return task_type


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


def default_filter_definition():
    return {"op": "and", "selected_task_type_id": None, "source_board_ids": [], "rules": []}


def parse_filter_definition(definition: str | None) -> dict:
    parsed = default_filter_definition()
    if not definition:
        return parsed
    try:
        raw = json.loads(definition)
    except json.JSONDecodeError:
        return parsed
    if not isinstance(raw, dict):
        return parsed
    parsed["op"] = raw.get("op") if raw.get("op") in {"and", "or"} else "and"
    parsed["selected_task_type_id"] = raw.get("selected_task_type_id")
    source_board_ids = raw.get("source_board_ids") if isinstance(raw.get("source_board_ids"), list) else []
    parsed["source_board_ids"] = [
        int(board_id)
        for board_id in source_board_ids
        if isinstance(board_id, int) or (isinstance(board_id, str) and board_id.isdigit())
    ]
    rules = raw.get("rules") if isinstance(raw.get("rules"), list) else []
    parsed["rules"] = [
        {
            "field": rule.get("field"),
            "operator": rule.get("operator"),
            "value": rule.get("value"),
        }
        for rule in rules
        if isinstance(rule, dict) and rule.get("field") and rule.get("operator")
    ]
    return parsed


def _validated_filter_definition(
    definition: dict | None,
    owning_board_id: int,
    db: Session,
    user: Optional[models.User] = None,
) -> dict:
    parsed = parse_filter_definition(json.dumps(definition or default_filter_definition()))
    if parsed["selected_task_type_id"] is not None:
        _require_task_type_in_board(parsed["selected_task_type_id"], owning_board_id, db)

    validated_source_board_ids = []
    for board_id in parsed.get("source_board_ids") or []:
        board = db.query(models.Board).filter(models.Board.id == board_id).first()
        if not board:
            raise HTTPException(status_code=400, detail="Invalid source board")
        if user is not None:
            require_board_access(board_id, user, db, "viewer")
        validated_source_board_ids.append(board_id)
    parsed["source_board_ids"] = list(dict.fromkeys(validated_source_board_ids))

    for rule in parsed.get("rules") or []:
        if rule["field"].startswith("custom:"):
            field_id = int(rule["field"].split(":", 1)[1])
            field_def = db.query(models.CustomFieldDef).filter(models.CustomFieldDef.id == field_id).first()
            if not field_def or not field_def.task_type or field_def.task_type.board_id != owning_board_id:
                raise HTTPException(status_code=400, detail="Invalid custom field rule")
            if parsed["selected_task_type_id"] is not None and field_def.task_type_id != parsed["selected_task_type_id"]:
                raise HTTPException(status_code=400, detail="Custom field rule does not match selected type")
    return parsed


def saved_filter_to_dict(saved_filter: models.SavedFilter) -> dict:
    return {
        "id": saved_filter.id,
        "board_id": saved_filter.board_id,
        "name": saved_filter.name,
        "definition": parse_filter_definition(saved_filter.definition),
    }


def stage_to_dict(stage: models.Stage) -> dict:
    return {
        "id": stage.id,
        "name": stage.name,
        "position": stage.position,
        "is_log": stage.is_log,
        "filter_id": stage.filter_id,
        "saved_filter": saved_filter_to_dict(stage.saved_filter) if stage.saved_filter else None,
    }


def _task_field_value(task: models.Task, field: str):
    if field == "title":
        return task.title or ""
    if field == "description":
        return task.description or ""
    if field == "done":
        return task.done
    if field == "due_date":
        return task.due_date
    if field == "color":
        return task.color or ""
    if field == "task_type_id":
        return task.task_type_id
    if field == "has_parent_task":
        return bool(task.parent_task_id)
    if field.startswith("custom:"):
        field_id = int(field.split(":", 1)[1])
        for cfv in task.custom_field_values:
            if cfv.field_def_id == field_id:
                return cfv.value
        return None
    return None


def _rule_matches(task: models.Task, rule: dict) -> bool:
    value = _task_field_value(task, rule["field"])
    operator = rule["operator"]
    expected = rule.get("value")

    if expected == "today":
        expected = date.today().isoformat()

    if rule["field"] in {"done", "has_parent_task"}:
        if isinstance(expected, str):
            expected = expected.lower() == "true"

    if operator == "contains":
        return expected is not None and str(expected).lower() in str(value or "").lower()
    if operator == "eq":
        return value == expected if isinstance(expected, bool) else str(value) == str(expected)
    if operator == "neq":
        return value != expected if isinstance(expected, bool) else str(value) != str(expected)
    if operator == "empty":
        return value is None or str(value).strip() == ""
    if operator == "not_empty":
        return value is not None and str(value).strip() != ""
    if operator == "lt":
        return value is not None and expected is not None and str(value) < str(expected)
    if operator == "gt":
        return value is not None and expected is not None and str(value) > str(expected)
    if operator == "lte":
        return value is not None and expected is not None and str(value) <= str(expected)
    if operator == "gte":
        return value is not None and expected is not None and str(value) >= str(expected)
    return False


def _task_matches_filter(task: models.Task, definition: dict) -> bool:
    if definition.get("selected_task_type_id"):
        if task.task_type_id != definition["selected_task_type_id"]:
            return False
    rules = definition.get("rules") or []
    if not rules:
        return True
    matches = [_rule_matches(task, rule) for rule in rules]
    return all(matches) if definition.get("op") != "or" else any(matches)


def get_stage_tasks(stage: models.Stage, db: Session, current_user: Optional[models.User] = None):
    if not stage.is_log:
        return (
            db.query(models.Task)
            .filter(models.Task.stage_id == stage.id)
            .order_by(models.Task.position)
            .all()
        )

    definition = parse_filter_definition(stage.saved_filter.definition) if stage.saved_filter else default_filter_definition()
    source_board_ids = definition.get("source_board_ids") or [stage.board_id]
    if current_user is not None:
        accessible_board_ids = {board.id for board in get_accessible_boards(current_user, db)}
        source_board_ids = [board_id for board_id in source_board_ids if board_id in accessible_board_ids]
    if not source_board_ids:
        return []
    query = (
        db.query(models.Task)
        .join(models.Stage, models.Task.stage_id == models.Stage.id)
        .filter(
            models.Stage.board_id.in_(source_board_ids),
            models.Stage.id != stage.id,
            or_(models.Stage.is_log == False, models.Stage.is_log.is_(None)),
        )
        .order_by(models.Task.created_at.desc(), models.Task.id.desc())
    )
    return [task for task in query.all() if _task_matches_filter(task, definition)]


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return login_redirect_response()
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "board": None,
            "boards": [],
            "current_user": current_user,
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
    return templates.TemplateResponse(request, "filters.html", {
        "board": {"id": board.id, "name": board.name, "color": board.color},
        "boards": _boards_for_nav(db, current_user),
        "current_user": current_user,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
            "custom_fields": [field_to_dict(f) for f in task.task_type.custom_fields],
        }
    display_color = task.color or (task.task_type.color if task.task_type else None)
    effective_show_description_on_card = (
        task.show_description_on_card
        if task.show_description_on_card is not None
        else (task.task_type.show_description_on_card if task.task_type else False)
    )
    parent_task = None
    if task.parent_task:
        parent_task = {
            "id": task.parent_task.id,
            "title": task.parent_task.title,
            "board_id": task.parent_task.stage.board_id if task.parent_task.stage else None,
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
        "show_description_on_card": task.show_description_on_card,
        "effective_show_description_on_card": effective_show_description_on_card,
        "stage_id": task.stage_id,
        "task_type": task_type,
        "task_type_id": task.task_type_id,
        "color": display_color,
        "position": task.position,
        "done": task.done,
        "custom_field_values": custom_values,
        "checklist": checklist,
    }

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

    db.query(models.ChecklistItem).filter(
        models.ChecklistItem.spawned_task_id.in_(task_ids)
    ).update({"spawned_task_id": None}, synchronize_session=False)

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

def user_to_dict(user: models.User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
    }


def board_membership_to_dict(membership: models.BoardMembership) -> dict:
    return {
        "user_id": membership.user_id,
        "email": membership.user.email,
        "display_name": membership.user.display_name,
        "role": membership.role,
    }


def _validate_membership_role(role: str) -> str:
    if role not in BOARD_ROLE_ORDER:
        raise HTTPException(status_code=400, detail="Invalid membership role")
    return role


def _owner_membership_count(board_id: int, db: Session) -> int:
    return (
        db.query(models.BoardMembership)
        .filter(
            models.BoardMembership.board_id == board_id,
            models.BoardMembership.role == "owner",
        )
        .count()
    )


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
        raise HTTPException(status_code=400, detail="Valid email is required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    existing = db.query(models.User).filter(models.User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = models.User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    claim_legacy_boards_for_first_user(user, db)
    token = create_user_session(user, db)
    _set_session_cookie(response, token)
    return user_to_dict(user)


@app.post("/api/auth/login")
def auth_login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    email = _normalize_email(data.email)
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(data.password or "", user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_user_session(user, db)
    _set_session_cookie(response, token)
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


# ---------------------------------------------------------------------------
# Boards API
# ---------------------------------------------------------------------------

@app.get("/api/boards")
def get_boards(request: Request = None, db: Session = Depends(get_db)):
    if request is None:
        boards = db.query(models.Board).order_by(models.Board.position).all()
        return [
            {
                "id": b.id,
                "name": b.name,
                "color": b.color,
                "position": b.position,
                "is_shared": board_is_shared(b.id, db),
            }
            for b in boards
        ]
    else:
        user = require_current_user(request, db)
        boards = get_accessible_boards(user, db)
        return [
            {
                "id": b.id,
                "name": b.name,
                "color": b.color,
                "position": b.position,
                "role": get_board_role(b.id, user, db),
                "is_shared": board_is_shared(b.id, db),
            }
            for b in boards
        ]

@app.post("/api/boards")
def create_board(data: BoardCreate, db: Session = Depends(get_db), request: Request = None):
    owner_user = require_current_user(request, db) if request is not None else None
    pos = db.query(models.Board).count()
    board = models.Board(
        name=data.name,
        color=data.color or None,
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
    _authorize_board_request(request, db, board_id, "owner")
    role = _validate_membership_role(data.role)
    email = _normalize_email(data.email)
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    membership = ensure_board_membership(board, user, role, db)
    db.commit()
    db.refresh(membership)
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
        .order_by(models.Stage.position)
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
    pos = db.query(models.Stage).filter(models.Stage.board_id == data.board_id).count()
    stage = models.Stage(name=data.name, board_id=data.board_id, position=pos)
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return {**stage_to_dict(stage), "tasks": []}

# NOTE: /api/stages/reorder must be declared before /api/stages/{stage_id}
@app.put("/api/stages/reorder")
def reorder_stages(data: ReorderStages, db: Session = Depends(get_db), request: Request = None):
    if data.ids:
        board_id = _board_id_for_stage(data.ids[0], db)
        if board_id is not None:
            _authorize_board_request(request, db, board_id, "editor")
            for stage_id in data.ids:
                _require_stage_in_board(stage_id, board_id, db)
    for i, stage_id in enumerate(data.ids):
        db.query(models.Stage).filter(models.Stage.id == stage_id).update({"position": i})
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
        db.query(models.ChecklistItem).filter(
            models.ChecklistItem.spawned_task_id.in_(task_ids)
        ).update({"spawned_task_id": None}, synchronize_session=False)
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
    board_id = _board_id_for_task(task_id, db)
    if board_id is not None:
        _authorize_board_request(request, db, board_id, "editor")
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if "task_type_id" in data.model_fields_set and data.task_type_id is not None:
        _require_task_type_in_board(data.task_type_id, task.stage.board_id, db)

    effective_task_type_id = data.task_type_id if "task_type_id" in data.model_fields_set else task.task_type_id
    _validate_custom_fields_for_task(data.custom_fields, effective_task_type_id, task.stage.board_id, db)

    prev_done = task.done

    if data.title is not None:
        task.title = data.title
    if data.description is not None:
        task.description = data.description
    if "due_date" in data.model_fields_set:
        task.due_date = data.due_date or None
    if "task_type_id" in data.model_fields_set:
        task.task_type_id = data.task_type_id
    if "color" in data.model_fields_set:
        task.color = data.color or None
    if "show_description_on_card" in data.model_fields_set:
        task.show_description_on_card = data.show_description_on_card
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
    db.query(models.ChecklistItem).filter(
        models.ChecklistItem.spawned_task_id == task_id
    ).update({"spawned_task_id": None}, synchronize_session=False)
    db.delete(task)
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

    item = models.ChecklistItem(task_id=task_id, title=data.title)
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
            title=data.title,
            stage_id=target_stage_id,
            position=new_pos,
            color=task.task_type.color,
            parent_task_id=task.id,
        )
        db.add(spawned)
        db.flush()
        item.spawned_task_id = spawned.id

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
    db.delete(item)
    db.commit()
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
