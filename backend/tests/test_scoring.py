from datetime import date

import pytest

from app.progress import ActivityRecord, DevelopmentEvent, SkillEffect
from app.scoring import (
    RecommendationFactors,
    check_eligibility,
    format_fit,
    history_affinity,
    rank_candidates,
)
from app.trajectory import DevelopmentProfile, RoleRequirements

SNAPSHOT = date(2026, 10, 1)


def test_weights_match_the_product_formula() -> None:
    factors = RecommendationFactors(
        gap_closure=0.5,
        grade_relevance=1,
        history_affinity=0.25,
        format_fit=0.75,
    )
    assert factors.score == pytest.approx(0.6125)


@pytest.mark.parametrize(
    "update, reason",
    [
        ({"mandatory": True}, "mandatory"),
        ({"target_roles": ["Data Analyst"]}, "wrong_role"),
        ({"target_grades": ["Senior"]}, "wrong_grade"),
        ({"prerequisites": {"SK_SYSTEM_DESIGN": 3}}, "prerequisites_not_met"),
        ({"prerequisites": {"SK_MISSING": 1}}, "prerequisites_not_met"),
        (
            {
                "develops_skills": [
                    SkillEffect(skill_id="SK_SYSTEM_DESIGN", gain=2, max_level=2)
                ]
            },
            "no_effective_gain",
        ),
        ({"develops_skills": []}, "no_effective_gain"),
        (
            {"format": "online", "upcoming_sessions": [date(2026, 9, 30)]},
            "no_upcoming_session",
        ),
    ],
)
def test_eligibility_filters(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
    update: dict[str, object],
    reason: str,
) -> None:
    result = check_eligibility(
        profile,
        design_event.model_copy(update=update),
        [],
        as_of_date=SNAPSHOT,
    )
    assert not result.eligible
    assert reason in result.reasons


def test_completion_and_dismissal_exclusions(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
) -> None:
    row = ActivityRecord(
        record_id="completed",
        employee_id=profile.employee_id,
        event_id=design_event.event_id,
        date=date(2026, 8, 1),
        status="completed",
    )
    result = check_eligibility(profile, design_event, [row], as_of_date=SNAPSHOT)
    assert result.reasons == ["already_completed"]
    dismissed = check_eligibility(
        profile,
        design_event,
        [],
        as_of_date=SNAPSHOT,
        dismissed_event_ids=[design_event.event_id],
    )
    assert dismissed.reasons == ["dismissed"]
    # Another employee's completion never blocks this employee.
    assert check_eligibility(
        profile,
        design_event,
        [row.model_copy(update={"employee_id": "OTHER"})],
        as_of_date=SNAPSHOT,
    ).eligible


def test_club_can_be_repeated_but_an_active_enrollment_is_not_recommended(
    profile: DevelopmentProfile,
    speaking_event: DevelopmentEvent,
) -> None:
    row = ActivityRecord(
        record_id="club",
        employee_id=profile.employee_id,
        event_id="EV_036",
        date=date(2026, 9, 10),
        status="completed",
    )
    assert check_eligibility(
        profile, speaking_event, [row], as_of_date=SNAPSHOT
    ).eligible
    result = check_eligibility(
        profile,
        speaking_event,
        [row.model_copy(update={"status": "in_progress"})],
        as_of_date=SNAPSHOT,
    )
    assert result.reasons == ["in_progress"]


def test_history_affinity_ignores_mandatory_other_employees_and_unfinished_work(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
) -> None:
    mandatory = design_event.model_copy(
        update={"event_id": "MANDATORY", "mandatory": True}
    )
    events = {event.event_id: event for event in [design_event, mandatory]}
    base = ActivityRecord(
        record_id="1",
        employee_id=profile.employee_id,
        event_id=design_event.event_id,
        date=date(2026, 8, 1),
        status="no_show",
    )
    rows = [
        base,
        base.model_copy(update={"record_id": "2", "status": "completed"}),
        base.model_copy(update={"record_id": "3", "status": "declined"}),
        base.model_copy(update={"record_id": "4", "status": "dropped"}),
        base.model_copy(update={"record_id": "5", "status": "in_progress"}),
        base.model_copy(update={"record_id": "6", "event_id": "MANDATORY"}),
        base.model_copy(update={"record_id": "7", "employee_id": "OTHER"}),
        base.model_copy(update={"record_id": "8", "date": date(2026, 10, 2)}),
    ]
    evidence = history_affinity(
        profile, design_event, events, rows, as_of_date=SNAPSHOT
    )
    assert evidence.completed == 1
    assert evidence.unsuccessful == 3
    assert evidence.record_ids == ["1", "2", "3", "4"]
    assert evidence.affinity == pytest.approx(1 / 3)
    assert (
        history_affinity(
            profile, design_event, events, [], as_of_date=SNAPSHOT
        ).affinity
        == 0.5
    )


def test_affinity_matches_shared_skills_even_across_activity_types(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
    speaking_event: DevelopmentEvent,
) -> None:
    mentoring = design_event.model_copy(
        update={"event_id": "MENTOR", "type": "mentoring"}
    )
    history = [
        ActivityRecord(
            record_id="mentor",
            employee_id=profile.employee_id,
            event_id=mentoring.event_id,
            date=date(2026, 8, 1),
            status="completed",
        )
    ]
    events = {
        event.event_id: event for event in [mentoring, design_event, speaking_event]
    }
    assert history_affinity(
        profile,
        design_event,
        events,
        history,
        as_of_date=SNAPSHOT,
    ).affinity == pytest.approx(2 / 3)
    assert (
        history_affinity(
            profile,
            speaking_event,
            events,
            history,
            as_of_date=SNAPSHOT,
        ).affinity
        == 0.5
    )


@pytest.mark.parametrize(
    "work_format, event_format, expected",
    [
        ("remote", "online", 1),
        ("remote", "self_paced", 1),
        ("remote", "offline", 0),
        ("office", "offline", 1),
        ("office", "online", 0.75),
        ("office", "self_paced", 0.75),
        ("hybrid", "online", 1),
        ("hybrid", "offline", 1),
        ("hybrid", "self_paced", 1),
    ],
)
def test_format_heuristic(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
    work_format: str,
    event_format: str,
    expected: float,
) -> None:
    assert (
        format_fit(
            profile.model_copy(update={"work_format": work_format}),
            design_event.model_copy(update={"format": event_format}),
        )
        == expected
    )


def test_history_updates_eligibility_readiness_and_factors_consistently(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
    requirements: list[RoleRequirements],
) -> None:
    advanced = design_event.model_copy(
        update={
            "event_id": "ADVANCED",
            "prerequisites": {"SK_SYSTEM_DESIGN": 3},
        }
    )
    row = ActivityRecord(
        record_id="learned",
        employee_id=profile.employee_id,
        event_id=design_event.event_id,
        date=date(2026, 9, 8),
        status="completed",
    )
    candidates = rank_candidates(
        profile,
        [design_event, advanced],
        [row],
        requirements,
        as_of_date=SNAPSHOT,
    )
    assert [item.event_id for item in candidates] == ["ADVANCED"]
    candidate = candidates[0]
    assert candidate.changes[0].before == 3
    assert candidate.changes[0].after == 4
    assert candidate.readiness_before == 70
    assert candidate.readiness_after == 80
    assert candidate.factors.gap_closure == pytest.approx(1 / 3)
    assert candidate.factors.grade_relevance == 1
    assert candidate.critical_skills_closed == ["SK_SYSTEM_DESIGN"]


def test_ranking_is_deterministic_and_empty_eligibility_is_legitimate(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
    requirements: list[RoleRequirements],
) -> None:
    events = [
        design_event.model_copy(update={"event_id": identifier})
        for identifier in ("Z", "A")
    ]
    ranked = rank_candidates(profile, events, [], requirements, as_of_date=SNAPSHOT)
    assert [candidate.event_id for candidate in ranked] == ["A", "Z"]
    assert (
        rank_candidates(
            profile,
            events,
            [],
            requirements,
            as_of_date=SNAPSHOT,
            dismissed_event_ids=["A", "Z"],
        )
        == []
    )
    with pytest.raises(ValueError, match="Duplicate event IDs"):
        rank_candidates(
            profile, [design_event, design_event], [], requirements, as_of_date=SNAPSHOT
        )


def test_satisfied_requirements_do_not_create_fake_gap_closure(
    profile: DevelopmentProfile,
    design_event: DevelopmentEvent,
    requirements: list[RoleRequirements],
) -> None:
    satisfied = profile.model_copy(
        update={"skills": dict(requirements[0].required_skills)}
    )
    event = design_event.model_copy(
        update={
            "develops_skills": [
                SkillEffect(skill_id="SK_SYSTEM_DESIGN", gain=1, max_level=5),
            ]
        }
    )
    candidate = rank_candidates(
        satisfied, [event], [], requirements, as_of_date=SNAPSHOT
    )[0]
    assert candidate.factors.gap_closure == 0
    assert candidate.factors.grade_relevance == 0
    assert candidate.readiness_before == candidate.readiness_after == 100
