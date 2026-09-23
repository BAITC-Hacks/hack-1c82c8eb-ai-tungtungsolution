"""Mock the HTTP boundary while exercising the installed Responses SDK parser."""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx2
from openai import AsyncOpenAI

from app.agent import FACTOR_NAMES, TOOLS, RecommendationAgent
from app.recommendation_data import RecommendationContext


def selection_payload(context: RecommendationContext, count: int = 1) -> dict[str, Any]:
    return {
        "recommendations": [
            {
                "event_id": item.event_id,
                "factors": [
                    {"factor": name, "value": getattr(item.factors, name)}
                    for name in FACTOR_NAMES
                ],
                "skills": [
                    {
                        "skill_id": change.skill_id,
                        "before": change.before,
                        "after": change.after,
                    }
                    for change in item.changes
                ],
                "readiness_before": item.readiness_before,
                "readiness_after": item.readiness_after,
                "history_completed": item.history.completed,
                "history_unsuccessful": item.history.unsuccessful,
            }
            for item in context.candidates[:count]
        ]
    }


def tool_output(round_number: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "type": "reasoning",
            "id": f"reasoning_{round_number}",
            "summary": [],
            "encrypted_content": "opaque-encrypted-state",
        },
        *[
            {
                "type": "function_call",
                "id": f"fc_{round_number}_{index}",
                "call_id": f"call_{round_number}_{index}",
                "name": tool.name,
                "arguments": "{}",
            }
            for index, tool in enumerate(TOOLS)
        ],
    ]


def final_output(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "message",
            "id": "message_1",
            "status": "completed",
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": json.dumps(payload), "annotations": []}
            ],
        }
    ]


def response(
    output: list[dict[str, Any]], status: str = "completed"
) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "response_1",
            "created_at": 0,
            "model": "unit-test-model",
            "object": "response",
            "status": status,
            "output": output,
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
        },
    )


@dataclass
class MockResponses:
    responses: list[httpx2.Response]
    requests: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        if not self.responses:
            raise AssertionError("Unexpected extra OpenAI request")
        return self.responses.pop(0)


def mock_client(mock: MockResponses) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key="unit-test-key",
        max_retries=0,
        _strict_response_validation=True,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(mock)),
    )


def make_agent(client: AsyncOpenAI, timeout_seconds: float = 10) -> RecommendationAgent:
    return RecommendationAgent(
        client=client,
        model="unit-test-model",
        timeout_seconds=timeout_seconds,
        max_rounds=4,
    )
