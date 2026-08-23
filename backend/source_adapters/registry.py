from backend.config import Settings
from backend.domain.ports import SourceDiscoveryAdapter

from .lottery_toolman import LotteryToolmanSourceAdapter
from .nuomi_backpack import NuomiBackpackSourceAdapter
from .tomato_fries import TomatoFriesSourceAdapter


def build_adapter_registry(settings: Settings) -> dict[str, SourceDiscoveryAdapter]:
    return {
        "lottery_toolman_v1": LotteryToolmanSourceAdapter(settings),
        "nuomi_backpack_v1": NuomiBackpackSourceAdapter(settings),
        "tomato_fries_v1": TomatoFriesSourceAdapter(settings),
    }
