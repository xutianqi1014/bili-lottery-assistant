from backend.activity_engine.models import ActionResult, ActionState


class WriteDisabledError(RuntimeError):
    """Raised if an unapproved flow tries to perform an external mutation."""


class ManualGate:
    def __init__(self, direct_write_enabled: bool = False):
        self.direct_write_enabled = direct_write_enabled

    def require_confirmation(self, action: str, *, user_confirmed: bool = False) -> None:
        if not self.direct_write_enabled:
            raise WriteDisabledError(f"DIRECT_WRITE_DISABLED:{action}")
        if not user_confirmed:
            raise WriteDisabledError(f"USER_CONFIRMATION_REQUIRED:{action}")

    @staticmethod
    def waiting(message: str) -> ActionResult:
        return ActionResult(
            state=ActionState.WAITING_USER,
            code="MANUAL_GATE_REQUIRED",
            message=message,
            requires_user=True,
        )

