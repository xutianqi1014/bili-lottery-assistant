from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class SourceProfile(SQLModel, table=True):
    __tablename__ = "source_profiles"

    id: int | None = Field(default=None, primary_key=True)
    source_key: str = Field(index=True, unique=True)
    platform: str = "bilibili"
    mid: str = Field(index=True)
    upload_url: str = Field(unique=True)
    adapter_key: str = Field(index=True)
    enabled: bool = True
    latest_per_family: int = 5
    config_json: str = "{}"
    last_discovery_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Readlist(SQLModel, table=True):
    __tablename__ = "readlists"

    id: int | None = Field(default=None, primary_key=True)
    source_profile_id: int = Field(foreign_key="source_profiles.id", index=True)
    rl_id: str = Field(index=True)
    canonical_url: str = Field(unique=True)
    family: str = Field(index=True)
    title: str
    normalized_title: str
    suffix_value: int
    item_count: int | None = None
    display_updated_text: str | None = None
    observed_updated_at: datetime | None = None
    source_mid: str | None = None
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)


class SourceArticle(SQLModel, table=True):
    __tablename__ = "source_articles"

    id: int | None = Field(default=None, primary_key=True)
    article_id: str = Field(unique=True, index=True)
    canonical_url: str = Field(unique=True)
    title: str
    published_at: datetime | None = None
    like_state: str = "unknown"
    like_checked_at: datetime | None = None
    content_fingerprint: str | None = None
    parse_stats_json: str = "{}"
    parse_status: str = "not_checked"
    parse_checked_at: datetime | None = None
    parse_error_code: str | None = None
    first_seen_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReadlistEntry(SQLModel, table=True):
    __tablename__ = "readlist_entries"

    readlist_id: int = Field(foreign_key="readlists.id", primary_key=True)
    source_article_id: int = Field(foreign_key="source_articles.id", primary_key=True)
    position: int
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
