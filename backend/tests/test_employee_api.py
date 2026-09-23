from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import AgentResult, RecommendationAgent
from app.recommendation_data import RecommendationSnapshot
from app.recommendation_service import RecommendationCache, RecommendationRun


@pytest.fixture
def employee_app(
    configured_backend: None,
    monkeypatch: pytest.MonkeyPatch,
    recommendation_snapshot: RecommendationSnapshot,
) -> tuple[FastAPI, MagicMock, RecommendationCache]:
    from app import employee_api
    from app.auth import SessionPrincipal, signer
    from app.db import get_session
    from app.models import Employee

    session = MagicMock(spec=AsyncSession)
    employee = Employee(
        employee_id="TRAP_EMPLOYEE",
        full_name="Test Employee",
        department="Backend",
        role="Backend Engineer",
        grade="Middle",
        tenure_months=24,
        work_format="hybrid",
        preferred_language="ru",
        career_goal={"target_role": "Backend Engineer", "target_grade": "Senior"},
        last_review_date=recommendation_snapshot.profile.last_review_date,
    )

    async def get(model: type[object], identity: object) -> object | None:
        if model is Employee and identity == "TRAP_EMPLOYEE":
            return employee
        return None

    session.get = AsyncMock(side_effect=get)
    session.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, session)

    cache = RecommendationCache(ttl_seconds=60, max_entries=8)
    agent = MagicMock(spec=RecommendationAgent)
    app = FastAPI()
    app.include_router(
        employee_api.create_router(
            recommendation_cache=cache,
            recommendation_agent=cast(RecommendationAgent, agent),
        )
    )
    app.dependency_overrides[get_session] = session_override
    app.state.employee_token = signer.issue(
        SessionPrincipal(role="employee", employee_id="TRAP_EMPLOYEE")
    )
    app.state.other_token = signer.issue(
        SessionPrincipal(role="employee", employee_id="OTHER_EMPLOYEE")
    )
    app.state.hr_token = signer.issue(SessionPrincipal(role="hr"))
    monkeypatch.setattr(
        employee_api,
        "load_snapshot",
        AsyncMock(return_value=recommendation_snapshot),
    )
    return app, session, cache


def cookie(token: str) -> dict[str, str]:
    from app.auth import SESSION_COOKIE

    return {"Cookie": f"{SESSION_COOKIE}={token}"}


@pytest.mark.anyio
async def test_create_read_delete_session_and_employee_list(
    employee_app: tuple[FastAPI, MagicMock, RecommendationCache],
) -> None:
    app, session, _cache = employee_app
    from app.auth import SESSION_COOKIE
    from app.models import Employee

    employees = [
        Employee(
            employee_id="TRAP_EMPLOYEE",
            full_name="Test Employee",
            role="Backend Engineer",
            grade="Middle",
        )
    ]
    session.scalars.return_value = MagicMock(all=MagicMock(return_value=employees))
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app), base_url="http://test"
    ) as client:
        listed = await client.get("/api/employees")
        assert listed.status_code == 200
        assert listed.json()[0]["employee_id"] == "TRAP_EMPLOYEE"
        created = await client.post(
            "/api/session",
            json={"role": "employee", "employee_id": "TRAP_EMPLOYEE"},
        )
        assert created.status_code == 200
        assert SESSION_COOKIE in created.cookies
        assert "HttpOnly" in created.headers["set-cookie"]
        current = await client.get("/api/session")
        assert current.json() == {
            "role": "employee",
            "employee_id": "TRAP_EMPLOYEE",
        }
        deleted = await client.delete("/api/session")
        assert deleted.status_code == 200
        assert f'{SESSION_COOKIE}=""' in deleted.headers["set-cookie"]
        tampered = await client.get(
            "/api/session",
            headers={"Cookie": f"{SESSION_COOKIE}=tampered.value"},
        )
        assert tampered.status_code == 401
        invalid_role = await client.post(
            "/api/session",
            json={"role": "hr", "employee_id": "TRAP_EMPLOYEE"},
        )
        assert invalid_role.status_code == 422
        missing = await client.post(
            "/api/session",
            json={"role": "employee", "employee_id": "UNKNOWN"},
        )
        assert missing.status_code == 404


@pytest.mark.anyio
async def test_employee_profile_is_derived_only_from_cookie_identity(
    employee_app: tuple[FastAPI, MagicMock, RecommendationCache],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, session, _cache = employee_app
    from app import employee_api

    loader = cast(AsyncMock, employee_api.load_snapshot)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app), base_url="http://test"
    ) as client:
        own = await client.get(
            "/api/employee/profile?employee_id=OTHER_EMPLOYEE",
            headers=cookie(app.state.employee_token),
        )
        assert own.status_code == 200
        assert own.json()["employee_id"] == "TRAP_EMPLOYEE"
        loader.assert_awaited_once_with(session, "TRAP_EMPLOYEE")
        loader.reset_mock()
        other = await client.get(
            "/api/employee/profile",
            headers=cookie(app.state.other_token),
        )
        assert other.status_code == 404
        assert loader.await_count == 0
        hr = await client.get(
            "/api/employee/profile",
            headers=cookie(app.state.hr_token),
        )
        assert hr.status_code == 403
        anonymous = await client.get("/api/employee/profile")
        assert anonymous.status_code == 401


@pytest.mark.anyio
async def test_recommend_complete_and_dismiss_use_cookie_identity(
    employee_app: tuple[FastAPI, MagicMock, RecommendationCache],
    recommendation_snapshot: RecommendationSnapshot,
    recommendation_context: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, session, cache = employee_app
    from app import employee_api
    from app.models import ActivityHistory, Dismissal, Event
    from app.recommendation_data import RecommendationContext

    context = cast(RecommendationContext, recommendation_context)
    candidate = context.candidates[0]
    run = RecommendationRun(
        **AgentResult(
            answer="Готово",
            recommendations=[],
            status="ready",
            fallback_used=False,
            fallback_reason=None,
            steps=[],
            latency_ms=1,
        ).model_dump(),
        id=1,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    recommend_mock = AsyncMock(return_value=run)
    candidate_mock = AsyncMock(return_value=candidate)
    monkeypatch.setattr(employee_api, "recommend", recommend_mock)
    monkeypatch.setattr(employee_api, "_candidate", candidate_mock)
    original_get = session.get.side_effect

    async def get_with_event(model: type[object], identity: object) -> object | None:
        if model is Event:
            return Event(event_id=cast(str, identity))
        return await original_get(model, identity)

    session.get.side_effect = get_with_event
    invalidated = MagicMock(wraps=cache.invalidate_employee)
    monkeypatch.setattr(cache, "invalidate_employee", invalidated)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app), base_url="http://test"
    ) as client:
        recommended = await client.post(
            "/api/employee/recommendations?employee_id=OTHER_EMPLOYEE",
            json={"message": "Помоги"},
            headers=cookie(app.state.employee_token),
        )
        assert recommended.status_code == 200
        assert recommend_mock.await_args is not None
        assert recommend_mock.await_args.kwargs["employee_id"] == "TRAP_EMPLOYEE"
        completed = await client.post(
            f"/api/employee/events/{candidate.event_id}/complete?employee_id=OTHER_EMPLOYEE",
            headers=cookie(app.state.employee_token),
        )
        assert completed.status_code == 200
        assert completed.json()["progress"]["changes"]
        completion_row = next(
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], ActivityHistory)
        )
        assert completion_row.employee_id == "TRAP_EMPLOYEE"
        assert completion_row.status == "completed"
        dismissed = await client.post(
            f"/api/employee/events/{candidate.event_id}/dismiss",
            headers=cookie(app.state.employee_token),
        )
        assert dismissed.status_code == 200
        dismissal_row = next(
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], Dismissal)
        )
        assert dismissal_row.employee_id == "TRAP_EMPLOYEE"
        assert invalidated.call_count == 2
        assert session.commit.await_count == 2
        assert all(
            call.args[1] == "TRAP_EMPLOYEE" for call in candidate_mock.await_args_list
        )
