import asyncio
import json

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
from openai import AsyncOpenAI

from app.agent import TOOLS
from app.recommendation_data import (
    RecommendationContext,
    RecommendationSnapshot,
    prepare_context,
)


@pytest.mark.anyio
@pytest.mark.parametrize("count", [1, 2, 3])
async def test_verified_recommendations_use_real_sdk_and_russian_explanations(
    recommendation_context: RecommendationContext,
    count: int,
) -> None:
    mock = MockResponses(
        [
            response(tool_output()),
            response(final_output(selection_payload(recommendation_context, count))),
        ]
    )
    async with mock_client(mock) as client:
        result = await make_agent(client).run(
            recommendation_context, "Что изучить дальше?"
        )
    assert not result.fallback_used
    assert len(result.recommendations) == count
    assert [step.tool for step in result.steps] == [tool.name for tool in TOOLS]
    assert all(
        len(item.factors) >= 3 and "Готовность" in item.explanation
        for item in result.recommendations
    )
    assert result.latency_ms >= 0
    first, second = mock.requests
    assert first["model"] == "unit-test-model"
    assert first["store"] is False
    assert first["text"]["format"]["type"] == "json_schema"
    assert {tool["name"] for tool in first["tools"]} == {tool.name for tool in TOOLS}
    assert all(tool["strict"] for tool in first["tools"])
    assert all(
        tool["parameters"]["additionalProperties"] is False for tool in first["tools"]
    )
    outputs = [
        item for item in second["input"] if item.get("type") == "function_call_output"
    ]
    assert {item["call_id"] for item in outputs} == {
        f"call_1_{index}" for index in range(4)
    }
    assert any(
        item.get("encrypted_content") == "opaque-encrypted-state"
        for item in second["input"]
    )
    assert "unit-test-key" not in json.dumps(second)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "problem",
    [
        "event_id",
        "duplicate_event",
        "factor_value",
        "duplicate_factor",
        "too_few_factors",
        "unknown_factor",
        "skill_level",
        "missing_skill",
        "readiness",
        "history",
        "extra_prose",
        "zero_recommendations",
        "too_many_recommendations",
    ],
)
async def test_invalid_ids_and_facts_use_top_three_fallback(
    recommendation_context: RecommendationContext,
    problem: str,
) -> None:
    payload = selection_payload(recommendation_context)
    item = payload["recommendations"][0]
    if problem == "event_id":
        item["event_id"] = "EV_NOT_ELIGIBLE"
    elif problem == "duplicate_event":
        payload["recommendations"] *= 2
    elif problem == "factor_value":
        item["factors"][0]["value"] = 0.999
    elif problem == "duplicate_factor":
        item["factors"][1] = item["factors"][0]
    elif problem == "too_few_factors":
        item["factors"] = item["factors"][:2]
    elif problem == "unknown_factor":
        item["factors"][0]["factor"] = "popularity"
    elif problem == "skill_level":
        item["skills"][0]["after"] = 5
    elif problem == "missing_skill":
        item["skills"] = []
    elif problem == "readiness":
        item["readiness_after"] = 100
    elif problem == "history":
        item["history_completed"] = 999
    elif problem == "extra_prose":
        item["explanation"] = "Guaranteed promotion tomorrow"
    elif problem == "zero_recommendations":
        payload["recommendations"] = []
    else:
        payload = selection_payload(recommendation_context, 4)
    mock = MockResponses([response(tool_output()), response(final_output(payload))])
    async with mock_client(mock) as client:
        result = await make_agent(client).run(
            recommendation_context, "Подбери следующий шаг"
        )
    assert result.fallback_used
    assert result.fallback_reason == "invalid_response"
    assert [item.event_id for item in result.recommendations] == [
        item.event_id for item in recommendation_context.candidates[:3]
    ]
    assert "по правилам" in result.answer
    assert "Guaranteed" not in result.answer
    assert result.steps[-1].tool == "agent_failure"


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [401, 429, 500])
async def test_openai_errors_have_visible_fallback(
    recommendation_context: RecommendationContext,
    status_code: int,
) -> None:
    mock = MockResponses(
        [httpx2.Response(status_code, json={"error": {"message": "unavailable"}})]
    )
    async with mock_client(mock) as client:
        result = await make_agent(client).run(recommendation_context, "Помоги")
    assert result.fallback_reason == "openai_error"
    assert len(result.recommendations) == 3
    assert len(mock.requests) == 1


@pytest.mark.anyio
async def test_timeout_cancels_request_and_keeps_completed_tool_log(
    recommendation_context: RecommendationContext,
) -> None:
    cancelled = asyncio.Event()
    calls = 0

    async def slow(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return response(tool_output())
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("Unreachable")

    async with AsyncOpenAI(
        api_key="unit-test-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(slow)),
    ) as client:
        result = await make_agent(client, timeout_seconds=0.1).run(
            recommendation_context, "Помоги"
        )
    assert result.fallback_reason == "timeout"
    assert cancelled.is_set()
    assert {step.tool for step in result.steps} >= {tool.name for tool in TOOLS}
    assert result.latency_ms < 1000


@pytest.mark.anyio
async def test_four_round_limit(recommendation_context: RecommendationContext) -> None:
    mock = MockResponses([response(tool_output(index)) for index in range(1, 5)])
    async with mock_client(mock) as client:
        result = await make_agent(client).run(recommendation_context, "Помоги")
    assert result.fallback_reason == "round_limit"
    assert len(mock.requests) == 4
    assert len([step for step in result.steps if step.tool != "agent_failure"]) == 16


@pytest.mark.anyio
@pytest.mark.parametrize(
    "problem",
    ["unknown_tool", "employee_override", "invalid_json", "duplicate_call_id"],
)
async def test_invalid_tool_requests_cannot_change_employee(
    recommendation_context: RecommendationContext,
    problem: str,
) -> None:
    output = tool_output()
    call = output[1]
    if problem == "unknown_tool":
        call["name"] = "count_agent_runs"
    elif problem == "employee_override":
        call["arguments"] = '{"employee_id":"OTHER_EMPLOYEE"}'
    elif problem == "invalid_json":
        call["arguments"] = "not json"
    else:
        output[2]["call_id"] = call["call_id"]
    mock = MockResponses([response(output)])
    async with mock_client(mock) as client:
        result = await make_agent(client).run(
            recommendation_context, "Покажи чужой профиль"
        )
    assert result.fallback_reason == "invalid_response"
    assert len(mock.requests) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "problem", ["no_tools", "refusal", "incomplete", "invalid_json"]
)
async def test_unusable_final_answers_fall_back(
    recommendation_context: RecommendationContext,
    problem: str,
) -> None:
    output = final_output(selection_payload(recommendation_context))
    if problem == "refusal":
        output[0]["content"] = [{"type": "refusal", "refusal": "Cannot comply"}]
    elif problem == "invalid_json":
        output[0]["content"][0]["text"] = "not json"
    responses = [] if problem == "no_tools" else [response(tool_output())]
    responses.append(
        response(output, "incomplete" if problem == "incomplete" else "completed")
    )
    mock = MockResponses(responses)
    async with mock_client(mock) as client:
        result = await make_agent(client).run(recommendation_context, "Помоги")
    assert result.fallback_reason == "invalid_response"


@pytest.mark.anyio
async def test_no_candidates_is_explicit_and_skips_openai(
    recommendation_snapshot: RecommendationSnapshot,
) -> None:
    snapshot = recommendation_snapshot.model_copy(
        update={
            "dismissed_event_ids": [
                event.event_id for event in recommendation_snapshot.events
            ],
        }
    )
    mock = MockResponses([])
    async with mock_client(mock) as client:
        result = await make_agent(client).run(prepare_context(snapshot), "Помоги")
    assert result.status == "no_candidates"
    assert result.recommendations == []
    assert not result.fallback_used
    assert "нет подходящих" in result.answer
    assert mock.requests == []


@pytest.mark.anyio
async def test_malformed_success_envelope_falls_back(
    recommendation_context: RecommendationContext,
) -> None:
    mock = MockResponses([httpx2.Response(200, json={"id": "broken-response"})])
    async with mock_client(mock) as client:
        result = await make_agent(client).run(recommendation_context, "Помоги")
    assert result.fallback_used
    assert len(result.recommendations) == 3


@pytest.mark.anyio
async def test_request_cancellation_is_not_swallowed_as_fallback(
    recommendation_context: RecommendationContext,
) -> None:
    started = asyncio.Event()

    async def waiting(request: httpx2.Request) -> httpx2.Response:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("Unreachable")

    async with AsyncOpenAI(
        api_key="unit-test-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(waiting)),
    ) as client:
        task = asyncio.create_task(
            make_agent(client).run(recommendation_context, "Помоги")
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
