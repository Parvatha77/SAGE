"""Database engine and session helpers."""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        connect_args = (
            {"check_same_thread": False}
            if settings.db_url.startswith("sqlite")
            else {}
        )
        _engine = create_engine(settings.db_url, connect_args=connect_args)
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def create_all() -> None:
    """Create all tables (idempotent)."""
    Base.metadata.create_all(get_engine())
    _apply_migrations()


def _apply_migrations() -> None:
    """Add columns that were introduced after the initial schema (SQLite-safe)."""
    engine = get_engine()
    with engine.connect() as conn:
        from sqlalchemy import text, inspect as sa_inspect
        insp = sa_inspect(engine)
        # AuditEvent.need_id — added in Phase 6
        existing = {c["name"] for c in insp.get_columns("audit_events")}
        if "need_id" not in existing:
            conn.execute(text("ALTER TABLE audit_events ADD COLUMN need_id TEXT"))
            conn.commit()

        # Case.state and Case.thread_id — added in Phase 4 (LangGraph)
        case_cols = {c["name"] for c in insp.get_columns("cases")}
        if "state" not in case_cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN state TEXT"))
            conn.commit()
        if "thread_id" not in case_cols:
            conn.execute(text("ALTER TABLE cases ADD COLUMN thread_id TEXT"))
            conn.commit()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional session scope."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
