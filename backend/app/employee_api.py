"""Employee-facing endpoints; identity always comes from the signed session."""

from datetime import date
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, TypeAdapter, model_validator
from sqlalchemy import select

from app.agent import RecommendationAgent
from app.auth import (
    SESSION_COOKIE,
    EmployeePrincipalDep,
    PrincipalDep,
    Role,
    SessionPrincipal,
    signer,
)
from app.config import settings
from app.db import SessionDep
from app.models import ActivityHistory, Dismissal, Employee, Event
from app.progress import ActivityStatus, SkillChange
from app.recommendation_data import (
    EmployeeNotFoundError,
    load_snapshot,
    prepare_context,
)
from app.recommendation_service import (
    RecommendationCache,
    RecommendationRun,
    recommend,
)
from app.scoring import Candidate
from app.trajectory import Trajectory

activity_status_adapter = TypeAdapter(ActivityStatus)


class SessionIn(BaseModel):
    role: Role
    employee_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_identity(self) -> "SessionIn":
        if (self.role == "employee") != (self.employee_id is not None):
            raise ValueError("employee_id is required only for an employee session")
        return self


class SessionOut(BaseModel):
    role: Role
    employee_id: str | None


class EmployeeListItem(BaseModel):
    employee_id: str
    full_name: str
    role: str
    grade: str


class SkillOut(BaseModel):
    skill_id: str
    name: str
    level: int = Field(ge=0, le=5)


class HistoryOut(BaseModel):
    record_id: str
    event_id: str
    title: str
    date: date
    status: ActivityStatus
    completion_pct: int = Field(ge=0, le=100)


class EmployeeProfileOut(BaseModel):
    employee_id: str
    full_name: str
    department: str
    role: str
    grade: str
    tenure_months: int
    work_format: str
    preferred_language: str
    career_goal: dict[str, str] | None
    as_of_date: date
    skills: list[SkillOut]
    trajectory: Trajectory
    history: list[HistoryOut]


class RecommendationIn(BaseModel):
    message: str = Field(
        default="Подбери следующие шаги развития",
        min_length=1,
        max_length=4000,
    )


class ProgressOut(BaseModel):
    readiness_before: float | None
    readiness_after: float | None
    changes: list[SkillChange]


class CompletionOut(BaseModel):
    record_id: str
    event_id: str
    progress: ProgressOut


class DismissOut(BaseModel):
    event_id: str
    status: Literal["dismissed"]


def _employee_id(principal: SessionPrincipal) -> str:
    if principal.employee_id is None:
        raise RuntimeError("Employee dependency returned no employee_id")
    return principal.employee_id


async def _candidate(session: SessionDep, employee_id: str, event_id: str) -> Candidate:
    try:
        context = prepare_context(await load_snapshot(session, employee_id))
    except EmployeeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Сотрудник не найден") from exc
    candidate = next(
        (item for item in context.candidates if item.event_id == event_id),
        None,
    )
    if candidate is None:
        raise HTTPException(
            status_code=409,
            detail="Мероприятие недоступно или больше не подходит",
        )
    return candidate


def create_router(
    *,
    recommendation_cache: RecommendationCache,
    recommendation_agent: RecommendationAgent,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/session", response_model=SessionOut)
    async def create_session(
        payload: SessionIn, response: Response, session: SessionDep
    ) -> SessionOut:
        if (
            payload.employee_id is not None
            and await session.get(Employee, payload.employee_id) is None
        ):
            raise HTTPException(status_code=404, detail="Сотрудник не найден")
        principal = SessionPrincipal(
            role=payload.role,
            employee_id=payload.employee_id,
        )
        response.set_cookie(
            SESSION_COOKIE,
            signer.issue(principal),
            max_age=settings.session_max_age_seconds,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite="lax",
            path="/",
        )
        return SessionOut(**principal.model_dump())

    @router.get("/session", response_model=SessionOut)
    async def get_session(principal: PrincipalDep) -> SessionOut:
        return SessionOut(**principal.model_dump())

    @router.delete("/session", response_model=SessionOut)
    async def delete_session(response: Response, principal: PrincipalDep) -> SessionOut:
        response.delete_cookie(SESSION_COOKIE, path="/")
        return SessionOut(**principal.model_dump())

    @router.get("/employees", response_model=list[EmployeeListItem])
    async def list_employees(session: SessionDep) -> list[EmployeeListItem]:
        rows = (
            await session.scalars(select(Employee).order_by(Employee.full_name))
        ).all()
        return [
            EmployeeListItem.model_validate(row, from_attributes=True) for row in rows
        ]

    @router.get("/employee/profile", response_model=EmployeeProfileOut)
    async def employee_profile(
        principal: EmployeePrincipalDep, session: SessionDep
    ) -> EmployeeProfileOut:
        employee_id = _employee_id(principal)
        employee = await session.get(Employee, employee_id)
        if employee is None:
            raise HTTPException(status_code=404, detail="Сотрудник не найден")
        context = prepare_context(await load_snapshot(session, employee_id))
        events = {event.event_id: event for event in context.snapshot.events}
        history_rows = (
            await session.scalars(
                select(ActivityHistory)
                .where(ActivityHistory.employee_id == employee_id)
                .order_by(ActivityHistory.date.desc(), ActivityHistory.record_id.desc())
            )
        ).all()
        return EmployeeProfileOut(
            employee_id=employee.employee_id,
            full_name=employee.full_name,
            department=employee.department,
            role=employee.role,
            grade=employee.grade,
            tenure_months=employee.tenure_months,
            work_format=employee.work_format,
            preferred_language=employee.preferred_language,
            career_goal=employee.career_goal,
            as_of_date=context.snapshot.as_of_date,
            skills=[
                SkillOut(
                    skill_id=skill_id,
                    name=context.snapshot.skill_names[skill_id],
                    level=level,
                )
                for skill_id, level in sorted(context.profile.skills.items())
            ],
            trajectory=context.trajectory,
            history=[
                HistoryOut(
                    record_id=row.record_id,
                    event_id=row.event_id,
                    title=events[row.event_id].title,
                    date=row.date,
                    status=activity_status_adapter.validate_python(row.status),
                    completion_pct=row.completion_pct,
                )
                for row in history_rows
            ],
        )

    @router.post("/employee/recommendations", response_model=RecommendationRun)
    async def employee_recommendations(
        payload: RecommendationIn,
        principal: EmployeePrincipalDep,
        session: SessionDep,
    ) -> RecommendationRun:
        try:
            return await recommend(
                session,
                employee_id=_employee_id(principal),
                message=payload.message,
                agent=recommendation_agent,
                cache=recommendation_cache,
            )
        except EmployeeNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Сотрудник не найден") from exc

    @router.post(
        "/employee/events/{event_id}/complete",
        response_model=CompletionOut,
    )
    async def complete_event(
        event_id: str,
        principal: EmployeePrincipalDep,
        session: SessionDep,
    ) -> CompletionOut:
        employee_id = _employee_id(principal)
        candidate = await _candidate(session, employee_id, event_id)
        snapshot = await load_snapshot(session, employee_id)
        record_id = f"UI_{uuid4().hex}"
        session.add(
            ActivityHistory(
                record_id=record_id,
                employee_id=employee_id,
                event_id=event_id,
                date=snapshot.as_of_date,
                due_date=None,
                status="completed",
                completion_pct=100,
                score=None,
                feedback_rating=None,
                assigned_by="self",
            )
        )
        await session.commit()
        recommendation_cache.invalidate_employee(employee_id)
        return CompletionOut(
            record_id=record_id,
            event_id=event_id,
            progress=ProgressOut(
                readiness_before=candidate.readiness_before,
                readiness_after=candidate.readiness_after,
                changes=candidate.changes,
            ),
        )

    @router.post(
        "/employee/events/{event_id}/dismiss",
        response_model=DismissOut,
    )
    async def dismiss_event(
        event_id: str,
        principal: EmployeePrincipalDep,
        session: SessionDep,
    ) -> DismissOut:
        employee_id = _employee_id(principal)
        await _candidate(session, employee_id, event_id)
        event = await session.get(Event, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Мероприятие не найдено")
        session.add(Dismissal(employee_id=employee_id, event_id=event_id))
        await session.commit()
        recommendation_cache.invalidate_employee(employee_id)
        return DismissOut(event_id=event_id, status="dismissed")

    return router
