from datetime import datetime

from sqlmodel import Field, SQLModel

from .source import utc_now


class Activity(SQLModel, table=True):
    __tablename__ = "activities"

    id: int | None = Field(default=None, primary_key=True)
    dynamic_id: str = Field(unique=True, index=True)
    canonical_url: str = Field(unique=True)
    title: str = ""
    body_excerpt: str = ""
    mode_detected: str = "unknown"
    unofficial_type: str = "unknown"
    platform_status: str = "unknown"
    classification_json: str = "{}"
    preflight_checked_at: datetime | None = None
    runtime_inspected_at: datetime | None = None
    runtime_selector_version: str | None = None
    discovered_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ActivityOrigin(SQLModel, table=True):
    __tablename__ = "activity_origins"

    source_article_id: int = Field(foreign_key="source_articles.id", primary_key=True)
    activity_id: int = Field(foreign_key="activities.id", primary_key=True)
    source_position: int
    source_section: str | None = None
    discovered_in_run_id: int = Field(foreign_key="discovery_runs.id")
