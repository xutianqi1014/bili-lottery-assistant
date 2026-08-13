from backend.config import Settings

from .lottery_toolman import LotteryToolmanSourceAdapter


def build_adapter_registry(settings: Settings) -> dict[str, LotteryToolmanSourceAdapter]:
    return {"lottery_toolman_v1": LotteryToolmanSourceAdapter(settings)}
