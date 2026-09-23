import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.progress import ActivityRecord, DevelopmentEvent, SkillEffect
from app.recommendation_data import (
    RecommendationContext,
    RecommendationSnapshot,
    prepare_context,
)
from app.trajectory import DevelopmentProfile, RoleRequirements

SNAPSHOT = date(2026, 10, 1)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def configured_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests never read a developer's credentials or connect to PostgreSQL/OpenAI.
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@127.0.0.1:1/test")
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "unit-test-model")


@pytest.fixture
def profile() -> DevelopmentProfile:
    return DevelopmentProfile(
        employee_id="TRAP_EMPLOYEE",
        role="Backend Engineer",
        grade="Middle",
        work_format="hybrid",
        skills={"SK_SYSTEM_DESIGN": 2, "SK_PUBLIC_SPEAKING": 0, "SK_PYTHON": 4},
        last_review_date=date(2026, 9, 1),
    )


@pytest.fixture
def requirements() -> list[RoleRequirements]:
    return [
        RoleRequirements(
            role="Backend Engineer",
            grade="Senior",
            required_skills={
                "SK_SYSTEM_DESIGN": 4,
                "SK_PUBLIC_SPEAKING": 2,
                "SK_PYTHON": 4,
            },
            critical_skills=["SK_SYSTEM_DESIGN"],
        )
    ]


@pytest.fixture
def design_event() -> DevelopmentEvent:
    return DevelopmentEvent(
        event_id="EV_DESIGN",
        title="System Design",
        type="course",
        format="self_paced",
        duration_hours=8,
        mandatory=False,
        target_roles=["Backend Engineer"],
        target_grades=["Middle"],
        develops_skills=[SkillEffect(skill_id="SK_SYSTEM_DESIGN", gain=1, max_level=4)],
        prerequisites={},
        upcoming_sessions=[],
    )


@pytest.fixture
def speaking_event(design_event: DevelopmentEvent) -> DevelopmentEvent:
    return design_event.model_copy(
        update={
            "event_id": "EV_036",
            "title": "Public Speaking Club",
            "type": "meetup",
            "format": "offline",
            "develops_skills": [
                SkillEffect(skill_id="SK_PUBLIC_SPEAKING", gain=1, max_level=4)
            ],
            "upcoming_sessions": [date(2026, 10, 8)],
        }
    )


@pytest.fixture
def recommendation_snapshot(
    profile: DevelopmentProfile,
    requirements: list[RoleRequirements],
    design_event: DevelopmentEvent,
    speaking_event: DevelopmentEvent,
) -> RecommendationSnapshot:
    return RecommendationSnapshot(
        profile=profile,
        requirements=requirements,
        events=[
            design_event,
            speaking_event,
            design_event.model_copy(update={"event_id": "EV_DESIGN_2"}),
            design_event.model_copy(update={"event_id": "EV_DESIGN_3"}),
        ],
        history=[],
        dismissed_event_ids=[],
        skill_names={
            "SK_SYSTEM_DESIGN": "System Design",
            "SK_PYTHON": "Python",
            "SK_PUBLIC_SPEAKING": "Public Speaking",
        },
        as_of_date=SNAPSHOT,
        dataset_version="test-1",
    )


@pytest.fixture
def recommendation_context(
    recommendation_snapshot: RecommendationSnapshot,
) -> RecommendationContext:
    return prepare_context(recommendation_snapshot)


@dataclass(frozen=True)
class TrapProfile:
    profile: DevelopmentProfile
    requirements: list[RoleRequirements]
    events: list[DevelopmentEvent]
    history: list[ActivityRecord]


@pytest.fixture
def skipped_weakest_skill(
    profile: DevelopmentProfile,
    requirements: list[RoleRequirements],
    design_event: DevelopmentEvent,
    speaking_event: DevelopmentEvent,
) -> TrapProfile:
    """The weakest skill has three no-shows; next-grade architecture is critical."""
    return TrapProfile(
        profile,
        requirements,
        [speaking_event, design_event],
        [
            ActivityRecord(
                record_id=f"SKIPPED_{day}",
                employee_id=profile.employee_id,
                event_id="EV_036",
                date=date(2026, 8, day),
                status="no_show",
            )
            for day in (1, 8, 15)
        ],
    )


@pytest.fixture
def irrelevant_weakest_skill(
    profile: DevelopmentProfile,
    requirements: list[RoleRequirements],
    design_event: DevelopmentEvent,
) -> TrapProfile:
    """The largest raw gain improves a skill absent from next-grade requirements."""
    irrelevant_event = design_event.model_copy(
        update={
            "event_id": "EV_IRRELEVANT",
            "develops_skills": [
                SkillEffect(skill_id="SK_WRITING", gain=3, max_level=5)
            ],
        }
    )
    return TrapProfile(
        profile.model_copy(
            update={
                "skills": {
                    "SK_SYSTEM_DESIGN": 2,
                    "SK_PUBLIC_SPEAKING": 2,
                    "SK_PYTHON": 4,
                    "SK_WRITING": 0,
                }
            }
        ),
        requirements,
        [irrelevant_event, design_event],
        [],
    )


@pytest.fixture
def largest_gap_without_event(
    profile: DevelopmentProfile,
    requirements: list[RoleRequirements],
    design_event: DevelopmentEvent,
    speaking_event: DevelopmentEvent,
) -> TrapProfile:
    """Architecture is the largest gap, but its only event has unmet prerequisites."""
    return TrapProfile(
        profile.model_copy(
            update={
                "skills": {
                    "SK_SYSTEM_DESIGN": 0,
                    "SK_PUBLIC_SPEAKING": 1,
                    "SK_PYTHON": 4,
                }
            }
        ),
        requirements,
        [
            design_event.model_copy(update={"prerequisites": {"SK_SYSTEM_DESIGN": 2}}),
            speaking_event,
        ],
        [],
    )


@dataclass(frozen=True)
class OrganizerData:
    profiles: list[DevelopmentProfile]
    requirements: list[RoleRequirements]
    events: list[DevelopmentEvent]
    history: list[ActivityRecord]
    as_of_date: date


@pytest.fixture(scope="session")
def organizer_data() -> OrganizerData:
    """Use the committed organizer files without starting a DB or reading .env."""
    data_dir = Path(__file__).resolve().parents[1] / "data"
    employees = json.loads((data_dir / "employees.json").read_text(encoding="utf-8"))
    skills = json.loads((data_dir / "skills.json").read_text(encoding="utf-8"))
    events = json.loads((data_dir / "events.json").read_text(encoding="utf-8"))
    with (data_dir / "activity_history.csv").open(
        encoding="utf-8-sig", newline=""
    ) as source:
        history = [ActivityRecord.model_validate(row) for row in csv.DictReader(source)]
    return OrganizerData(
        profiles=TypeAdapter(list[DevelopmentProfile]).validate_python(
            employees["employees"]
        ),
        requirements=TypeAdapter(list[RoleRequirements]).validate_python(
            skills["role_profiles"]
        ),
        events=TypeAdapter(list[DevelopmentEvent]).validate_python(events["events"]),
        history=history,
        as_of_date=date.fromisoformat(employees["meta"]["as_of_date"]),
    )
