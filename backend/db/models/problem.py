from datetime import datetime

from sqlmodel import Field, SQLModel

from .source import utc_now


class ProblemRecord(SQLModel, table=True):
    __tablename__ = "problem_records"

    id: int | None = Field(default=None, primary_key=True)
    discovery_run_id: int | None = Field(default=None, foreign_key="discovery_runs.id", index=True)
    source_article_id: int | None = Field(
        default=None,
        foreign_key="source_articles.id",
        index=True,
    )
    problem_url: str
    page_type: str
    stage: str
    problem_code: str
    safe_detail: str
    occurrence_count: int = 1
    status: str = "open"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
