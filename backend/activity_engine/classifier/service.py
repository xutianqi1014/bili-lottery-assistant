from collections.abc import Collection

from backend.activity_engine.models import (
    ActivityClassification,
    ActivityMode,
    ActivitySnapshot,
    UnofficialType,
)


class ActivityClassifier:
    """Classify a visible dynamic without trusting the source readlist family.

    The runtime has three independent classifications, in priority order:
    the visible official lottery entry, the exact ``预约有奖`` reservation
    marker, and finally the non-official fallback.  Source allow-lists are
    applied by the execution service after this classification and never
    rewrite a reservation into an unofficial activity.
    """

    def classify(
        self,
        snapshot: ActivitySnapshot,
        *,
        allowed_modes: Collection[ActivityMode] | None = None,
    ) -> ActivityClassification:
        # Keep the argument for compatibility with callers and integrations;
        # source policy must not change the page-fact classification.
        del allowed_modes
        text = snapshot.actionable_text or snapshot.body_text
        if snapshot.has_official_lottery_entry:
            evidence_codes = ["OFFICIAL_IFRAME_ENTRY"]
            if snapshot.official_lottery_panel_opened:
                evidence_codes.append("OFFICIAL_LOTTERY_PANEL_OPENED")
            if snapshot.official_lottery_panel_error:
                evidence_codes.append(snapshot.official_lottery_panel_error)
            evidence_codes.append(
                "OFFICIAL_ACTIVITY_LIKED_MARKER"
                if snapshot.activity_like_active
                else "OFFICIAL_ACTIVITY_UNLIKED_MARKER"
            )
            return ActivityClassification(
                mode=ActivityMode.OFFICIAL,
                unofficial_type=UnofficialType.UNKNOWN,
                is_expired=snapshot.expired_text,
                is_participated=snapshot.activity_like_active,
                confidence="high",
                evidence_codes=tuple(evidence_codes),
            )
        if snapshot.has_reservation_entry:
            evidence_codes = ["RESERVATION_ENTRY"]
            evidence_codes.append(
                "RESERVATION_ACTIVITY_LIKED_MARKER"
                if snapshot.activity_like_active
                else "RESERVATION_ACTIVITY_UNLIKED_MARKER"
            )
            if snapshot.reservation_active:
                evidence_codes.append("RESERVATION_ALREADY_ACTIVE")
            else:
                evidence_codes.append("RESERVATION_UNBOOKED")
            return ActivityClassification(
                mode=ActivityMode.RESERVATION,
                unofficial_type=UnofficialType.UNKNOWN,
                is_expired=snapshot.expired_text,
                # Reservation state only describes the button.  The dynamic
                # like is the cross-run participation marker shared with the
                # interactive official flow.
                is_participated=snapshot.activity_like_active,
                confidence="high",
                evidence_codes=tuple(evidence_codes),
            )
        return self._classify_unofficial(snapshot, text)

    @staticmethod
    def _classify_unofficial(
        snapshot: ActivitySnapshot,
        text: str,
    ) -> ActivityClassification:
        has_requirement_text = any(keyword in text for keyword in ("评论", "转发", "关注"))
        boosted_by_dom = snapshot.has_forwarded_original
        boosted_by_text = any(
            keyword in text for keyword in ("加码", "翻倍", "额外奖励", "转发加码")
        )
        unofficial_type = (
            UnofficialType.BOOSTED
            if boosted_by_dom or boosted_by_text
            else UnofficialType.NORMAL
        )
        evidence_codes = (
            ["VISIBLE_REQUIREMENT_TEXT"]
            if has_requirement_text
            else ["NON_OFFICIAL_FALLBACK_NO_OFFICIAL_ENTRY"]
        )
        evidence_codes.extend(snapshot.nonofficial_dom_evidence)
        if boosted_by_dom:
            evidence_codes.append("BOOSTED_FORWARDED_OUTER_DYNAMIC")
        elif boosted_by_text:
            evidence_codes.append("BOOSTED_REQUIREMENT_TEXT")
        return ActivityClassification(
            mode=ActivityMode.UNOFFICIAL,
            unofficial_type=unofficial_type,
            is_expired=snapshot.expired_text,
            is_participated=None,
            confidence=(
                "high"
                if boosted_by_dom
                else "medium"
                if has_requirement_text or boosted_by_text
                else "low"
            ),
            evidence_codes=tuple(dict.fromkeys(evidence_codes)),
        )
