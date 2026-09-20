"""Minimal SQLite migrations for the local single-user database.

The project intentionally keeps migrations small until the run ledger is
introduced.  ``create_all`` creates a new install, while this module adds the
few columns needed by the next read-only phase to an existing install.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable
from sqlmodel import SQLModel

_ADDITIONS: dict[str, dict[str, str]] = {
    "source_articles": {
        "parse_stats_json": "TEXT NOT NULL DEFAULT '{}'",
        "parse_status": "TEXT NOT NULL DEFAULT 'not_checked'",
        "parse_checked_at": "DATETIME",
        "parse_error_code": "TEXT",
    },
    "readlists": {
        "source_mid": "TEXT",
    },
    "activities": {
        "classification_json": "TEXT NOT NULL DEFAULT '{}'",
        "preflight_checked_at": "DATETIME",
        "runtime_inspected_at": "DATETIME",
        "runtime_selector_version": "TEXT",
    },
    "runs": {
        "status_detail": "TEXT",
    },
    "activity_origins": {
        "source_section": "TEXT",
    },
    "run_items": {
        "runtime_inspected_at": "DATETIME",
        "runtime_selector_version": "TEXT",
        "runtime_inspection_json": "TEXT NOT NULL DEFAULT '{}'",
        "result_code": "TEXT",
        "result_message": "TEXT",
        "source_section": "TEXT",
    },
}


def apply_sqlite_migrations(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    with engine.begin() as connection:
        # SQLite legacy transaction mode does not begin a transaction for DDL.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        for table_name, additions in _ADDITIONS.items():
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, definition in additions.items():
                if column_name in existing:
                    continue
                connection.execute(
                    text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}')
                )

        # Rebuild only the two association tables. Run/RunItem evidence is untouched.
        for name, expected in _SNAPSHOT_KEYS.items():
            current = inspect(connection)
            keys = current.get_pk_constraint(name)["constrained_columns"]
            if set(keys) == expected:
                continue
            table = SQLModel.metadata.tables[name]
            columns = [column.name for column in table.columns]
            if {column["name"] for column in current.get_columns(name)} != set(columns):
                raise RuntimeError(f"SNAPSHOT_MIGRATION_UNEXPECTED_COLUMNS:{name}")
            temporary = name + "_stage123"
            ddl = str(CreateTable(table).compile(dialect=engine.dialect))
            connection.exec_driver_sql(
                ddl.replace(f"CREATE TABLE {name}", f"CREATE TABLE {temporary}", 1)
            )
            fields = ", ".join(f'"{column}"' for column in columns)
            connection.exec_driver_sql(
                f'INSERT INTO "{temporary}" ({fields}) SELECT {fields} FROM "{name}"'
            )
            before = connection.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar()
            after = connection.exec_driver_sql(
                f'SELECT count(*) FROM "{temporary}"'
            ).scalar()
            if before != after:
                raise RuntimeError(f"SNAPSHOT_MIGRATION_ROW_COUNT:{name}")
            connection.exec_driver_sql(f'DROP TABLE "{name}"')
            connection.exec_driver_sql(f'ALTER TABLE "{temporary}" RENAME TO "{name}"')


_SNAPSHOT_KEYS = {
    "activity_origins": {"source_article_id", "activity_id", "discovered_in_run_id"},
    "discovery_selections": {"discovery_run_id", "source_article_id", "readlist_id"},
}


def backup_before_snapshot_migration(engine: Engine) -> Path | None:
    """Consistent SQLite backup before any upgrade; never invent lost history."""
    if engine.dialect.name != "sqlite":
        return None
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    needs_upgrade = any(
        name in names
        and set(inspector.get_pk_constraint(name)["constrained_columns"]) != expected
        for name, expected in _SNAPSHOT_KEYS.items()
    )
    if not needs_upgrade:
        return None
    with engine.connect() as connection:
        database = connection.exec_driver_sql("PRAGMA database_list").first()
        filename = str(database[2]) if database else ""
    if not filename:  # In-memory databases are exclusively used by offline tests.
        return None
    source_path = Path(filename).resolve()
    backup_path = source_path.with_name(
        source_path.name + ".pre-stage123-" + uuid4().hex + ".bak"
    )
    raw = engine.raw_connection()
    try:
        source = raw.driver_connection
        if not isinstance(source, sqlite3.Connection):
            raise RuntimeError("SQLITE_BACKUP_CONNECTION_UNAVAILABLE")
        with closing(sqlite3.connect(backup_path)) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RuntimeError("SQLITE_BACKUP_INTEGRITY_FAILED")
    finally:
        raw.close()
    return backup_path
