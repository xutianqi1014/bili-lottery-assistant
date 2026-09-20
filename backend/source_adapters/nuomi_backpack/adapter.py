"""Source adapter for 糯米是个背包's year-organised lottery columns."""

from collections.abc import Sequence

from backend.db.models.source import SourceProfile
from backend.domain.entities import ReadlistCandidate
from backend.domain.ports import BrowserGateway
from backend.source_adapters.compatibility import ReadlistSelection
from backend.source_adapters.lottery_toolman.adapter import LotteryToolmanSourceAdapter
from backend.source_adapters.lottery_toolman.discover_readlists import (
    discover_year_readlist_api,
)


class NuomiBackpackSourceAdapter(LotteryToolmanSourceAdapter):
    """Read the newest year collection and its newest three articles.

    The selected collection contains a mixed queue of interactive and reserve
    lottery dynamics.  It is stored under the official execution family so
    the confirmed-run automation can handle both types without routing a
    reserve card into the comment/repost flow.
    """

    key = "nuomi_backpack_v1"

    async def discover_readlists(
        self, profile: SourceProfile, browser: BrowserGateway | None
    ) -> list[ReadlistCandidate]:
        del browser
        return await discover_year_readlist_api(profile.mid, self.settings.request_timeout_sec)


    @staticmethod
    def select_readlists(
        candidates: Sequence[ReadlistCandidate],
    ) -> Sequence[ReadlistCandidate]:
        """Return the one year collection selected by ``discover_readlists``."""

        if not candidates:
            raise ValueError("READLIST_YEAR_NOT_FOUND")
        selected = max(
            candidates,
            key=lambda candidate: (
                candidate.suffix_value,
                candidate.observed_updated_at or -1,
                candidate.rl_id,
            ),
        )
        return ReadlistSelection([selected])
