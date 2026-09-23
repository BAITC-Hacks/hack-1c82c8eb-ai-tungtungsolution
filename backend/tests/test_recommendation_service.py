from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from agent_helpers import (
    MockResponses,
    final_output,
    make_agent,
    mock_client,
    response,
    selection_payload,
    tool_output,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import recommendation_service as service
from app.agent import AgentResult
from app.progress import ActivityRecord
from app.recommendation_data import (
    RecommendationContext,
    RecommendationSnapshot,
    prepare_context,
)

if TYPE_CHECKING:
    from app.models import AgentRun


@pytest.fixture
def audit_session(configured_backend: None) -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    next_id = 0

    async def refresh(row: AgentRun) -> None:
        nonlocal next_id
        next_id += 1
        row.id = next_id
        row.created_at = datetime(2026, 10, 1, tzinfo=UTC)

    session.refresh = AsyncMock(side_effect=refresh)
    return session


@pytest.mark.anyio
async def test_audit_cache_hit_and_completed_dismissed_uploaded_state_changes(
    monkeypatch: pytest.MonkeyPatch,
    audit_session: MagicMock,
    recommendation_snapshot: RecommendationSnapshot,
    recommendation_context: RecommendationContext,
) -> None:
    loader = AsyncMock(return_value=recommendation_snapshot)
    monkeypatch.setattr(service, "load_snapshot", loader)
    mock = MockResponses(
        [
            response(tool_output()),
            response(final_output(selection_payload(recommendation_context))),
        ]
    )
    cache = service.RecommendationCache(ttl_seconds=60, max_entries=10)
    session = cast(AsyncSession, audit_session)
    async with mock_client(mock) as client:
        agent = make_agent(client)
        first = await service.recommend(
            session,
            employee_id=recommendation_snapshot.profile.employee_id,
            message="Помоги",
            agent=agent,
            cache=cache,
        )
        second = await service.recommend(
            session,
            employee_id=recommendation_snapshot.profile.employee_id,
            message="Помоги",
            agent=agent,
            cache=cache,
        )
        assert not first.cache_hit
        assert second.cache_hit
        assert second.id != first.id
        assert second.recommendations == first.recommendations
        assert second.steps[0].result["source_run_id"] == first.id
        assert len(mock.requests) == 2
        original = recommendation_snapshot
        completed = original.model_copy(
            update={
                "history": [
                    ActivityRecord(
                        record_id="DONE",
                        employee_id=original.profile.employee_id,
                        event_id=first.recommendations[0].event_id,
                        date=date(2026, 10, 1),
                        status="completed",
                    )
                ]
            }
        )
        dismissed = original.model_copy(
            update={
                "dismissed_event_ids": [first.recommendations[0].event_id],
            }
        )
        # A jury upload can change data while retaining the same dataset version.
        uploaded = original.model_copy(
            update={
                "profile": original.profile.model_copy(
                    update={
                        "skills": {**original.profile.skills, "SK_SYSTEM_DESIGN": 3},
                    }
                )
            }
        )
        for changed in (completed, dismissed, uploaded):
            loader.return_value = changed
            context = prepare_context(changed)
            mock.responses.extend(
                [
                    response(tool_output()),
                    response(final_output(selection_payload(context))),
                ]
            )
            run = await service.recommend(
                session,
                employee_id=changed.profile.employee_id,
                message="Помоги",
                agent=agent,
                cache=cache,
            )
            assert not run.cache_hit
            assert not run.fallback_used
            if changed is completed or changed is dismissed:
                assert first.recommendations[0].event_id not in [
                    item.event_id for item in run.recommendations
                ]
        assert len(mock.requests) == 8
    assert audit_session.commit.await_count == 5
    for call in audit_session.add.call_args_list:
        row = call.args[0]
        assert row.kind == "recommendation"
        assert row.employee_id == recommendation_snapshot.profile.employee_id
        assert row.latency_ms >= 0
        assert row.answer
        assert row.steps[-1]["tool"] == "recommendation_result"
        assert row.steps[-1]["result"]["recommendations"]


@pytest.mark.anyio
async def test_fallback_is_audited_but_not_cached(
    monkeypatch: pytest.MonkeyPatch,
    audit_session: MagicMock,
    recommendation_snapshot: RecommendationSnapshot,
) -> None:
    monkeypatch.setattr(
        service, "load_snapshot", AsyncMock(return_value=recommendation_snapshot)
    )
    mock = MockResponses(
        [httpx2.Response(500, json={"error": {"message": "offline"}}) for _ in range(2)]
    )
    cache = service.RecommendationCache(ttl_seconds=60, max_entries=10)
    async with mock_client(mock) as client:
        for _ in range(2):
            result = await service.recommend(
                cast(AsyncSession, audit_session),
                employee_id=recommendation_snapshot.profile.employee_id,
                message="Помоги",
                agent=make_agent(client),
                cache=cache,
            )
            assert result.fallback_used
            assert not result.cache_hit
    assert len(mock.requests) == 2
    assert all(call.args[0].fallback_used for call in audit_session.add.call_args_list)


@pytest.mark.anyio
async def test_database_failure_is_not_a_fallback_or_cached_success(
    monkeypatch: pytest.MonkeyPatch,
    audit_session: MagicMock,
    recommendation_snapshot: RecommendationSnapshot,
    recommendation_context: RecommendationContext,
) -> None:
    loader = AsyncMock(return_value=recommendation_snapshot)
    monkeypatch.setattr(service, "load_snapshot", loader)
    mock = MockResponses(
        [
            response(tool_output()),
            response(final_output(selection_payload(recommendation_context))),
        ]
    )
    cache = service.RecommendationCache(ttl_seconds=60, max_entries=10)
    async with mock_client(mock) as client:
        agent = make_agent(client)
        audit_session.commit.side_effect = SQLAlchemyError("audit failed")
        with pytest.raises(SQLAlchemyError, match="audit failed"):
            await service.recommend(
                cast(AsyncSession, audit_session),
                employee_id=recommendation_snapshot.profile.employee_id,
                message="Помоги",
                agent=agent,
                cache=cache,
            )
        assert (
            cache.get(cache.key(recommendation_snapshot, "Помоги", agent.model)) is None
        )
        loader.side_effect = SQLAlchemyError("read failed")
        with pytest.raises(SQLAlchemyError, match="read failed"):
            await service.recommend(
                cast(AsyncSession, audit_session),
                employee_id=recommendation_snapshot.profile.employee_id,
                message="Помоги",
                agent=agent,
                cache=cache,
            )
        assert len(mock.requests) == 2


def test_cache_expiration_capacity_copying_and_invalidation(
    recommendation_snapshot: RecommendationSnapshot,
) -> None:
    now = [0.0]
    cache = service.RecommendationCache(
        ttl_seconds=10, max_entries=2, clock=lambda: now[0]
    )
    result = AgentResult(
        answer="Нет кандидатов",
        recommendations=[],
        status="no_candidates",
        fallback_used=False,
        fallback_reason=None,
        steps=[],
        latency_ms=0,
    )
    key = cache.key(recommendation_snapshot, "Помоги", "unit-test-model")
    other_employee = recommendation_snapshot.model_copy(
        update={
            "profile": recommendation_snapshot.profile.model_copy(
                update={"employee_id": "OTHER"}
            ),
        }
    )
    other_key = cache.key(other_employee, "Помоги", "unit-test-model")
    model_key = cache.key(recommendation_snapshot, "Помоги", "another-test-model")
    assert len({key, other_key, model_key}) == 3
    cache.put(key, result, source_run_id=1)
    result.answer = "Changed after caching"
    hit = cache.get(key)
    assert hit is not None and hit.result.answer == "Нет кандидатов"
    hit.result.answer = "Changed after reading"
    hit_again = cache.get(key)
    assert hit_again is not None and hit_again.result.answer == "Нет кандидатов"
    cache.put(other_key, result, source_run_id=2)
    cache.put(model_key, result, source_run_id=3)
    assert cache.get(key) is None
    cache.invalidate_employee(recommendation_snapshot.profile.employee_id)
    assert cache.get(model_key) is None
    assert cache.get(other_key) is not None
    now[0] = 10.0
    assert cache.get(other_key) is None
    cache.put(key, result, source_run_id=4)
    cache.clear()
    assert cache.get(key) is None


def test_context_rejects_foreign_employee_history(
    recommendation_snapshot: RecommendationSnapshot,
) -> None:
    row = ActivityRecord(
        record_id="PRIVATE",
        employee_id="OTHER",
        event_id="EV_DESIGN",
        date=date(2026, 9, 10),
        status="completed",
    )
    with pytest.raises(ValueError, match="belong to the selected employee"):
        prepare_context(recommendation_snapshot.model_copy(update={"history": [row]}))


@pytest.mark.anyio
async def test_agent_endpoint_returns_verified_result_and_persists_audit(
    monkeypatch: pytest.MonkeyPatch,
    audit_session: MagicMock,
    recommendation_snapshot: RecommendationSnapshot,
    recommendation_context: RecommendationContext,
) -> None:
    from app import main
    from app.db import get_session

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, audit_session)

    monkeypatch.setattr(
        service, "load_snapshot", AsyncMock(return_value=recommendation_snapshot)
    )
    monkeypatch.setitem(main.app.dependency_overrides, get_session, session_override)
    monkeypatch.setattr(
        main,
        "recommendation_cache",
        service.RecommendationCache(ttl_seconds=60, max_entries=5),
    )
    mock = MockResponses(
        [
            response(tool_output()),
            response(final_output(selection_payload(recommendation_context, 3))),
        ]
    )
    async with mock_client(mock) as client:
        monkeypatch.setattr(main, "recommendation_agent", make_agent(client))
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(main.app),
            base_url="http://test",
        ) as api:
            output = await api.post(
                "/api/agent/run",
                json={
                    "employee_id": recommendation_snapshot.profile.employee_id,
                    "message": "Помоги",
                },
            )
            assert output.status_code == 200
            body = output.json()
            assert body["id"] == 1
            assert not body["fallback_used"]
            assert len(body["recommendations"]) == 3
            assert len(body["steps"]) == 4
            assert "created_at" in body
            invalid = await api.post("/api/agent/run", json={"message": "Помоги"})
            assert invalid.status_code == 422
            from app.recommendation_data import EmployeeNotFoundError

            monkeypatch.setattr(
                service,
                "load_snapshot",
                AsyncMock(side_effect=EmployeeNotFoundError("UNKNOWN")),
            )
            missing = await api.post(
                "/api/agent/run", json={"employee_id": "UNKNOWN", "message": "Помоги"}
            )
            assert missing.status_code == 404
            schema = (await api.get("/openapi.json")).json()
            assert (
                "employee_id"
                in schema["components"]["schemas"]["AgentRunIn"]["required"]
            )
    audit_session.commit.assert_awaited_once()
