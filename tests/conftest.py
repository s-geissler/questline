import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("QUESTLINE_DATABASE_URL", f"sqlite:///{db_path}")

    for module_name in ("main", "models", "database"):
        sys.modules.pop(module_name, None)

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    db = database.SessionLocal()
    try:
        yield {
            "main": main,
            "models": models,
            "database": database,
            "db": db,
        }
    finally:
        db.close()
        database.engine.dispose()
