from dataclasses import dataclass

from backend.domain.enums import SourceFamily


@dataclass(frozen=True)
class FamilyConfig:
    family: SourceFamily
    execution_mode: str


@dataclass(frozen=True)
class LotteryToolmanConfig:
    source_key: str = "lottery_toolman"
    mid: str = "100680137"
    upload_url: str = "https://space.bilibili.com/100680137/upload/opus"
    latest_per_family: int = 5
    families: tuple[FamilyConfig, ...] = (
        FamilyConfig(SourceFamily.NORMAL, "unofficial"),
        FamilyConfig(SourceFamily.OFFICIAL, "official"),
    )

