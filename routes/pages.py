"""HTML page routes."""
from __future__ import annotations

import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

import models
from authz import (
    _boards_for_nav,
    get_optional_current_user,
    login_redirect_response,
    require_board_access,
    user_to_dict,
)
from routes._deps import get_db
from services.settings import get_instance_settings
from templates import templates

router = APIRouter(tags=["pages"])

HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _normalize_swatch_color(color: object) -> Optional[str]:
    value = str(color or "").strip().lower()
    if not HEX_COLOR_RE.fullmatch(value):
        return None
    if len(value) == 4:
        return f"#{value[1]}{value[1]}{value[2]}{value[2]}{value[3]}{value[3]}"
    return value


def _custom_field_swatch_colors(board: models.Board) -> set[str]:
    colors = {_normalize_swatch_color(board.color)}
    for task_type in board.task_types:
        colors.add(_normalize_swatch_color(task_type.color))
        for field in task_type.custom_fields:
            colors.add(_normalize_swatch_color(field.color))
            try:
                options = json.loads(field.options) if field.options else []
            except json.JSONDecodeError:
                options = []
            for option in options:
                if isinstance(option, dict):
                    colors.add(_normalize_swatch_color(option.get("color")))
    return {color for color in colors if color}


def _swatch_css(colors: set[str]) -> str:
    return "".join(
        f".swatch-{color.replace('#', '')} {{ background: {color}; }}\n"
        for color in sorted(colors)
    )


def _get_board_or_404(board_id: int, db: Session) -> models.Board:
    board = db.query(models.Board).filter(models.Board.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


@router.get("/", response_class=HTMLResponse)
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


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if get_optional_current_user(request, db):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"board": None, "boards": [], "current_user": None},
    )


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    if get_optional_current_user(request, db):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "register.html",
        {"board": None, "boards": [], "current_user": None},
    )


@router.get("/board/{board_id}", response_class=HTMLResponse)
def board_page(request: Request, board_id: int, db: Session = Depends(get_db)):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return login_redirect_response()
    board = _get_board_or_404(board_id, db)
    board_role = require_board_access(board_id, current_user, db, "viewer")
    return templates.TemplateResponse(request, "board.html", {
        "board": {"id": board.id, "name": board.name, "color": board.color},
        "boards": _boards_for_nav(db, current_user),
        "current_user": current_user,
        "board_role": board_role,
    })


@router.get("/board/{board_id}/custom-field-colors.css")
def board_custom_field_colors_css(request: Request, board_id: int, db: Session = Depends(get_db)):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    board = _get_board_or_404(board_id, db)
    require_board_access(board_id, current_user, db, "viewer")
    return Response(
        content=_swatch_css(_custom_field_swatch_colors(board)),
        media_type="text/css",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/board/{board_id}/task-types", response_class=HTMLResponse)
def task_types_page(request: Request, board_id: int, db: Session = Depends(get_db)):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return login_redirect_response()
    board = _get_board_or_404(board_id, db)
    board_role = require_board_access(board_id, current_user, db, "viewer")
    return templates.TemplateResponse(request, "task_types.html", {
        "board": {"id": board.id, "name": board.name, "color": board.color},
        "boards": _boards_for_nav(db, current_user),
        "current_user": current_user,
        "board_role": board_role,
    })


@router.get("/board/{board_id}/filters", response_class=HTMLResponse)
def filters_page(request: Request, board_id: int, db: Session = Depends(get_db)):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return login_redirect_response()
    board = _get_board_or_404(board_id, db)
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


@router.get("/board/{board_id}/automations", response_class=HTMLResponse)
def automations_page(request: Request, board_id: int, db: Session = Depends(get_db)):
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return login_redirect_response()
    board = _get_board_or_404(board_id, db)
    board_role = require_board_access(board_id, current_user, db, "viewer")
    return templates.TemplateResponse(request, "automations.html", {
        "board": {"id": board.id, "name": board.name, "color": board.color},
        "boards": _boards_for_nav(db, current_user),
        "current_user": current_user,
        "board_role": board_role,
    })


@router.get("/admin", response_class=HTMLResponse)
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
