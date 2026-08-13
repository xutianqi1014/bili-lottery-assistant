from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from backend.db.models.problem import ProblemRecord


class ProblemRegistry:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def record(
        self,
        *,
        discovery_run_id: int | None,
        source_article_id: int | None,
        problem_url: str,
        page_type: str,
        stage: str,
        problem_code: str,
        safe_detail: str,
    ) -> ProblemRecord:
        safe_url = sanitize_url(problem_url)
        with Session(self.engine) as session:
            row = session.exec(
                select(ProblemRecord).where(
                    ProblemRecord.discovery_run_id == discovery_run_id,
                    ProblemRecord.source_article_id == source_article_id,
                    ProblemRecord.problem_url == safe_url,
                    ProblemRecord.problem_code == problem_code,
                )
            ).first()
            if row is None:
                row = ProblemRecord(
                    discovery_run_id=discovery_run_id,
                    source_article_id=source_article_id,
                    problem_url=safe_url,
                    page_type=page_type,
                    stage=stage,
                    problem_code=problem_code,
                    safe_detail=safe_detail[:1000],
                )
            else:
                row.occurrence_count += 1
            session.add(row)
            session.commit()
            session.refresh(row)
            return row


def sanitize_url(url: str) -> str:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    safe_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in {"spm_id_from", "token", "auth", "csrf", "code"}
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))
