from datetime import date

import pytest

from app.progress import (
    ActivityRecord,
    ActivityStatus,
    DevelopmentEvent,
    SkillEffect,
    apply_skill_gains,
    effective_gain,
    effective_skills,
    simulate_completion,
)
from app.trajectory import DevelopmentProfile, RoleRequirements


@pytest.mark.parametrize(
    "current,gain,cap,expected",
    [
        (0, 2, 5, 2),
        (3, 3, 4, 1),
        (4, 1, 4, 0),
        (5, 1, 3, 0),
        (0, 1, 0, 0),
    ],
)
def test_effective_gain(current: int, gain: int, cap: int, expected: int) -> None:
    assert effective_gain(current, gain, cap) == expected


def test_effects_never_reduce_levels_or_mutate_input() -> None:
    skills = {"a": 5}
    updated = apply_skill_gains(
        skills,
        [
            SkillEffect(skill_id="a", gain=1, max_level=3),
            SkillEffect(skill_id="b", gain=2, max_level=4),
        ],
    )
    assert updated == {"a": 5, "b": 2}
    assert skills == {"a": 5}


def test_duplicate_effect_is_an_error() -> None:
    effect = SkillEffect(skill_id="a", gain=1, max_level=5)
    with pytest.raises(ValueError, match="Duplicate skill effect"):
        apply_skill_gains({}, [effect, effect])


def test_replay_uses_only_own_completed_history_after_assessment(
    profile: DevelopmentProfile,
    speaking_event: DevelopmentEvent,
) -> None:
    rows: list[tuple[str, date, ActivityStatus]] = [
        (profile.employee_id, date(2026, 8, 30), "completed"),
        (profile.employee_id, date(2026, 9, 1), "completed"),
        (profile.employee_id, date(2026, 9, 3), "completed"),
        (profile.employee_id, date(2026, 9, 4), "in_progress"),
        (profile.employee_id, date(2026, 9, 5), "no_show"),
        ("OTHER_EMPLOYEE", date(2026, 9, 8), "completed"),
        (profile.employee_id, date(2026, 10, 2), "completed"),
    ]
    history = [
        ActivityRecord(
            record_id=str(index),
            employee_id=employee,
            event_id="EV_036",
            date=day,
            status=status,
        )
        for index, (employee, day, status) in enumerate(rows)
    ]
    events = {speaking_event.event_id: speaking_event}
    before = dict(profile.skills)
    for _ in range(2):
        updated = effective_skills(
            profile, events, history, as_of_date=date(2026, 10, 1)
        )
        assert updated["SK_PUBLIC_SPEAKING"] == 1
    assert profile.skills == before


def test_replay_sorts_before_applying_different_caps(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
) -> None:
    profile = profile.model_copy(update={"skills": {"SK_SYSTEM_DESIGN": 1}})
    basic = design_event.model_copy(
        update={
            "develops_skills": [
                SkillEffect(skill_id="SK_SYSTEM_DESIGN", gain=2, max_level=2),
            ]
        }
    )
    advanced = design_event.model_copy(
        update={
            "event_id": "ADVANCED",
            "develops_skills": [
                SkillEffect(skill_id="SK_SYSTEM_DESIGN", gain=2, max_level=5)
            ],
        }
    )
    history = [
        ActivityRecord(
            record_id="B",
            employee_id=profile.employee_id,
            event_id=advanced.event_id,
            date=date(2026, 9, 4),
            status="completed",
        ),
        ActivityRecord(
            record_id="A",
            employee_id=profile.employee_id,
            event_id=basic.event_id,
            date=date(2026, 9, 3),
            status="completed",
        ),
    ]
    updated = effective_skills(
        profile,
        {basic.event_id: basic, advanced.event_id: advanced},
        history,
        as_of_date=date(2026, 10, 1),
    )
    assert updated["SK_SYSTEM_DESIGN"] == 4


def test_recurring_club_is_capped(
    profile: DevelopmentProfile,
    speaking_event: DevelopmentEvent,
) -> None:
    history = [
        ActivityRecord(
            record_id=str(day),
            employee_id=profile.employee_id,
            event_id="EV_036",
            date=date(2026, 9, day),
            status="completed",
        )
        for day in range(2, 8)
    ]
    assert (
        effective_skills(
            profile,
            {"EV_036": speaking_event},
            history,
            as_of_date=date(2026, 10, 1),
        )["SK_PUBLIC_SPEAKING"]
        == 4
    )


def test_invalid_history_is_not_silently_ignored(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
) -> None:
    row = ActivityRecord(
        record_id="one",
        employee_id=profile.employee_id,
        event_id=design_event.event_id,
        date=date(2026, 9, 3),
        status="completed",
    )
    with pytest.raises(ValueError, match="Unknown event"):
        effective_skills(profile, {}, [row], as_of_date=date(2026, 10, 1))
    with pytest.raises(ValueError, match="Duplicate activity"):
        effective_skills(
            profile,
            {design_event.event_id: design_event},
            [row, row],
            as_of_date=date(2026, 10, 1),
        )
    with pytest.raises(ValueError, match="completed twice"):
        effective_skills(
            profile,
            {design_event.event_id: design_event},
            [row, row.model_copy(update={"record_id": "two"})],
            as_of_date=date(2026, 10, 1),
        )


def test_completion_diff_recomputes_readiness_and_critical_skills(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
) -> None:
    requirements = [
        RoleRequirements(
            role=profile.role,
            grade="Senior",
            required_skills={"SK_SYSTEM_DESIGN": 3, "SK_PYTHON": 4},
            critical_skills=["SK_SYSTEM_DESIGN"],
        )
    ]
    progress = simulate_completion(profile, design_event, requirements)
    assert progress.before.readiness == pytest.approx(600 / 7)
    assert progress.after.readiness == 100
    assert not progress.before.critical_skills_met
    assert progress.after.critical_skills_met
    assert progress.after.promotion_ready
    assert len(progress.changes) == 1
    assert progress.changes[0].gain == 1
    assert profile.skills["SK_SYSTEM_DESIGN"] == 2


def test_recurring_mandatory_training_does_not_break_progress(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
) -> None:
    compliance = design_event.model_copy(
        update={
            "event_id": "EV_001",
            "mandatory": True,
            "develops_skills": [],
        }
    )
    history = [
        ActivityRecord(
            record_id=str(year),
            employee_id=profile.employee_id,
            event_id=compliance.event_id,
            date=date(year, 9, 3),
            status="completed",
        )
        for year in (2025, 2026)
    ]
    assert (
        effective_skills(
            profile,
            {compliance.event_id: compliance},
            history,
            as_of_date=date(2026, 10, 1),
        )
        == profile.skills
    )
