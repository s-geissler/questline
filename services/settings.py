"""Instance-wide settings stored in the database."""
from __future__ import annotations

from sqlalchemy.orm import Session

import models


INSTANCE_SETTINGS_DEFAULTS: dict = {
    "registration_enabled": "true",
    "default_board_color": "#2563eb",
    "new_accounts_active_by_default": "false",
    "instance_theme_color": "#1d4ed8",
    "recurrence_worker_interval_seconds": "60",
}

RECURRENCE_MIN_INTERVAL_SECONDS: int = 5


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
            int(
                str(
                    values.get(
                        "recurrence_worker_interval_seconds",
                        INSTANCE_SETTINGS_DEFAULTS["recurrence_worker_interval_seconds"],
                    )
                ).strip()
                or INSTANCE_SETTINGS_DEFAULTS["recurrence_worker_interval_seconds"]
            ),
        ),
    }
