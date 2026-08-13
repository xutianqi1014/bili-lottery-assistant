import pytest
from fastapi import HTTPException

from backend.api.routes.preflight import removed_preflight


def test_removed_activity_preflight_is_a_non_starting_tombstone():
    with pytest.raises(HTTPException) as error:
        removed_preflight(123)

    assert getattr(error.value, "status_code", None) == 410
    assert getattr(error.value, "detail", None) == "ACTIVITY_PREFLIGHT_REMOVED"
