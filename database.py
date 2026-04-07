import os
import logging
import time
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

SQLALCHEMY_DATABASE_URL = os.getenv("QUESTLINE_DATABASE_URL", "sqlite:///./questline.db")
logger = logging.getLogger("questline.db")
SLOW_QUERY_MS = float(os.getenv("QUESTLINE_SLOW_QUERY_MS", "200"))

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)


def _sqlite_file_path(url: str) -> str | None:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    path = url[len(prefix):]
    if not path or path == ":memory:":
        return None
    return os.path.abspath(path)


def _harden_sqlite_file_permissions():
    db_path = _sqlite_file_path(SQLALCHEMY_DATABASE_URL)
    if not db_path:
        return
    db_dir = os.path.dirname(db_path)
    if db_dir and os.path.isdir(db_dir):
        os.makedirs(db_dir, mode=0o700, exist_ok=True)
    if os.path.exists(db_path):
        os.chmod(db_path, 0o600)

# Enable foreign key enforcement in SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
            _harden_sqlite_file_permissions()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
    finally:
        cursor.close()


@event.listens_for(engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_start_time = time.perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    elapsed_ms = (time.perf_counter() - context._query_start_time) * 1000
    if elapsed_ms >= SLOW_QUERY_MS:
        logger.warning("slow_query %.1fms %s", elapsed_ms, statement.splitlines()[0][:200])

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
