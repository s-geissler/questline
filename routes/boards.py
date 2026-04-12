"""Board and membership routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from authz import (
    _authorize_board_request,
    _board_role_map,
    _board_shared_map,
    _normalize_email,
    _owner_membership_count,
    board_membership_to_dict,
    ensure_board_membership,
    get_accessible_boards,
    get_board_role,
    require_current_user,
)
from routes._deps import get_db
from services.notifications import create_notification
from services.settings import get_instance_settings

router = APIRouter(prefix="/api/boards", tags=["boards"])

MAX_NAME_LENGTH = 120
HEX_COLOR_DETAIL = "Board color must be a valid hex color"


class BoardCreate(BaseModel):
    name: str = Field(max_length=MAX_NAME_LENGTH)
    color: Optional[str] = Field(default=None, max_length=7)


class BoardUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=MAX_NAME_LENGTH)
    color: Optional[str] = Field(default=None, max_length=7)


class BoardMemberCreate(BaseModel):
    email: str = Field(max_length=255)
    role: str = "viewer"


class BoardMemberUpdate(BaseModel):
    role: str


def _validate_membership_role(role: str) -> str:
    if role not in {"viewer", "editor", "owner"}:
        raise HTTPException(status_code=400, detail="Invalid membership role")
    return role


def _validated_optional_hex_color(value: Optional[str], detail: str) -> Optional[str]:
    color = (value or "").strip()
    if not color:
        return None
    if not color.startswith("#") or len(color) not in {4, 7}:
        raise HTTPException(status_code=400, detail=detail)
    if any(ch not in "0123456789abcdefABCDEF" for ch in color[1:]):
        raise HTTPException(status_code=400, detail=detail)
    return color


@router.get("")
def get_boards(request: Request = None, db: Session = Depends(get_db)):
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
            "is_owner": b.owner_user_id == user.id,
        }
        for b in boards
    ]


@router.post("")
def create_board(request: Request = None, data: BoardCreate = None, db: Session = Depends(get_db)):
    owner_user = require_current_user(request, db) if request is not None else None
    instance_settings = get_instance_settings(db)
    pos = db.query(models.Board).count()
    board = models.Board(
        name=data.name,
        color=_validated_optional_hex_color(data.color, HEX_COLOR_DETAIL)
        or instance_settings["default_board_color"]
        or None,
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


@router.put("/{board_id}")
def update_board(board_id: int, request: Request = None, data: BoardUpdate = None, db: Session = Depends(get_db)):
    _authorize_board_request(request, db, board_id, "owner")
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    if data.name is not None:
        board.name = data.name
    if "color" in data.model_fields_set:
        board.color = _validated_optional_hex_color(data.color, HEX_COLOR_DETAIL)
    db.commit()
    return {"id": board.id, "name": board.name, "color": board.color}


@router.delete("/{board_id}")
def delete_board(board_id: int, request: Request = None, db: Session = Depends(get_db)):
    _authorize_board_request(request, db, board_id, "owner")
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    db.delete(board)
    db.commit()
    return {"ok": True}


@router.get("/{board_id}/members")
def get_board_members(board_id: int, request: Request = None, db: Session = Depends(get_db)):
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


@router.post("/{board_id}/members")
def add_board_member(
    board_id: int,
    request: Request = None,
    data: BoardMemberCreate = None,
    db: Session = Depends(get_db),
):
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


@router.put("/{board_id}/members/{user_id}")
def update_board_member(
    board_id: int,
    user_id: int,
    request: Request = None,
    data: BoardMemberUpdate = None,
    db: Session = Depends(get_db),
):
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


@router.delete("/{board_id}/members/{user_id}")
def delete_board_member(board_id: int, user_id: int, request: Request = None, db: Session = Depends(get_db)):
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
