"""Admin routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from authz import ensure_board_membership, require_admin, user_to_dict
from routes._deps import get_db
from services.audit import _audit_log
from services.settings import (
    INSTANCE_SETTINGS_DEFAULTS,
    RECURRENCE_MIN_INTERVAL_SECONDS,
    get_instance_settings,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

MAX_PASSWORD_LENGTH = 4096


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


def _validated_hex_color(value: Optional[str], fallback: str, detail: str) -> str:
    color = (value or "").strip() or fallback
    if not color.startswith("#") or len(color) not in {4, 7}:
        raise HTTPException(status_code=400, detail=detail)
    if any(ch not in "0123456789abcdefABCDEF" for ch in color[1:]):
        raise HTTPException(status_code=400, detail=detail)
    return color


def set_instance_settings(db: Session, updates: dict) -> dict:
    for key, value in updates.items():
        row = db.query(models.InstanceSetting).filter(models.InstanceSetting.key == key).first()
        if not row:
            row = models.InstanceSetting(key=key)
            db.add(row)
        row.value = value
    db.commit()
    return get_instance_settings(db)


def _list_boards_internal(db: Session):
    boards = db.query(models.Board).order_by(models.Board.position).all()
    board_ids = [board.id for board in boards]
    shared_rows = (
        db.query(models.BoardMembership.board_id)
        .filter(models.BoardMembership.board_id.in_(board_ids))
        .group_by(models.BoardMembership.board_id)
        .having(func.count(models.BoardMembership.id) > 1)
        .all()
        if board_ids
        else []
    )
    shared_map = {board_id: True for board_id, in shared_rows}
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


@router.get("/users")
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


@router.get("/boards")
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


@router.post("/actions/delete-orphaned-boards")
def delete_admin_orphaned_boards(request: Request, db: Session = Depends(get_db)):
    current_user = require_admin(request, db)
    orphaned_boards = db.query(models.Board).filter(models.Board.owner_user_id.is_(None)).all()
    deleted_board_ids = [board.id for board in orphaned_boards]
    deleted_count = len(deleted_board_ids)
    for board in orphaned_boards:
        db.delete(board)
    db.commit()
    _audit_log(
        "admin_orphaned_boards_deleted",
        request=request,
        actor_user_id=current_user.id,
        details={"deleted_board_ids": deleted_board_ids, "deleted_count": deleted_count},
    )
    return {"ok": True, "deleted_count": deleted_count}


@router.put("/boards/{board_id}/owner")
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


@router.get("/settings")
def get_admin_settings(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    return get_instance_settings(db)


@router.put("/settings")
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


@router.put("/users/{user_id}")
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
        from authz import hash_password  # local import to avoid broad main coupling

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


@router.delete("/users/{user_id}")
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
    owned_board_ids = [board_id for (board_id,) in db.query(models.Board.id).filter(models.Board.owner_user_id == user.id).all()]
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
