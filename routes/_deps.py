"""Shared FastAPI dependencies for route modules."""
from authz import _authorize_board_request, require_current_user
from database import get_db

__all__ = ["get_db", "require_current_user", "_authorize_board_request"]
