from conftest import OrganizerData

from app.progress import effective_skills
from app.scoring import rank_candidates
from app.trajectory import calculate_trajectory


def test_all_organizer_profiles_produce_valid_reproducible_domain_results(
    organizer_data: OrganizerData,
) -> None:
    data = organizer_data
    assert len(data.profiles) == 200
    assert len(data.events) == 40
    assert len(data.history) == 2743
    events = {event.event_id: event for event in data.events}
    for profile in data.profiles:
        skills = effective_skills(
            profile, events, data.history, as_of_date=data.as_of_date
        )
        assert all(
            profile.skills.get(skill, 0) <= level <= 5
            for skill, level in skills.items()
        )
        trajectory = calculate_trajectory(
            profile.model_copy(update={"skills": skills}), data.requirements
        )
        if profile.grade == "Lead":
            assert trajectory.target_grade is None
        else:
            assert trajectory.readiness is not None
            assert 0 <= trajectory.readiness <= 100

        candidates = rank_candidates(
            profile,
            data.events,
            data.history,
            data.requirements,
            as_of_date=data.as_of_date,
        )
        own_history = [
            row for row in data.history if row.employee_id == profile.employee_id
        ]
        assert candidates == rank_candidates(
            profile,
            list(reversed(data.events)),
            own_history,
            data.requirements,
            as_of_date=data.as_of_date,
        )
        completed = {row.event_id for row in own_history if row.status == "completed"}
        assert len(candidates) == len({candidate.event_id for candidate in candidates})
        for candidate in candidates:
            assert candidate.event_id not in completed or candidate.event_id == "EV_036"
            assert not events[candidate.event_id].mandatory
            assert 0 <= candidate.score <= 1
            assert candidate.changes
            assert all(
                change.gain > 0 and change.after <= 5 for change in candidate.changes
            )
            if candidate.readiness_before is not None:
                assert candidate.readiness_after is not None
                assert candidate.readiness_after >= candidate.readiness_before
