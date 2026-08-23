import json

from sqlmodel import Session, create_engine

from backend.db.engine import init_database
from backend.db.models.problem import ProblemRecord
from backend.db.models.source import SourceProfile
from backend.db.repositories.problems import list_all
from backend.db.repositories.profiles import seed_builtin_profiles, seed_default_profile


def test_default_profile_is_seeded_once():
    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        first = seed_default_profile(session)
        second = seed_default_profile(session)
        assert first.id == second.id
        assert first.mid == "100680137"
        assert json.loads(first.config_json)["activityTypes"] == ["official", "unofficial"]


def test_builtin_profiles_include_nuomi_year_collection_source():
    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        profiles = seed_builtin_profiles(session)

        nuomi = next(profile for profile in profiles if profile.source_key == "nuomi_backpack")
        assert nuomi.mid == "492426375"
        assert nuomi.adapter_key == "nuomi_backpack_v1"
        assert nuomi.latest_per_family == 3
        assert '"readlistStrategy": "largest_year"' in nuomi.config_json
        assert json.loads(nuomi.config_json)["activityTypes"] == ["official", "reservation"]

        tomato = next(profile for profile in profiles if profile.source_key == "tomato_fries")
        assert tomato.mid == "3546836235193146"
        assert tomato.adapter_key == "tomato_fries_v1"
        assert tomato.latest_per_family == 3
        tomato_config = json.loads(tomato.config_json)
        assert tomato_config["readlistName"] == "互动抽奖"
        assert tomato_config["activityTypes"] == ["official", "unofficial", "reservation"]
        assert tomato_config["excludedSections"] == ["charge"]


def test_existing_profile_gets_missing_display_name_without_overwriting_config():
    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        session.add(
            SourceProfile(
                source_key="lottery_toolman",
                mid="100680137",
                upload_url="https://space.bilibili.com/100680137/upload/opus",
                adapter_key="lottery_toolman_v1",
                config_json='{"customFlag": true}',
            )
        )
        session.commit()

        profile = seed_default_profile(session)

        assert '"customFlag": true' in profile.config_json
        assert '"displayName": "你的抽奖工具人"' in profile.config_json


def test_existing_custom_display_name_is_preserved_when_default_label_changes():
    engine = create_engine("sqlite://")
    init_database(engine)
    with Session(engine) as session:
        session.add(
            SourceProfile(
                source_key="lottery_toolman",
                mid="100680137",
                upload_url="https://space.bilibili.com/100680137/upload/opus",
                adapter_key="lottery_toolman_v1",
                config_json='{"displayName": "我自定义的来源"}',
            )
        )
        session.commit()

        profile = seed_default_profile(session)

        assert '"displayName": "我自定义的来源"' in profile.config_json


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
