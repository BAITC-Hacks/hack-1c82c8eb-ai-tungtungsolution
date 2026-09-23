"""Load one employee's recommendation inputs and prepare a consistent tool context."""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.progress import ActivityRecord, DevelopmentEvent, effective_skills
from app.scoring import Candidate, rank_candidates
from app.trajectory import (
    DevelopmentProfile,
    RoleRequirements,
    Trajectory,
    calculate_trajectory,
    next_grade,
)


class EmployeeNotFoundError(LookupError):
    pass


class RecommendationSnapshot(BaseModel):
    profile: DevelopmentProfile
    requirements: list[RoleRequirements]
    events: list[DevelopmentEvent]
    history: list[ActivityRecord]
    dismissed_event_ids: list[str]
    skill_names: dict[str, str]
    as_of_date: date
    dataset_version: str


@dataclass(frozen=True)
class RecommendationContext:
    snapshot: RecommendationSnapshot
    profile: DevelopmentProfile
    trajectory: Trajectory
    candidates: list[Candidate]
    history_summary: dict[str, object]


def prepare_context(snapshot: RecommendationSnapshot) -> RecommendationContext:
    if any(row.employee_id != snapshot.profile.employee_id for row in snapshot.history):
        raise ValueError("Recommendation history must belong to the selected employee")
    events = {event.event_id: event for event in snapshot.events}
    levels = effective_skills(
        snapshot.profile, events, snapshot.history, as_of_date=snapshot.as_of_date
    )
    profile = snapshot.profile.model_copy(update={"skills": levels})
    trajectory = calculate_trajectory(profile, snapshot.requirements)
    candidates = rank_candidates(
        snapshot.profile,
        snapshot.events,
        snapshot.history,
        snapshot.requirements,
        as_of_date=snapshot.as_of_date,
        dismissed_event_ids=snapshot.dismissed_event_ids,
    )
    used_skills = set(levels) | {skill.skill_id for skill in trajectory.skills}
    used_skills.update(
        change.skill_id for item in candidates for change in item.changes
    )
    if missing := used_skills - snapshot.skill_names.keys():
        raise ValueError(f"Missing skill names: {sorted(missing)}")
    history = [row for row in snapshot.history if row.date <= snapshot.as_of_date]
    voluntary = [row for row in history if not events[row.event_id].mandatory]
    return RecommendationContext(
        snapshot=snapshot,
        profile=profile,
        trajectory=trajectory,
        candidates=candidates,
        history_summary={
            "employee_id": profile.employee_id,
            "as_of_date": snapshot.as_of_date.isoformat(),
            "voluntary_status_counts": dict(Counter(row.status for row in voluntary)),
            "mandatory_status_counts": dict(
                Counter(row.status for row in history if events[row.event_id].mandatory)
            ),
            "voluntary_records": [row.model_dump(mode="json") for row in voluntary],
        },
    )


async def load_snapshot(
    session: AsyncSession, employee_id: str
) -> RecommendationSnapshot:
    # Keep importing domain calculations independent of startup config and .env.
    from app.models import (
        ActivityHistory,
        DatasetMetadata,
        Dismissal,
        Employee,
        EmployeeSkill,
        Event,
        EventSkill,
        GradeRequirement,
        RoleProfile,
        Skill,
    )

    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise EmployeeNotFoundError(employee_id)
    metadata = list((await session.scalars(select(DatasetMetadata))).all())
    if {item.source_filename for item in metadata} != {
        "employees.json",
        "events.json",
        "skills.json",
    } or len({(item.dataset, item.version, item.as_of_date) for item in metadata}) != 1:
        raise ValueError(
            "Dataset metadata is missing or inconsistent; load a complete dataset"
        )
    employee_skills = (
        await session.scalars(
            select(EmployeeSkill).where(EmployeeSkill.employee_id == employee_id)
        )
    ).all()
    profile = DevelopmentProfile.model_validate(
        {
            "employee_id": employee.employee_id,
            "role": employee.role,
            "grade": employee.grade,
            "work_format": employee.work_format,
            "skills": {item.skill_id: item.level for item in employee_skills},
            "last_review_date": employee.last_review_date,
        }
    )
    target = next_grade(employee.grade)
    requirements: list[RoleRequirements] = []
    if target is not None:
        role_profile = await session.get(RoleProfile, (employee.role, target))
        if role_profile is None:
            raise ValueError(f"Missing requirements for {employee.role}/{target}")
        rows = (
            await session.scalars(
                select(GradeRequirement).where(
                    GradeRequirement.role == employee.role,
                    GradeRequirement.grade == target,
                )
            )
        ).all()
        requirements.append(
            RoleRequirements(
                role=employee.role,
                grade=target,
                required_skills={item.skill_id: item.required_level for item in rows},
                critical_skills=sorted(
                    item.skill_id for item in rows if item.is_critical
                ),
            )
        )
    event_rows = (await session.scalars(select(Event).order_by(Event.event_id))).all()
    effect_rows = (
        await session.scalars(
            select(EventSkill).order_by(EventSkill.event_id, EventSkill.skill_id)
        )
    ).all()
    events = [
        DevelopmentEvent.model_validate(
            {
                "event_id": event.event_id,
                "title": event.title,
                "type": event.type,
                "format": event.format,
                "duration_hours": event.duration_hours,
                "mandatory": event.mandatory,
                "target_roles": event.target_roles,
                "target_grades": event.target_grades,
                "prerequisites": event.prerequisites,
                "upcoming_sessions": event.upcoming_sessions,
                "develops_skills": [
                    {
                        "skill_id": effect.skill_id,
                        "gain": effect.gain,
                        "max_level": effect.max_level,
                    }
                    for effect in effect_rows
                    if effect.event_id == event.event_id
                ],
            }
        )
        for event in event_rows
    ]
    history = (
        await session.scalars(
            select(ActivityHistory)
            .where(ActivityHistory.employee_id == employee_id)
            .order_by(ActivityHistory.date, ActivityHistory.record_id)
        )
    ).all()
    dismissed = (
        await session.scalars(
            select(Dismissal.event_id)
            .where(Dismissal.employee_id == employee_id)
            .order_by(Dismissal.event_id)
        )
    ).all()
    skills = (await session.scalars(select(Skill).order_by(Skill.skill_id))).all()
    return RecommendationSnapshot(
        profile=profile,
        requirements=requirements,
        events=events,
        history=[
            ActivityRecord.model_validate(row, from_attributes=True) for row in history
        ],
        dismissed_event_ids=sorted(set(dismissed)),
        skill_names={skill.skill_id: skill.name for skill in skills},
        as_of_date=metadata[0].as_of_date,
        dataset_version=metadata[0].version,
    )
