"""Keep run summary counters aligned with the current run-item states."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from backend.db.models.run import RunItem

_BLOCKED_STATES = frozenset({"blocked", "waiting_user"})
_TERMINAL_STATES = frozenset({"completed", "skipped"})


def reconcile_run_item_stats(
    stats: Mapping[str, Any],
    items: Iterable[RunItem],
) -> dict[str, Any]:
    """Overlay live outcome counters while preserving immutable plan-scope totals.

    ``plannedActivities`` describes how many items entered the confirmed plan and
    therefore remains unchanged.  Outcome counters are derived from current item
    states so completed and historical runs cannot expose stale skip/block totals.
    """

    rows = list(items)
    reconciled = dict(stats)
    reconciled["totalActivities"] = len(rows)
    reconciled["skippedActivities"] = sum(row.state == "skipped" for row in rows)
    reconciled["blockedActivities"] = sum(row.state in _BLOCKED_STATES for row in rows)
    reconciled["waitingUserActivities"] = sum(
        row.state == "waiting_user" for row in rows
    )
    reconciled["terminalActivities"] = sum(
        row.state in _TERMINAL_STATES for row in rows
    )
    reconciled["runtimeInspectedActivities"] = sum(
        row.runtime_inspected_at is not None for row in rows
    )
    reconciled["runtimeUncheckedActivities"] = sum(
        row.runtime_inspected_at is None for row in rows
    )
    return reconciled
