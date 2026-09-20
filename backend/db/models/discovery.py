from datetime import datetime

from sqlmodel import Field, SQLModel

from .source import utc_now


class DiscoveryRun(SQLModel, table=True):
    __tablename__ = "discovery_runs"

    id: int | None = Field(default=None, primary_key=True)
    source_profile_id: int = Field(foreign_key="source_profiles.id", index=True)
    state: str = Field(default="running", index=True)
    selected_readlists_json: str = "[]"
    latest_per_family: int = 5
    stats_json: str = "{}"
    error_code: str | None = None
    error_detail: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


class DiscoverySelection(SQLModel, table=True):
    __tablename__ = "discovery_selections"

    discovery_run_id: int = Field(foreign_key="discovery_runs.id", primary_key=True)
    source_article_id: int = Field(foreign_key="source_articles.id", primary_key=True)
    readlist_id: int = Field(foreign_key="readlists.id", primary_key=True)
    family: str
    selected_rank: int
    source_position: int
    like_state_snapshot: str
    decision: str
    decision_reason: str
