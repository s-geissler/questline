import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_modules(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("QUESTLINE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("QUESTLINE_ENV", "development")
    monkeypatch.setenv("QUESTLINE_ALLOW_INSECURE_COOKIES", "true")

    for module_name in (
        "main",
        "models",
        "database",
        "authz",
        "filters_logic",
        "routes",
        "routes.auth",
        "routes.boards",
        "routes.stages",
        "routes._deps",
        "routes._helpers",
        "services",
        "services.audit",
        "services.settings",
        "services.tasks",
        "services.notifications",
        "services.automation",
        "services.recurrence",
    ):
        sys.modules.pop(module_name, None)

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    auth = importlib.import_module("routes.auth")
    return database, models, main, auth


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    database, models, main, auth = _load_modules(tmp_path, monkeypatch)
    db = database.SessionLocal()
    try:
        yield {
            "main": main,
            "auth": auth,
            "models": models,
            "database": database,
            "db": db,
        }
    finally:
        db.close()
        database.engine.dispose()
