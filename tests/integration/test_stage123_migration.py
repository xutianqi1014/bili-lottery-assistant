"""File-backed upgrade and source closure limit regression tests."""

import json
import sqlite3

import pytest
from sqlalchemy import inspect
from sqlmodel import Session, create_engine, select

from backend.config import Settings
from backend.db.engine import init_database
from backend.db.models.run import Run, RunItem
from backend.db.models.source import SourceArticle
from backend.source_adapters.lottery_toolman.source_like import (
    SourceLikeOutcomeState,
    SourceLikeWriteResult,
)
from backend.use_cases.source_like_automation import SourceLikeAutomationService
from tests.unit.test_source_like_automation import _Browser, _seed_ready_run, _Transport


def legacy_database(path, *, extra=False):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE activity_origins (
                source_article_id INTEGER NOT NULL, activity_id INTEGER NOT NULL,
                source_position INTEGER NOT NULL, discovered_in_run_id INTEGER NOT NULL,
                PRIMARY KEY (source_article_id, activity_id));
            INSERT INTO activity_origins VALUES (10, 20, 3, 30);
            CREATE TABLE discovery_selections (
                discovery_run_id INTEGER NOT NULL, source_article_id INTEGER NOT NULL,
                readlist_id INTEGER NOT NULL, family VARCHAR NOT NULL,
                selected_rank INTEGER NOT NULL, source_position INTEGER NOT NULL,
                like_state_snapshot VARCHAR NOT NULL, decision VARCHAR NOT NULL,
                decision_reason VARCHAR NOT NULL,
                PRIMARY KEY (discovery_run_id, source_article_id));
            INSERT INTO discovery_selections VALUES
                (30, 10, 40, 'official', 1, 3, 'unliked', 'process', 'legacy');
        """)
        if extra:
            db.execute("ALTER TABLE activity_origins ADD COLUMN custom_data TEXT")
            db.execute("UPDATE activity_origins SET custom_data='preserve-me'")


def test_upgrade_backs_up_old_schema_preserves_rows_and_is_idempotent(tmp_path):
    path = tmp_path / "assistant.sqlite3"
    legacy_database(path)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    init_database(engine)
    backups = list(tmp_path.glob("*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as old:
        columns = [row[1] for row in old.execute("PRAGMA table_info(activity_origins)")]
        assert "source_section" not in columns
        assert old.execute("SELECT * FROM activity_origins").fetchall() == [(10, 20, 3, 30)]
        assert old.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert set(inspect(engine).get_pk_constraint("activity_origins")["constrained_columns"]) == {
        "source_article_id",
        "activity_id",
        "discovered_in_run_id",
    }
    assert set(
        inspect(engine).get_pk_constraint("discovery_selections")["constrained_columns"]
    ) == {"discovery_run_id", "source_article_id", "readlist_id"}
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT source_article_id, activity_id, source_position, discovered_in_run_id "
            "FROM activity_origins"
        ).all() == [(10, 20, 3, 30)]
        assert (
            connection.exec_driver_sql("SELECT decision_reason FROM discovery_selections").scalar()
            == "legacy"
        )
    init_database(engine)
    assert list(tmp_path.glob("*.bak")) == backups
    engine.dispose()


def test_unexpected_legacy_columns_abort_without_losing_data(tmp_path):
    path = tmp_path / "assistant.sqlite3"
    legacy_database(path, extra=True)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with pytest.raises(RuntimeError, match="UNEXPECTED_COLUMNS"):
        init_database(engine)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT custom_data FROM activity_origins").fetchone() == ("preserve-me",)
        assert "source_section" not in [
            r[1] for r in db.execute("PRAGMA table_info(activity_origins)")
        ]
    assert len(list(tmp_path.glob("*.bak"))) == 1
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("count", "limit", "blocked"),
    [
        (0, 15, False),
        (10, 15, False),
        (11, 15, False),
        (15, 15, False),
        (16, 15, True),
        (11, 10, True),
    ],
)
async def test_source_closure_limit_preserves_all_or_nothing_guard(count, limit, blocked):
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, first_id, _ = _seed_ready_run(engine)
    with Session(engine) as session:
        ids = [first_id] if count else []
        for index in range(1, count):
            article = SourceArticle(
                article_id=str(60000000 + index),
                canonical_url=f"https://www.bilibili.com/read/cv{60000000 + index}",
                title="extra",
                like_state="unliked",
            )
            session.add(article)
            session.flush()
            ids.append(article.id)
        run = session.get(Run, run_id)
        run.source_article_ids_json = json.dumps(ids)
        item = session.exec(select(RunItem).where(RunItem.run_id == run_id)).one()
        item.source_article_ids_json = json.dumps(ids)
        session.add_all([run, item])
        session.commit()
    transport = _Transport(
        SourceLikeWriteResult(SourceLikeOutcomeState.SUCCESS, "SOURCE_LIKE_CONFIRMED", "confirmed")
    )
    service = SourceLikeAutomationService(
        Settings(
            source_like_automation_max_items_per_run=limit,
            source_like_automation_delay_min_sec=0,
            source_like_automation_delay_max_sec=0,
        ),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )
    result = await service.execute_ready(run_id)
    if blocked:
        assert result.result_code == "SOURCE_LIKE_AUTOMATION_SCOPE_TOO_LARGE"
        assert transport.calls == []
    else:
        assert result.state == "completed"
        assert len(transport.calls) == count
        await service.execute_ready(run_id)
        assert len(transport.calls) == count
