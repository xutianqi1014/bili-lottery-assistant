from sqlalchemy import text
from sqlmodel import Session, select

from backend.db.models.problem import ProblemRecord


def list_for_discovery(session: Session, discovery_id: int) -> list[ProblemRecord]:
    return list(
        session.exec(
            select(ProblemRecord)
            .where(ProblemRecord.discovery_run_id == discovery_id)
            .order_by(text("id"))
        ).all()
    )


def list_all(session: Session, limit: int = 100) -> list[ProblemRecord]:
    return list(
        session.exec(select(ProblemRecord).order_by(text("id DESC")).limit(limit)).all()
    )
