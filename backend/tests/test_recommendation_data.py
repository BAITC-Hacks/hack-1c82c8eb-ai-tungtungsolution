from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.recommendation_data import (
    EmployeeNotFoundError,
    RecommendationSnapshot,
    load_snapshot,
)


@pytest.mark.anyio
async def test_loader_maps_schema_and_scopes_personal_queries(
    configured_backend: None,
    recommendation_snapshot: RecommendationSnapshot,
) -> None:
    from app.models import (
        ActivityHistory,
        DatasetMetadata,
        Employee,
        EmployeeSkill,
        Event,
        EventSkill,
        GradeRequirement,
        RoleProfile,
        Skill,
    )

    snapshot = recommendation_snapshot
    profile = snapshot.profile
    employee = Employee(
        employee_id=profile.employee_id,
        role=profile.role,
        grade=profile.grade,
        work_format=profile.work_format,
        last_review_date=profile.last_review_date,
    )
    metadata = [
        DatasetMetadata(
            source_filename=filename,
            dataset="Career Quest",
            version=snapshot.dataset_version,
            as_of_date=snapshot.as_of_date,
        )
        for filename in ("employees.json", "events.json", "skills.json")
    ]
    event_rows = [
        Event(**event.model_dump(exclude={"develops_skills"}))
        for event in snapshot.events
    ]
    effect_rows = [
        EventSkill(event_id=event.event_id, **effect.model_dump())
        for event in snapshot.events
        for effect in event.develops_skills
    ]
    skill_rows = [
        EmployeeSkill(employee_id=profile.employee_id, skill_id=skill, level=level)
        for skill, level in profile.skills.items()
    ]
    target = snapshot.requirements[0]
    requirements = [
        GradeRequirement(
            role=target.role,
            grade=target.grade,
            skill_id=skill,
            required_level=level,
            is_critical=skill in target.critical_skills,
        )
        for skill, level in target.required_skills.items()
    ]
    history = [
        ActivityHistory(
            record_id="ONE",
            employee_id=profile.employee_id,
            event_id="EV_DESIGN",
            date=snapshot.as_of_date,
            status="no_show",
        )
    ]
    lists = [
        metadata,
        skill_rows,
        requirements,
        event_rows,
        effect_rows,
        history,
        ["EV_DESIGN_2"],
        [Skill(skill_id=key, name=name) for key, name in snapshot.skill_names.items()],
    ]
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(
        side_effect=[employee, RoleProfile(role=target.role, grade=target.grade)]
    )
    session.scalars = AsyncMock(
        side_effect=[MagicMock(all=MagicMock(return_value=rows)) for rows in lists]
    )
    loaded = await load_snapshot(cast(AsyncSession, session), profile.employee_id)
    assert loaded.profile == profile
    assert loaded.requirements == snapshot.requirements
    assert loaded.events == snapshot.events
    assert loaded.history[0].employee_id == profile.employee_id
    assert loaded.dismissed_event_ids == ["EV_DESIGN_2"]
    assert loaded.as_of_date == snapshot.as_of_date
    # Employee skills, history and dismissals are all restricted in SQL.
    for index in (1, 5, 6):
        statement = session.scalars.await_args_list[index].args[0]
        assert profile.employee_id in statement.compile().params.values()


@pytest.mark.anyio
async def test_unknown_employee_is_not_empty_data(configured_backend: None) -> None:
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=None)
    with pytest.raises(EmployeeNotFoundError):
        await load_snapshot(cast(AsyncSession, session), "UNKNOWN")
    session.scalars.assert_not_called()


@pytest.mark.anyio
async def test_missing_metadata_raises(configured_backend: None) -> None:
    from app.models import Employee

    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=Employee(employee_id="E1"))
    session.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    with pytest.raises(ValueError, match="metadata"):
        await load_snapshot(cast(AsyncSession, session), "E1")
