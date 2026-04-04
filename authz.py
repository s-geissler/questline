import hashlib
import hmac
import os
import secrets
from typing import Optional

from fastapi import HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

import models

SESSION_COOKIE = "questline_session"
CSRF_COOKIE = "questline_csrf"
PASSWORD_HASH_ITERATIONS = 120_000
BOARD_ROLE_ORDER = {"viewer": 1, "editor": 2, "owner": 3, "admin": 4}


def _env_flag(name: str) -> Optional[bool]:
    value = os.getenv(name)
    if value is None:
        return None
    return value.lower() in {"1", "true", "yes", "on"}


QUESTLINE_ENV = (os.getenv("QUESTLINE_ENV") or "production").strip().lower()
_session_cookie_secure_override = _env_flag("QUESTLINE_SESSION_COOKIE_SECURE")
_allow_insecure_cookies = _env_flag("QUESTLINE_ALLOW_INSECURE_COOKIES")

if _session_cookie_secure_override is not None:
    SESSION_COOKIE_SECURE = _session_cookie_secure_override
else:
    SESSION_COOKIE_SECURE = not bool(_allow_insecure_cookies)

SESSION_COOKIE_SAMESITE = os.getenv("QUESTLINE_SESSION_COOKIE_SAMESITE", "lax").lower()
if SESSION_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    SESSION_COOKIE_SAMESITE = "lax"


def validate_runtime_security_config():
    if QUESTLINE_ENV == "production":
        if _allow_insecure_cookies:
            raise RuntimeError(
                "QUESTLINE_ALLOW_INSECURE_COOKIES must be disabled when QUESTLINE_ENV=production"
            )
        if not SESSION_COOKIE_SECURE:
            raise RuntimeError(
                "Secure session cookies are required when QUESTLINE_ENV=production"
            )


def get_accessible_boards(user: Optional[models.User], db: Session):
    if not user:
        return []
    if user.role == "admin":
        return db.query(models.Board).order_by(models.Board.position).all()
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


def _board_shared_map(board_ids: list[int], db: Session) -> dict[int, bool]:
    if not board_ids:
        return {}
    rows = (
        db.query(models.BoardMembership.board_id, func.count(models.BoardMembership.id))
        .filter(models.BoardMembership.board_id.in_(board_ids))
        .group_by(models.BoardMembership.board_id)
        .all()
    )
    counts = {board_id: count for board_id, count in rows}
    return {board_id: counts.get(board_id, 0) > 1 for board_id in board_ids}


def _board_role_map(board_ids: list[int], user: Optional[models.User], db: Session) -> dict[int, Optional[str]]:
    if not user or not board_ids:
        return {}
    if user.role == "admin":
        return {board_id: "admin" for board_id in board_ids}
    rows = (
        db.query(models.BoardMembership.board_id, models.BoardMembership.role)
        .filter(
            models.BoardMembership.user_id == user.id,
            models.BoardMembership.board_id.in_(board_ids),
        )
        .all()
    )
    return {board_id: role for board_id, role in rows}


def _boards_for_nav(db: Session, user: Optional[models.User] = None):
    boards = get_accessible_boards(user, db)
    board_ids = [board.id for board in boards]
    shared_map = _board_shared_map(board_ids, db)
    role_map = _board_role_map(board_ids, user, db)
    return [
        {
            "id": b.id,
            "name": b.name,
            "color": b.color,
            "role": role_map.get(b.id) if user else None,
            "is_shared": shared_map.get(b.id, False),
        }
        for b in boards
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


def _hash_csrf_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _set_session_cookie(response: Response, token: str, csrf_token: str):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
        secure=SESSION_COOKIE_SECURE,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        samesite=SESSION_COOKIE_SAMESITE,
        secure=SESSION_COOKIE_SECURE,
        path="/",
    )


def _clear_session_cookie(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def create_user_session(user: models.User, db: Session) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    session = models.UserSession(
        user_id=user.id,
        token_hash=_hash_session_token(token),
        csrf_token_hash=_hash_csrf_token(csrf_token),
    )
    db.add(session)
    db.commit()
    return token, csrf_token


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
    if not session or not session.user:
        return None
    if not session.user.is_active:
        db.delete(session)
        db.commit()
        return None
    return session.user


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
    if user.role == "admin":
        return "admin"
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


def _owner_membership_count(board_id: int, db: Session) -> int:
    return (
        db.query(models.BoardMembership)
        .filter(
            models.BoardMembership.board_id == board_id,
            models.BoardMembership.role == "owner",
        )
        .count()
    )


def user_to_dict(user: models.User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
    }


def board_membership_to_dict(membership: models.BoardMembership) -> dict:
    return {
        "user_id": membership.user_id,
        "email": membership.user.email,
        "display_name": membership.user.display_name,
        "role": membership.role,
        "account_role": membership.user.role,
        "is_active": membership.user.is_active,
    }


def require_admin(request: Request, db: Session) -> models.User:
    user = require_current_user(request, db)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access denied")
    return user
