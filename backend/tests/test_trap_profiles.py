from conftest import SNAPSHOT, TrapProfile

from app.scoring import rank_candidates
from app.trajectory import calculate_trajectory


def test_skipped_weakest_skill_prefers_critical_next_grade_skill(
    skipped_weakest_skill: TrapProfile,
) -> None:
    case = skipped_weakest_skill
    assert (
        min(case.profile.skills, key=lambda skill: case.profile.skills[skill])
        == "SK_PUBLIC_SPEAKING"
    )
    candidates = rank_candidates(
        case.profile,
        case.events,
        case.history,
        case.requirements,
        as_of_date=SNAPSHOT,
    )
    assert candidates[0].event_id == "EV_DESIGN"
    club = next(item for item in candidates if item.event_id == "EV_036")
    assert club.history.unsuccessful == 3
    assert club.factors.history_affinity < candidates[0].factors.history_affinity
    assert club.factors.grade_relevance < candidates[0].factors.grade_relevance


def test_irrelevant_weakest_skill_does_not_beat_next_grade_progress(
    irrelevant_weakest_skill: TrapProfile,
) -> None:
    case = irrelevant_weakest_skill
    assert (
        min(case.profile.skills, key=lambda skill: case.profile.skills[skill])
        == "SK_WRITING"
    )
    candidates = rank_candidates(
        case.profile,
        case.events,
        case.history,
        case.requirements,
        as_of_date=SNAPSHOT,
    )
    assert candidates[0].event_id == "EV_DESIGN"
    irrelevant = next(item for item in candidates if item.event_id == "EV_IRRELEVANT")
    assert irrelevant.changes[0].gain > candidates[0].changes[0].gain
    assert irrelevant.factors.gap_closure == 0
    assert irrelevant.factors.grade_relevance == 0


def test_largest_gap_without_event_selects_a_feasible_step(
    largest_gap_without_event: TrapProfile,
) -> None:
    case = largest_gap_without_event
    trajectory = calculate_trajectory(case.profile, case.requirements)
    assert max(trajectory.gaps, key=lambda gap: gap.gap).skill_id == "SK_SYSTEM_DESIGN"
    candidates = rank_candidates(
        case.profile,
        case.events,
        case.history,
        case.requirements,
        as_of_date=SNAPSHOT,
    )
    assert [item.event_id for item in candidates] == ["EV_036"]
    assert candidates[0].readiness_after is not None
    assert candidates[0].readiness_before is not None
    assert candidates[0].readiness_after > candidates[0].readiness_before
