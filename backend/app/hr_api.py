"""HR endpoints for aggregate insights, jury imports and AI audit records."""

from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime
from statistics import fmean
from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth import HRPrincipalDep
from app.db import SessionDep
from app.ingest import (
    DatasetBundle,
    IngestCounts,
    IngestValidationError,
    ingest_dataset,
    parse_employees_json,
    parse_events_json,
    parse_history_csv,
    parse_skills_json,
    validate_dataset,
)
from app.models import (
    ActivityHistory,
    AgentRun,
    DatasetMetadata,
    Employee,
    EmployeeSkill,
    Event,
    EventSkill,
    GradeRequirement,
    Skill,
)
from app.progress import ActivityRecord, DevelopmentEvent, effective_skills
from app.recommendation_service import RecommendationCache
from app.trajectory import (
    DevelopmentProfile,
    RoleRequirements,
    calculate_trajectory,
    next_grade,
)


class DepartmentOverview(BaseModel):
    department: str
    employee_count: int = Field(ge=0)
    employees_with_trajectory: int = Field(ge=0)
    average_readiness: float | None = Field(default=None, ge=0, le=100)


class SkillGapOverview(BaseModel):
    skill_id: str
    name: str
    employees_with_gap: int = Field(ge=1)
    average_gap: float = Field(gt=0, le=5)


class HROverviewOut(BaseModel):
    as_of_date: date
    employee_count: int = Field(ge=0)
    department_count: int = Field(ge=0)
    employees_with_trajectory: int = Field(ge=0)
    promotion_ready_count: int = Field(ge=0)
    average_readiness: float | None = Field(default=None, ge=0, le=100)
    departments: list[DepartmentOverview]
    skill_gaps: list[SkillGapOverview]


class DatasetCountsOut(BaseModel):
    metadata: int = Field(ge=0)
    employees: int = Field(ge=0)
    employee_skills: int = Field(ge=0)
    skills: int = Field(ge=0)
    role_profiles: int = Field(ge=0)
    grade_requirements: int = Field(ge=0)
    events: int = Field(ge=0)
    event_skills: int = Field(ge=0)
    activity_history: int = Field(ge=0)


class DatasetUploadOut(BaseModel):
    status: Literal["loaded"]
    dataset: str
    version: str
    as_of_date: date
    counts: DatasetCountsOut


class AgentRunOut(BaseModel):
    id: int
    employee_id: str | None
    kind: Literal["recommendation", "debug"]
    user_input: str
    answer: str
    steps: list[dict[str, object]]
    created_at: datetime
    latency_ms: int | None
    fallback_used: bool


class AgentRunListOut(BaseModel):
    total: int = Field(ge=0)
    items: list[AgentRunOut]


def _average(values: list[float]) -> float | None:
    return round(fmean(values), 2) if values else None


async def build_overview(session: SessionDep) -> HROverviewOut:
    metadata = list((await session.scalars(select(DatasetMetadata))).all())
    metadata_keys = {
        (row.dataset, row.version, row.as_of_date) for row in metadata
    }
    if {row.source_filename for row in metadata} != {
        "employees.json",
        "events.json",
        "skills.json",
    } or len(metadata_keys) != 1:
        raise ValueError(
            "Dataset metadata is missing or inconsistent; load a complete dataset"
        )
    snapshot_date = metadata[0].as_of_date

    employees = list(
        (await session.scalars(select(Employee).order_by(Employee.employee_id))).all()
    )
    employee_skill_rows = list((await session.scalars(select(EmployeeSkill))).all())
    requirement_rows = list((await session.scalars(select(GradeRequirement))).all())
    event_rows = list((await session.scalars(select(Event))).all())
    effect_rows = list((await session.scalars(select(EventSkill))).all())
    history_rows = list((await session.scalars(select(ActivityHistory))).all())
    skill_rows = list((await session.scalars(select(Skill))).all())

    skills_by_employee: dict[str, dict[str, int]] = defaultdict(dict)
    for row in employee_skill_rows:
        skills_by_employee[row.employee_id][row.skill_id] = row.level

    requirements_by_role_grade: dict[tuple[str, str], list[GradeRequirement]] = (
        defaultdict(list)
    )
    for row in requirement_rows:
        requirements_by_role_grade[(row.role, row.grade)].append(row)

    effects_by_event: dict[str, list[EventSkill]] = defaultdict(list)
    for row in effect_rows:
        effects_by_event[row.event_id].append(row)
    events = {
        row.event_id: DevelopmentEvent.model_validate(
            {
                "event_id": row.event_id,
                "title": row.title,
                "type": row.type,
                "format": row.format,
                "duration_hours": row.duration_hours,
                "mandatory": row.mandatory,
                "target_roles": row.target_roles,
                "target_grades": row.target_grades,
                "prerequisites": row.prerequisites,
                "upcoming_sessions": row.upcoming_sessions,
                "develops_skills": [
                    {
                        "skill_id": effect.skill_id,
                        "gain": effect.gain,
                        "max_level": effect.max_level,
                    }
                    for effect in effects_by_event[row.event_id]
                ],
            }
        )
        for row in event_rows
    }
    history_by_employee: dict[str, list[ActivityRecord]] = defaultdict(list)
    for row in history_rows:
        history_by_employee[row.employee_id].append(
            ActivityRecord.model_validate(row, from_attributes=True)
        )

    readiness_values: list[float] = []
    department_readiness: dict[str, list[float]] = defaultdict(list)
    department_counts: dict[str, int] = defaultdict(int)
    gap_totals: dict[str, list[int]] = defaultdict(list)
    promotion_ready_count = 0

    for employee in employees:
        department_counts[employee.department] += 1
        target_grade = next_grade(employee.grade)
        if target_grade is None:
            continue
        rows = requirements_by_role_grade[(employee.role, target_grade)]
        requirements = RoleRequirements.model_validate(
            {
                "role": employee.role,
                "grade": target_grade,
                "required_skills": {
                    row.skill_id: row.required_level for row in rows
                },
                "critical_skills": sorted(
                    row.skill_id for row in rows if row.is_critical
                ),
            }
        )
        profile = DevelopmentProfile.model_validate(
            {
                "employee_id": employee.employee_id,
                "role": employee.role,
                "grade": employee.grade,
                "work_format": employee.work_format,
                "skills": skills_by_employee[employee.employee_id],
                "last_review_date": employee.last_review_date,
            }
        )
        current_skills = effective_skills(
            profile,
            events,
            history_by_employee[employee.employee_id],
            as_of_date=snapshot_date,
        )
        trajectory = calculate_trajectory(
            profile.model_copy(update={"skills": current_skills}),
            [requirements],
        )
        if trajectory.readiness is None:
            continue
        readiness_values.append(trajectory.readiness)
        department_readiness[employee.department].append(trajectory.readiness)
        if trajectory.promotion_ready:
            promotion_ready_count += 1
        for gap in trajectory.gaps:
            gap_totals[gap.skill_id].append(gap.gap)

    skill_names = {row.skill_id: row.name for row in skill_rows}
    if missing := gap_totals.keys() - skill_names.keys():
        raise ValueError(f"Missing names for skills: {sorted(missing)}")
    departments = [
        DepartmentOverview(
            department=department,
            employee_count=count,
            employees_with_trajectory=len(department_readiness[department]),
            average_readiness=_average(department_readiness[department]),
        )
        for department, count in sorted(department_counts.items())
    ]
    skill_gaps = [
        SkillGapOverview(
            skill_id=skill_id,
            name=skill_names[skill_id],
            employees_with_gap=len(gaps),
            average_gap=round(fmean(gaps), 2),
        )
        for skill_id, gaps in sorted(gap_totals.items())
    ]
    return HROverviewOut(
        as_of_date=snapshot_date,
        employee_count=len(employees),
        department_count=len(departments),
        employees_with_trajectory=len(readiness_values),
        promotion_ready_count=promotion_ready_count,
        average_readiness=_average(readiness_values),
        departments=departments,
        skill_gaps=skill_gaps,
    )


async def _read_upload(upload: UploadFile) -> bytes:
    content = await upload.read()
    if not content:
        raise HTTPException(status_code=422, detail=f"{upload.filename}: файл пуст")
    return content


def create_router(*, recommendation_cache: RecommendationCache) -> APIRouter:
    router = APIRouter(prefix="/api/hr", tags=["hr"])

    @router.get("/overview", response_model=HROverviewOut)
    async def overview(
        _principal: HRPrincipalDep, session: SessionDep
    ) -> HROverviewOut:
        return await build_overview(session)

    @router.post("/dataset", response_model=DatasetUploadOut)
    async def upload_dataset(
        _principal: HRPrincipalDep,
        session: SessionDep,
        employees: Annotated[UploadFile, File()],
        events: Annotated[UploadFile, File()],
        skills: Annotated[UploadFile, File()],
        activity_history: Annotated[UploadFile, File()],
    ) -> DatasetUploadOut:
        try:
            bundle = DatasetBundle(
                employees=parse_employees_json(
                    await _read_upload(employees), employees.filename or "employees.json"
                ),
                events=parse_events_json(
                    await _read_upload(events), events.filename or "events.json"
                ),
                skills=parse_skills_json(
                    await _read_upload(skills), skills.filename or "skills.json"
                ),
                history=parse_history_csv(
                    await _read_upload(activity_history),
                    activity_history.filename or "activity_history.csv",
                ),
            )
            validate_dataset(bundle)
        except IngestValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        counts: IngestCounts = await ingest_dataset(session, bundle)
        await session.commit()
        recommendation_cache.clear()
        return DatasetUploadOut(
            status="loaded",
            dataset=bundle.employees.meta.dataset,
            version=bundle.employees.meta.version,
            as_of_date=bundle.employees.meta.as_of_date,
            counts=DatasetCountsOut(**asdict(counts)),
        )

    @router.get("/agent-runs", response_model=AgentRunListOut)
    async def agent_runs(
        _principal: HRPrincipalDep,
        session: SessionDep,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AgentRunListOut:
        total = await session.scalar(select(func.count()).select_from(AgentRun))
        rows = (
            await session.scalars(
                select(AgentRun)
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return AgentRunListOut(
            total=total or 0,
            items=[
                AgentRunOut.model_validate(row, from_attributes=True) for row in rows
            ],
        )

    return router
