"""HTML page routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
