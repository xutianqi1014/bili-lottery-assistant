from datetime import datetime

from sqlmodel import Field, SQLModel

from .source import utc_now


class Run(SQLModel, table=True):
    """Execution-plan header and locally persisted runtime state.

    Runtime inspection can consume a confirmed plan, but no external write is
    implied by this table or by the current executor.
    """

    __tablename__ = "runs"

    id: int | None = Field(default=None, primary_key=True)
    discovery_run_id: int = Field(foreign_key="discovery_runs.id", index=True)
    state: str = Field(default="awaiting_confirmation", index=True)
    execution_policy: str = "confirm_each"
    family_order_json: str = '["normal", "official"]'
    source_article_ids_json: str = "[]"
    activity_ids_json: str = "[]"
    stats_json: str = "{}"
    direct_write_enabled_snapshot: bool = False
    confirmation_note: str | None = None
    status_detail: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    confirmed_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunItem(SQLModel, table=True):
    """One globally de-duplicated activity in a run plan."""

    __tablename__ = "run_items"

    run_id: int = Field(foreign_key="runs.id", primary_key=True)
    activity_id: int = Field(foreign_key="activities.id", primary_key=True)
    sequence: int = Field(index=True)
    dynamic_id: str
    canonical_url: str
    title: str
    family: str
    mode: str
    unofficial_type: str
    platform_status: str
    # Discovery-time section hint.  ``mode`` is overwritten with the actual
    # runtime classification after the dynamic is opened.
    source_section: str | None = None
    source_article_ids_json: str = "[]"
    action_plan_json: str = "[]"
    state: str = "planned"
    block_reason: str | None = None
    runtime_inspected_at: datetime | None = None
    runtime_selector_version: str | None = None
    runtime_inspection_json: str = "{}"
    result_code: str | None = None
    result_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
