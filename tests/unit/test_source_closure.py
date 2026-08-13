import json

from sqlmodel import Session, create_engine

from backend.db.engine import init_database
from backend.db.models.activity import Activity
from backend.db.models.discovery import DiscoveryRun
from backend.db.models.problem import ProblemRecord
from backend.db.models.run import Run, RunItem
from backend.db.models.source import SourceArticle, SourceProfile
from backend.use_cases.source_closure import SourceClosureService


def _seed_closure_run(engine) -> tuple[int, int, int, int]:
    with Session(engine) as session:
        profile = SourceProfile(
            source_key="test-source",
            mid="100",
            upload_url="https://space.bilibili.com/100/upload/opus",
            adapter_key="test",
        )
        session.add(profile)
        session.flush()
        discovery = DiscoveryRun(source_profile_id=profile.id or 0, state="preview_ready")
        session.add(discovery)
        session.flush()
        article_ready = SourceArticle(
            article_id="cv-ready",
            canonical_url="https://www.bilibili.com/read/cv-ready",
            title="已完成来源",
            like_state="unliked",
        )
        article_waiting = SourceArticle(
            article_id="cv-waiting",
            canonical_url="https://www.bilibili.com/read/cv-waiting",
            title="等待来源",
            like_state="unliked",
        )
        article_liked = SourceArticle(
            article_id="cv-liked",
            canonical_url="https://www.bilibili.com/read/cv-liked",
            title="已点赞来源",
            like_state="liked",
        )
        session.add_all([article_ready, article_waiting, article_liked])
        session.flush()
        activities = [
            Activity(
                dynamic_id=f"dynamic-{index}",
                canonical_url=f"https://www.bilibili.com/opus/{index}",
                title=f"动态 {index}",
            )
            for index in range(1, 4)
        ]
        session.add_all(activities)
        session.flush()
        assert discovery.id is not None
        assert article_ready.id is not None
        assert article_waiting.id is not None
        assert article_liked.id is not None
        assert all(activity.id is not None for activity in activities)
        run = Run(
            discovery_run_id=discovery.id,
            source_article_ids_json=json.dumps(
                [article_ready.id, article_waiting.id, article_liked.id]
            ),
        )
        session.add(run)
        session.flush()
        assert run.id is not None
        for activity, article, state in zip(
            activities,
            [article_ready, article_waiting, article_liked],
            ["completed", "waiting_user", "skipped"],
            strict=True,
        ):
            assert activity.id is not None and article.id is not None
            session.add(
                RunItem(
                    run_id=run.id,
                    activity_id=activity.id,
                    sequence=activity.id,
                    dynamic_id=activity.dynamic_id,
                    canonical_url=activity.canonical_url,
                    title=activity.title,
                    family="official",
                    mode="official",
                    unofficial_type="unknown",
                    platform_status="already_participated",
                    source_article_ids_json=json.dumps([article.id]),
                    state=state,
                )
            )
        session.commit()
        return run.id, article_ready.id, article_waiting.id, article_liked.id


def test_source_closure_distinguishes_ready_waiting_and_already_liked():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, ready_id, waiting_id, liked_id = _seed_closure_run(engine)

    summary = SourceClosureService(engine).get(run_id)
    rows = {row.source_article_id: row for row in summary.rows}

    assert summary.ready_to_mark_count == 1
    assert summary.already_liked_count == 1
    assert summary.blocked_count == 1
    assert rows[ready_id].status == "ready_to_mark"
    assert rows[waiting_id].status == "blocked_not_marked"
    assert rows[waiting_id].reason_codes == ("ITEMS_NOT_TERMINAL", "WAITING_USER")
    assert rows[liked_id].status == "already_liked"


def test_open_problem_keeps_source_article_unmarked():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, ready_id, _waiting_id, _liked_id = _seed_closure_run(engine)
    with Session(engine) as session:
        run = session.get(Run, run_id)
        assert run is not None
        problem = ProblemRecord(
            discovery_run_id=run.discovery_run_id,
            source_article_id=ready_id,
            problem_url="https://www.bilibili.com/opus/problem",
            page_type="activity",
            stage="runtime_inspection",
            problem_code="RUNTIME_READ_FAILED",
            safe_detail="manual review required",
        )
        session.add(problem)
        session.commit()

    row = next(
        row
        for row in SourceClosureService(engine).get(run_id).rows
        if row.source_article_id == ready_id
    )
    assert row.status == "blocked_not_marked"
    assert row.open_problem_count == 1
    assert row.reason_codes == ("OPEN_PROBLEMS",)
    assert row.problem_codes == ("RUNTIME_READ_FAILED",)


def test_unknown_like_state_is_not_ready_and_already_liked_stays_skipped():
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, ready_id, _waiting_id, liked_id = _seed_closure_run(engine)
    with Session(engine) as session:
        article = session.get(SourceArticle, ready_id)
        liked = session.get(SourceArticle, liked_id)
        run = session.get(Run, run_id)
        assert article is not None and liked is not None and run is not None
        article.like_state = "unknown"
        session.add(
            ProblemRecord(
                discovery_run_id=run.discovery_run_id,
                source_article_id=liked_id,
                problem_url="https://www.bilibili.com/opus/already-liked",
                page_type="activity",
                stage="runtime_inspection",
                problem_code="ALREADY_HANDLED_WITH_WARNING",
                safe_detail="no source like needed",
            )
        )
        session.add(article)
        session.commit()

    rows = {
        row.source_article_id: row for row in SourceClosureService(engine).get(run_id).rows
    }
    assert rows[ready_id].status == "blocked_not_marked"
    assert rows[ready_id].reason_codes == ("SOURCE_LIKE_STATE_UNKNOWN",)
    assert rows[liked_id].status == "already_liked"
