import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# ── DB path ───────────────────────────────────────────────────────────────────
# Follows XDG Base Directory spec.
# Override with PAPIS_DB_PATH env var for testing or custom setups.

_xdg_data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
DB_PATH = Path(os.environ.get("PAPIS_DB_PATH", _xdg_data / "papis" / "papis.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ── SQLAlchemy engine ─────────────────────────────────────────────────────────

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={
        "check_same_thread": False,   # required for FastAPI's thread pool
        "timeout": 30,                # wait up to 30 s if DB is locked
    },
    # Keep a small pool; SQLite doesn't benefit from large pools
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,               # discard stale connections silently
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(conn, _record):
    """
    Applied to every new connection from the pool.

    WAL mode:        allows concurrent reads while a write is in progress.
                     Critical because the daemon writes events while the
                     UI is reading them.
    foreign_keys:    enforce FK constraints (SQLite ignores them by default).
    journal_mode:    set to WAL (Write-Ahead Logging).
    synchronous:     NORMAL is safe with WAL and faster than FULL.
    cache_size:      negative value = kibibytes; -64000 = 64 MB page cache.
    temp_store:      store temp tables in memory.
    """
    cursor = conn.cursor()
    cursor.executescript("""
        PRAGMA journal_mode   = WAL;
        PRAGMA foreign_keys   = ON;
        PRAGMA synchronous    = NORMAL;
        PRAGMA cache_size     = -64000;
        PRAGMA temp_store     = MEMORY;
        PRAGMA mmap_size      = 268435456;
    """)
    cursor.close()


# ── Session factory ───────────────────────────────────────────────────────────

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# ── Declarative base (imported by models.py) ──────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── DB initialisation ─────────────────────────────────────────────────────────

def init_db(dev_mode: bool = False):
    """
    Initialise the database.

    dev_mode=True  → fast path: SQLAlchemy create_all().
                     Use during development / unit tests.
                     Safe to call repeatedly — does nothing if tables exist.

    dev_mode=False → production path: runs pending Alembic migrations.
                     Ensures schema is always at `head` on startup.
                     Falls back to create_all() if alembic.ini is missing
                     (e.g. first run from source without packaging).
    """
    if dev_mode:
        from .models import Base as ModelBase
        ModelBase.metadata.create_all(bind=engine)
        return

    # Production: run Alembic migrations
    alembic_ini = Path(__file__).parents[1] / "alembic.ini"
    if alembic_ini.exists():
        try:
            from alembic.config import Config
            from alembic import command as alembic_cmd

            cfg = Config(str(alembic_ini))
            # Override the URL so it always matches the runtime DB_PATH
            cfg.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")
            alembic_cmd.upgrade(cfg, "head")
        except Exception as exc:
            # Log but don't crash — fall back to create_all so the app
            # can still start even if migrations fail unexpectedly.
            import logging
            logging.getLogger("papis.database").error(
                "Alembic migration failed (%s) — falling back to create_all()", exc
            )
            from .models import Base as ModelBase
            ModelBase.metadata.create_all(bind=engine)
    else:
        # alembic.ini not present (running directly from source)
        from .models import Base as ModelBase
        ModelBase.metadata.create_all(bind=engine)


# ── FastAPI dependency ────────────────────────────────────────────────────────

def get_db():
    """
    Yields a SQLAlchemy session for use as a FastAPI dependency.

    Usage:
        @router.get("/")
        def my_route(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Utility ───────────────────────────────────────────────────────────────────

def get_db_size_bytes() -> int:
    """Return the current size of the SQLite database file in bytes."""
    try:
        return DB_PATH.stat().st_size
    except OSError:
        return 0