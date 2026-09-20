from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from backend.config import Settings
from backend.db import models  # noqa: F401 - registers all tables
from backend.db.migrations import apply_sqlite_migrations, backup_before_snapshot_migration


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )


def init_database(engine: Engine) -> None:
    backup_before_snapshot_migration(engine)
    SQLModel.metadata.create_all(engine)
    apply_sqlite_migrations(engine)


def open_session(engine: Engine) -> Session:
    return Session(engine, expire_on_commit=False)
