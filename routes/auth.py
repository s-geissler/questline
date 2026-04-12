"""Authentication and profile routes."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from authz import (
    SESSION_COOKIE,
    _clear_session_cookie,
    _hash_session_token,
    _normalize_email,
    _set_session_cookie,
    claim_legacy_boards_for_first_user,
    create_user_session,
    get_optional_current_user,
    hash_password,
    require_current_user,
    user_to_dict,
    verify_password,
)
from routes._deps import get_db
from services.audit import _audit_log, _request_client_ip
from services.notifications import create_notification
from services.settings import get_instance_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_EMAIL_LENGTH = 255
MAX_PASSWORD_LENGTH = 4096
MAX_DISPLAY_NAME_LENGTH = 120
LOGIN_WINDOW_SECONDS = 60
LOGIN_MAX_ATTEMPTS = 5
REGISTRATION_WINDOW_SECONDS = 600
REGISTRATION_MAX_ATTEMPTS = 5
REGISTRATION_FAILURE_MIN_DELAY_SECONDS = 0.25

login_attempt_lock = Lock()
login_attempts = defaultdict(deque)
registration_attempt_lock = Lock()
registration_attempts = defaultdict(deque)


class RegisterRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_LENGTH)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    display_name: Optional[str] = Field(default=None, max_length=MAX_DISPLAY_NAME_LENGTH)


class LoginRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_LENGTH)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class PasswordRecoveryRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_LENGTH)


class ProfileUpdate(BaseModel):
    display_name: str = Field(max_length=MAX_DISPLAY_NAME_LENGTH)
    password: Optional[str] = Field(default=None, max_length=MAX_PASSWORD_LENGTH)


def _smooth_registration_failure_timing(started_at: float):
    remaining = REGISTRATION_FAILURE_MIN_DELAY_SECONDS - (time.perf_counter() - started_at)
    if remaining > 0:
        time.sleep(remaining)


def _purge_attempts(attempts: deque, now: float, window_seconds: int):
    while attempts and now - attempts[0] > window_seconds:
        attempts.popleft()


def _login_rate_limit_key(email: str, request: Optional[Request]) -> str:
    return f"{_request_client_ip(request)}:{email}"


def _enforce_login_rate_limit(email: str, request: Optional[Request]):
    key = _login_rate_limit_key(email, request)
    now = time.time()
    with login_attempt_lock:
        attempts = login_attempts[key]
        _purge_attempts(attempts, now, LOGIN_WINDOW_SECONDS)
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")


def _record_login_failure(email: str, request: Optional[Request]):
    key = _login_rate_limit_key(email, request)
    now = time.time()
    with login_attempt_lock:
        attempts = login_attempts[key]
        _purge_attempts(attempts, now, LOGIN_WINDOW_SECONDS)
        attempts.append(now)


def _clear_login_failures(email: str, request: Optional[Request]):
    key = _login_rate_limit_key(email, request)
    with login_attempt_lock:
        login_attempts.pop(key, None)


def _registration_rate_limit_key(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    return _request_client_ip(request)


def _enforce_registration_rate_limit(request: Optional[Request]):
    key = _registration_rate_limit_key(request)
    if key is None:
        return
    now = time.time()
    with registration_attempt_lock:
        attempts = registration_attempts[key]
        _purge_attempts(attempts, now, REGISTRATION_WINDOW_SECONDS)
        if len(attempts) >= REGISTRATION_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many registration attempts. Try again later.")


def _record_registration_attempt(request: Optional[Request]):
    key = _registration_rate_limit_key(request)
    if key is None:
        return
    now = time.time()
    with registration_attempt_lock:
        attempts = registration_attempts[key]
        _purge_attempts(attempts, now, REGISTRATION_WINDOW_SECONDS)
        attempts.append(now)


def notify_admins_password_recovery_requested(user: models.User, db: Session):
    admins = (
        db.query(models.User)
        .filter(
            models.User.role == "admin",
            models.User.is_active.is_(True),
        )
        .order_by(models.User.id)
        .all()
    )
    title = "Password recovery requested"
    body = f"{user.display_name} ({user.email}) requested password recovery assistance."
    for admin in admins:
        create_notification(
            admin.id,
            "password_recovery_requested",
            title,
            body,
            db,
            link_url="/admin",
        )


@router.get("/me")
def auth_me(request: Request, db: Session = Depends(get_db)):
    user = get_optional_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_to_dict(user)


@router.post("/register")
def auth_register(
    data: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
    request: Request = None,
):
    _enforce_registration_rate_limit(request)
    started_at = time.perf_counter()
    try:
        email = _normalize_email(data.email)
        password = data.password or ""
        display_name = (data.display_name or "").strip() or email.split("@", 1)[0]
        if not email or "@" not in email:
            _audit_log("registration_failed", request=request, outcome="failure", reason="invalid_email", email=email or None)
            raise HTTPException(status_code=400, detail="Registration failed")
        if len(password) < 8:
            _audit_log("registration_failed", request=request, outcome="failure", reason="password_too_short", email=email)
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        existing = db.query(models.User).filter(models.User.email == email).first()
        if existing:
            _record_registration_attempt(request)
            _audit_log("registration_failed", request=request, outcome="failure", reason="duplicate_email", email=email)
            raise HTTPException(status_code=400, detail="Registration failed")
        existing_user_count = db.query(models.User).count()
        if existing_user_count > 0 and not get_instance_settings(db)["registration_enabled"]:
            _audit_log("registration_failed", request=request, outcome="failure", reason="registration_disabled", email=email)
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
        _record_registration_attempt(request)
        claim_legacy_boards_for_first_user(user, db)
        if user.is_active:
            token, csrf_token = create_user_session(user, db)
            _set_session_cookie(response, token, csrf_token)
        _audit_log(
            "registration_succeeded",
            request=request,
            actor_user_id=user.id,
            target_user_id=user.id,
            email=user.email,
            details={"role": user.role, "is_active": user.is_active},
        )
        return user_to_dict(user)
    except HTTPException as exc:
        if exc.status_code in {400, 403}:
            _smooth_registration_failure_timing(started_at)
        raise


@router.post("/login")
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
        _audit_log("login_failed", request=request, outcome="failure", reason="invalid_credentials", email=email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        _record_login_failure(email, request)
        _audit_log("login_failed", request=request, target_user_id=user.id, outcome="failure", reason="inactive_account", email=email)
        raise HTTPException(status_code=403, detail="Account is awaiting activation")
    _clear_login_failures(email, request)
    token, csrf_token = create_user_session(user, db)
    _set_session_cookie(response, token, csrf_token)
    _audit_log("login_succeeded", request=request, actor_user_id=user.id, target_user_id=user.id, email=user.email)
    return user_to_dict(user)


@router.post("/password-recovery-request")
def auth_password_recovery_request(
    data: PasswordRecoveryRequest,
    db: Session = Depends(get_db),
    request: Request = None,
):
    email = _normalize_email(data.email)
    user = db.query(models.User).filter(models.User.email == email).first() if email and "@" in email else None
    if user and not user.password_reset_requested:
        user.password_reset_requested = True
        notify_admins_password_recovery_requested(user, db)
        db.commit()
        _audit_log(
            "password_recovery_requested",
            request=request,
            target_user_id=user.id,
            email=user.email,
        )
    return {"ok": True}


@router.post("/logout")
def auth_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    current_user = get_optional_current_user(request, db) if token else None
    if token:
        db.query(models.UserSession).filter(
            models.UserSession.token_hash == _hash_session_token(token)
        ).delete()
        db.commit()
    _clear_session_cookie(response)
    _audit_log(
        "logout_succeeded",
        request=request,
        actor_user_id=current_user.id if current_user else None,
        target_user_id=current_user.id if current_user else None,
    )
    return {"ok": True}


@router.put("/profile")
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
        _audit_log("password_changed", request=request, actor_user_id=user.id, target_user_id=user.id)
    db.refresh(user)
    return user_to_dict(user)
