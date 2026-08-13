from fastapi import APIRouter, HTTPException, status

router = APIRouter(tags=["preflight"])


@router.post("/api/discoveries/{discovery_id}/preflight")
def removed_preflight(discovery_id: int) -> None:
    """Compatibility tombstone; it must never start a browser job."""
    del discovery_id
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="ACTIVITY_PREFLIGHT_REMOVED",
    )
