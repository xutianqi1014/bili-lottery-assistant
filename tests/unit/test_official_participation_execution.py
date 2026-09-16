import json

import pytest
from sqlmodel import Session, create_engine, select

from backend.activity_engine.official.participation import (
    OfficialParticipationOutcomeState,
    OfficialParticipationWriteResult,
)
from backend.config import Settings
from backend.db.engine import init_database
from backend.db.models.activity import Activity
from backend.db.models.discovery import DiscoveryRun
from backend.db.models.problem import ProblemRecord
from backend.db.models.run import Run, RunItem
from backend.db.models.source import SourceArticle, SourceProfile
from backend.use_cases.official_participation_execution import (
    OfficialParticipationExecutionService,
)


class _Transport:
    def __init__(self, result: OfficialParticipationWriteResult) -> None:
        self.result = result
        self.calls = 0

    async def perform(self, *, target_url: str, payload: dict[str, object]):
        del target_url, payload
        self.calls += 1
        return self.result


class _Browser:
    async def open(self, url: str):
        raise AssertionError(f"DOM browser must not be used by fake transport: {url}")


def _seed_target(engine, *, family: str = "official") -> tuple[int, int]:
    with Session(engine) as session:
        profile = SourceProfile(
            source_key="official-participation-test",
            mid="200",
            upload_url="https://space.bilibili.com/200/upload/opus",
            adapter_key="test",
        )
        session.add(profile)
        session.flush()
        discovery = DiscoveryRun(source_profile_id=profile.id or 0, state="preview_ready")
        article = SourceArticle(
            article_id="official-source",
            canonical_url="https://www.bilibili.com/read/cvofficial-source",
            title="official source",
            like_state="unliked",
        )
        activity = Activity(
            dynamic_id="12345",
            canonical_url="https://www.bilibili.com/opus/12345",
            title="official test",
        )
        session.add_all([discovery, article, activity])
        session.flush()
        assert discovery.id is not None and activity.id is not None and article.id is not None
        run = Run(
            discovery_run_id=discovery.id,
            state="confirmed_waiting_user",
            source_article_ids_json=json.dumps([article.id]),
        )
        session.add(run)
        session.flush()
        assert run.id is not None
        session.add(
            RunItem(
                run_id=run.id,
                activity_id=activity.id,
                sequence=1,
                dynamic_id=activity.dynamic_id,
                canonical_url=activity.canonical_url,
                title=activity.title,
                family=family,
                mode="official",
                unofficial_type="unknown",
                platform_status="unchecked",
                source_article_ids_json=json.dumps([article.id]),
                state="planned",
            )
        )
        session.commit()
        return run.id, activity.id


def _settings(*, enabled: bool) -> Settings:
    return Settings(
        official_automation_enabled=enabled,
    )


def _seed_prior_success(engine, run_id: int, activity_id: int) -> int:
    with Session(engine) as session:
        current_run = session.get(Run, run_id)
        current_item = session.get(RunItem, (run_id, activity_id))
        assert current_run is not None and current_item is not None
        prior = Run(
            discovery_run_id=current_run.discovery_run_id,
            state="completed",
            source_article_ids_json=current_run.source_article_ids_json,
        )
        session.add(prior)
        session.flush()
        assert prior.id is not None
        session.add(
            RunItem(
                run_id=prior.id,
                activity_id=activity_id,
                sequence=1,
                dynamic_id=current_item.dynamic_id,
                canonical_url=current_item.canonical_url,
                title=current_item.title,
                family="official",
                mode="official",
                unofficial_type="unknown",
                platform_status="participated",
                state="completed",
                result_code="OFFICIAL_PARTICIPATION_CONFIRMED",
                result_message="prior confirmed result",
            )
        )
        session.commit()
        return prior.id


@pytest.mark.asyncio
async def test_success_persists_item_terminal_state_and_is_idempotent(tmp_path) -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed_target(engine)
    transport = _Transport(
        OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.SUCCESS,
            "OFFICIAL_PARTICIPATION_CONFIRMED",
            "confirmed",
        )
    )
    service = OfficialParticipationExecutionService(
        _settings(enabled=True),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )

    result = await service.execute(run_id, activity_id=activity_id)
    assert result["state"] == "completed"
    assert transport.calls == 1
    with Session(engine) as session:
        item = session.get(RunItem, (run_id, activity_id))
        run = session.get(Run, run_id)
        assert item is not None and item.state == "completed"
        assert item.platform_status == "participated"
        assert run is not None
        record = json.loads(run.stats_json)["officialParticipationWrites"][str(activity_id)]
        assert record["state"] == "completed"
        assert record["checkpoint"]["checkpoint"]["state"] == "confirmed"

    repeated = await service.execute(run_id, activity_id=activity_id)
    assert repeated["state"] == "completed"
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_disabled_automation_gate_never_calls_transport(tmp_path) -> None:
    del tmp_path
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed_target(engine)
    transport = _Transport(
        OfficialParticipationWriteResult(OfficialParticipationOutcomeState.SUCCESS, "OK", "no")
    )
    service = OfficialParticipationExecutionService(
        _settings(enabled=False),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )
    with pytest.raises(ValueError, match="OFFICIAL_PARTICIPATION_AUTOMATION_DISABLED"):
        await service.execute(run_id, activity_id=activity_id)
    assert transport.calls == 0


@pytest.mark.asyncio
async def test_unknown_result_is_terminal_and_cannot_retry(tmp_path) -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed_target(engine)
    transport = _Transport(
        OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.UNKNOWN,
            "OFFICIAL_PARTICIPATION_TERMINAL_STATE_UNKNOWN",
            "unknown",
        )
    )
    service = OfficialParticipationExecutionService(
        _settings(enabled=True),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )
    result = await service.execute(run_id, activity_id=activity_id)
    assert result["state"] == "blocked_unknown"
    with Session(engine) as session:
        problem = session.exec(
            select(ProblemRecord).where(
                ProblemRecord.problem_code == "OFFICIAL_PARTICIPATION_TERMINAL_STATE_UNKNOWN"
            )
        ).first()
        assert problem is not None and problem.problem_url.endswith("/opus/12345")
    with pytest.raises(ValueError, match="OFFICIAL_PARTICIPATION_WRITE_TERMINAL_NO_RETRY"):
        await service.execute(run_id, activity_id=activity_id)
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_non_official_item_is_rejected_before_authorization(tmp_path) -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed_target(engine, family="normal")
    service = OfficialParticipationExecutionService(
        _settings(enabled=True),
        engine,
        _Browser(),
    )
    with pytest.raises(ValueError, match="OFFICIAL_PARTICIPATION_TARGET_NOT_OFFICIAL"):
        await service.execute(run_id, activity_id=activity_id)


@pytest.mark.asyncio
async def test_runtime_official_item_from_mixed_source_is_in_authorized_scope(tmp_path) -> None:
    del tmp_path
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed_target(engine, family="normal")
    transport = _Transport(
        OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.SUCCESS,
            "OFFICIAL_PARTICIPATION_CONFIRMED",
            "confirmed",
        )
    )
    service = OfficialParticipationExecutionService(
        _settings(enabled=True),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )

    result = await service.execute(
        run_id,
        activity_id=activity_id,
        source_policy_authorized=True,
    )

    assert result["state"] == "completed"
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_official_automation_does_not_require_general_direct_write_switch(tmp_path) -> None:
    del tmp_path
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed_target(engine)
    settings = _settings(enabled=True)
    settings.enable_direct_write_api = False
    transport = _Transport(
        OfficialParticipationWriteResult(OfficialParticipationOutcomeState.SUCCESS, "OK", "no")
    )
    service = OfficialParticipationExecutionService(
        settings,
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )

    result = await service.execute(run_id, activity_id=activity_id)

    assert result["state"] == "completed"
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_expired_target_is_terminal_skip_without_problem(tmp_path) -> None:
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed_target(engine)
    transport = _Transport(
        OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.EXPIRED,
            "LOTTERY_EXPIRED",
            "ended",
        )
    )
    service = OfficialParticipationExecutionService(
        _settings(enabled=True),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )

    result = await service.execute(run_id, activity_id=activity_id)

    assert result["state"] == "completed"
    with Session(engine) as session:
        item = session.get(RunItem, (run_id, activity_id))
        assert item is not None
        assert item.state == "skipped"
        assert item.platform_status == "expired"
        assert session.exec(select(ProblemRecord)).first() is None


@pytest.mark.asyncio
async def test_prior_confirmed_participation_does_not_override_live_marker(tmp_path) -> None:
    del tmp_path
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed_target(engine)
    _seed_prior_success(engine, run_id, activity_id)
    transport = _Transport(
        OfficialParticipationWriteResult(OfficialParticipationOutcomeState.SUCCESS, "OK", "no")
    )
    service = OfficialParticipationExecutionService(
        _settings(enabled=True),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )

    result = await service.execute(run_id, activity_id=activity_id)

    assert result["resultCode"] == "OK"
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_pre_click_unknown_cannot_be_overridden_by_later_history(tmp_path) -> None:
    del tmp_path
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed_target(engine)
    transport = _Transport(
        OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.UNKNOWN,
            "OFFICIAL_LOTTERY_PAGE_READ_UNKNOWN",
            "page closed before any click",
        )
    )
    service = OfficialParticipationExecutionService(
        _settings(enabled=True),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )
    first = await service.execute(run_id, activity_id=activity_id)
    assert first["state"] == "blocked_unknown"
    _seed_prior_success(engine, run_id, activity_id)

    with pytest.raises(ValueError, match="OFFICIAL_PARTICIPATION_WRITE_TERMINAL_NO_RETRY"):
        await service.execute(run_id, activity_id=activity_id)

    assert transport.calls == 1
    with Session(engine) as session:
        item = session.get(RunItem, (run_id, activity_id))
        run = session.get(Run, run_id)
        assert item is not None and item.state == "waiting_user"
        assert item.result_code == "OFFICIAL_LOTTERY_PAGE_READ_UNKNOWN"
        assert run is not None
        record = json.loads(run.stats_json)["officialParticipationWrites"][str(activity_id)]
        assert record["resultCode"] == "OFFICIAL_LOTTERY_PAGE_READ_UNKNOWN"


@pytest.mark.asyncio
async def test_explicit_panel_expiry_reconciles_pre_click_failure_without_retry(tmp_path) -> None:
    del tmp_path
    engine = create_engine("sqlite://")
    init_database(engine)
    run_id, activity_id = _seed_target(engine)
    transport = _Transport(
        OfficialParticipationWriteResult(
            OfficialParticipationOutcomeState.FAILED,
            "OFFICIAL_PARTICIPATION_BUTTON_NOT_FOUND",
            "button was not hydrated",
        )
    )
    service = OfficialParticipationExecutionService(
        _settings(enabled=True),
        engine,
        _Browser(),
        transport_factory=lambda: transport,
    )
    first = await service.execute(run_id, activity_id=activity_id)
    assert first["state"] == "blocked_failed"

    result = service.reconcile_expired_from_panel_evidence(
        run_id,
        activity_id,
        panel_text="抽奖已失效 一等奖名单",
    )

    assert result["resultCode"] == "LOTTERY_EXPIRED"
    assert result["write"]["externalRetry"] is False
    assert transport.calls == 1
    with Session(engine) as session:
        item = session.get(RunItem, (run_id, activity_id))
        assert item is not None
        assert item.state == "skipped"
        assert item.platform_status == "expired"
