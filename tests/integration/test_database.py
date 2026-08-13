from sqlmodel import Session, create_engine

from backend.db.engine import init_database
from backend.db.models.problem import ProblemRecord
from backend.db.repositories.problems import list_all
from backend.db.repositories.profiles import seed_default_profile


def test_default_profile_is_seeded_once():
    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        first = seed_default_profile(session)
        second = seed_default_profile(session)
        assert first.id == second.id
        assert first.mid == "100680137"


def test_problem_repository_returns_latest_first():
    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        session.add_all(
            [
                ProblemRecord(
                    discovery_run_id=1,
                    source_article_id=1,
                    problem_url="https://www.bilibili.com/read/cv1",
                    page_type="source_article",
                    stage="test",
                    problem_code="ONE",
                    safe_detail="one",
                ),
                ProblemRecord(
                    discovery_run_id=1,
                    source_article_id=2,
                    problem_url="https://www.bilibili.com/read/cv2",
                    page_type="source_article",
                    stage="test",
                    problem_code="TWO",
                    safe_detail="two",
                ),
            ]
        )
        session.commit()
        rows = list_all(session)
        assert [row.problem_code for row in rows] == ["TWO", "ONE"]
