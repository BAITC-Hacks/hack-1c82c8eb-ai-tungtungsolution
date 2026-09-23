from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest import IngestCounts
from app.recommendation_service import RecommendationCache


def _rows(values: list[object]) -> MagicMock:
    return MagicMock(all=MagicMock(return_value=values))


def _cookie(token: str) -> dict[str, str]:
    from app.auth import SESSION_COOKIE

    return {"Cookie": f"{SESSION_COOKIE}={token}"}


@pytest.fixture
def hr_app(
    configured_backend: None,
) -> tuple[FastAPI, MagicMock, RecommendationCache]:
    from app import hr_api
    from app.auth import SessionPrincipal, signer
    from app.db import get_session

    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.scalar = AsyncMock(return_value=0)
    session.scalars = AsyncMock(return_value=_rows([]))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, session)

    cache = RecommendationCache(ttl_seconds=60, max_entries=8)
    app = FastAPI()
    app.include_router(hr_api.create_router(recommendation_cache=cache))
    app.dependency_overrides[get_session] = session_override
    app.state.hr_token = signer.issue(SessionPrincipal(role="hr"))
    app.state.employee_token = signer.issue(
        SessionPrincipal(role="employee", employee_id="EMP_001")
    )
    return app, session, cache


@pytest.mark.anyio
async def test_hr_overview_is_aggregate_and_role_guarded(
    hr_app: tuple[FastAPI, MagicMock, RecommendationCache],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import hr_api

    app, _session, _cache = hr_app
    overview = hr_api.HROverviewOut(
        as_of_date=date(2026, 10, 1),
        employee_count=2,
        department_count=1,
        employees_with_trajectory=1,
        promotion_ready_count=0,
        average_readiness=50,
        departments=[
            hr_api.DepartmentOverview(
                department="Engineering",
                employee_count=2,
                employees_with_trajectory=1,
                average_readiness=50,
            )
        ],
        skill_gaps=[
            hr_api.SkillGapOverview(
                skill_id="SK_001",
                name="System Design",
                employees_with_gap=1,
                average_gap=2,
            )
        ],
    )
    monkeypatch.setattr(hr_api, "build_overview", AsyncMock(return_value=overview))
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app), base_url="http://test"
    ) as client:
        anonymous = await client.get("/api/hr/overview")
        employee = await client.get(
            "/api/hr/overview", headers=_cookie(app.state.employee_token)
        )
        response = await client.get(
            "/api/hr/overview", headers=_cookie(app.state.hr_token)
        )
    assert anonymous.status_code == 401
    assert employee.status_code == 403
    assert response.status_code == 200
    serialized = response.text
    assert "employee_id" not in serialized
    assert "full_name" not in serialized


@pytest.mark.anyio
async def test_overview_calculates_effective_aggregate_without_employee_ranking(
    configured_backend: None,
) -> None:
    from app.hr_api import build_overview
    from app.models import (
        DatasetMetadata,
        Employee,
        EmployeeSkill,
        GradeRequirement,
        Skill,
    )

    snapshot = date(2026, 10, 1)
    metadata = [
        DatasetMetadata(
            source_filename=filename,
            dataset="test",
            version="1",
            as_of_date=snapshot,
        )
        for filename in ("employees.json", "events.json", "skills.json")
    ]
    employees = [
        Employee(
            employee_id="EMP_MIDDLE",
            department="Engineering",
            role="Backend Engineer",
            grade="Middle",
            work_format="hybrid",
            last_review_date=date(2026, 9, 1),
        ),
        Employee(
            employee_id="EMP_LEAD",
            department="Engineering",
            role="Backend Engineer",
            grade="Lead",
            work_format="remote",
            last_review_date=date(2026, 9, 1),
        ),
    ]
    levels = [
        EmployeeSkill(employee_id="EMP_MIDDLE", skill_id="SK_001", level=2),
        EmployeeSkill(employee_id="EMP_LEAD", skill_id="SK_001", level=5),
    ]
    requirements = [
        GradeRequirement(
            role="Backend Engineer",
            grade="Senior",
            skill_id="SK_001",
            required_level=4,
            is_critical=True,
        )
    ]
    session = MagicMock(spec=AsyncSession)
    session.scalars = AsyncMock(
        side_effect=[
            _rows(cast(list[object], metadata)),
            _rows(cast(list[object], employees)),
            _rows(cast(list[object], levels)),
            _rows(cast(list[object], requirements)),
            _rows([]),
            _rows([]),
            _rows([]),
            _rows([Skill(skill_id="SK_001", name="System Design")]),
        ]
    )
    result = await build_overview(cast(AsyncSession, session))
    assert result.employee_count == 2
    assert result.employees_with_trajectory == 1
    assert result.average_readiness == 50
    assert result.skill_gaps[0].employees_with_gap == 1
    assert result.skill_gaps[0].average_gap == 2
    assert "EMP_MIDDLE" not in result.model_dump_json()


@pytest.mark.anyio
async def test_hr_can_upload_validated_dataset_and_cache_is_cleared(
    hr_app: tuple[FastAPI, MagicMock, RecommendationCache],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import hr_api

    app, session, cache = hr_app
    ingest = AsyncMock(
        return_value=IngestCounts(
            metadata=3,
            employees=200,
            employee_skills=1200,
            skills=60,
            role_profiles=40,
            grade_requirements=240,
            events=40,
            event_skills=80,
            activity_history=2743,
        )
    )
    monkeypatch.setattr(hr_api, "ingest_dataset", ingest)
    cleared = MagicMock(wraps=cache.clear)
    monkeypatch.setattr(cache, "clear", cleared)
    data_dir = Path(__file__).resolve().parents[1] / "data"
    files = {
        "employees": (
            "employees.json",
            (data_dir / "employees.json").read_bytes(),
            "application/json",
        ),
        "events": (
            "events.json",
            (data_dir / "events.json").read_bytes(),
            "application/json",
        ),
        "skills": (
            "skills.json",
            (data_dir / "skills.json").read_bytes(),
            "application/json",
        ),
        "activity_history": (
            "activity_history.csv",
            (data_dir / "activity_history.csv").read_bytes(),
            "text/csv",
        ),
    }
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/hr/dataset",
            files=files,
            headers=_cookie(app.state.hr_token),
        )
    assert response.status_code == 200
    assert response.json()["counts"]["employees"] == 200
    ingest.assert_awaited_once()
    session.commit.assert_awaited_once()
    cleared.assert_called_once()


@pytest.mark.anyio
async def test_invalid_dataset_is_rejected_before_database_write(
    hr_app: tuple[FastAPI, MagicMock, RecommendationCache],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import hr_api

    app, session, _cache = hr_app
    ingest = AsyncMock()
    monkeypatch.setattr(hr_api, "ingest_dataset", ingest)
    files = {
        "employees": ("employees.json", b"{}", "application/json"),
        "events": ("events.json", b"{}", "application/json"),
        "skills": ("skills.json", b"{}", "application/json"),
        "activity_history": ("activity_history.csv", b"bad", "text/csv"),
    }
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/hr/dataset",
            files=files,
            headers=_cookie(app.state.hr_token),
        )
    assert response.status_code == 422
    ingest.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_hr_agent_run_log_is_paginated(
    hr_app: tuple[FastAPI, MagicMock, RecommendationCache],
) -> None:
    from app.models import AgentRun

    app, session, _cache = hr_app
    row = AgentRun(
        id=7,
        employee_id="EMP_001",
        kind="recommendation",
        user_input="Что развивать?",
        answer="Рекомендация",
        steps=[{"tool": "get_profile", "arguments": {}, "result": {}}],
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        latency_ms=12,
        fallback_used=False,
    )
    session.scalar.return_value = 1
    session.scalars.return_value = _rows([row])
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/hr/agent-runs?limit=10&offset=0",
            headers=_cookie(app.state.hr_token),
        )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == 7
