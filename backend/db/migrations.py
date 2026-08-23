"""Minimal SQLite migrations for the local single-user database.

The project intentionally keeps migrations small until the run ledger is
introduced.  ``create_all`` creates a new install, while this module adds the
few columns needed by the next read-only phase to an existing install.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

_ADDITIONS: dict[str, dict[str, str]] = {
    "source_articles": {
        "parse_stats_json": "TEXT NOT NULL DEFAULT '{}'",
        "parse_status": "TEXT NOT NULL DEFAULT 'not_checked'",
        "parse_checked_at": "DATETIME",
        "parse_error_code": "TEXT",
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
        for table_name, additions in _ADDITIONS.items():
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, definition in additions.items():
                if column_name in existing:
                    continue
                connection.execute(
                    text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}')
                )
