import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from openai import pydantic_function_tool
from openai.types.responses import ResponseFunctionToolCall
from openai.types.responses.response_input_param import ResponseInputParam
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm import client
from app.models import AgentRun

type ToolHandler = Callable[
    [AsyncSession, BaseModel], Awaitable[dict[str, object]]
]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler


class AgentStep(BaseModel):
    tool: str
    arguments: dict[str, object]
    result: dict[str, object]


class AgentAnswer(BaseModel):
    answer: str


class AgentStepLimitError(RuntimeError):
    pass


class CountAgentRunsArgs(BaseModel):
    pass


async def count_agent_runs(
    session: AsyncSession, args: BaseModel
) -> dict[str, object]:
    CountAgentRunsArgs.model_validate(args)
    count = await session.scalar(select(func.count()).select_from(AgentRun))
    if count is None:
        raise RuntimeError("The database returned no count for agent runs")
    return {"count": count}


TOOLS = [
    Tool(
        name="count_agent_runs",
        description="Count all rows stored in the agent_runs table.",
        args_model=CountAgentRunsArgs,
        handler=count_agent_runs,
    )
]


async def run_agent(
    session: AsyncSession,
    message: str,
    tools: list[Tool],
    max_steps: int = 8,
) -> tuple[AgentAnswer, list[AgentStep]]:
    tool_by_name = {tool.name: tool for tool in tools}
    sdk_tools = [
        pydantic_function_tool(
            tool.args_model,
            name=tool.name,
            description=tool.description,
        )
        for tool in tools
    ]
    input_items: ResponseInputParam = [{"role": "user", "content": message}]
    steps: list[AgentStep] = []

    while True:
        response = await client.responses.parse(
            model=settings.openai_model,
            instructions=(
                "Answer the user's request concisely. Use an available tool whenever "
                "it can supply the requested information, and never guess data that a "
                "tool can retrieve."
            ),
            input=input_items,
            tools=sdk_tools,
            text_format=AgentAnswer,
        )
        input_items.extend(cast(ResponseInputParam, response.output))
        calls = [
            item
            for item in response.output
            if isinstance(item, ResponseFunctionToolCall)
        ]

        if not calls:
            answer = response.output_parsed
            if answer is None:
                raise ValueError("The model returned no structured final answer")
            return answer, steps

        if len(steps) + len(calls) > max_steps:
            raise AgentStepLimitError(
                f"Agent exceeded the maximum of {max_steps} tool calls"
            )

        for call in calls:
            tool = tool_by_name.get(call.name)
            if tool is None:
                raise ValueError(f"Unknown tool requested: {call.name}")

            args = tool.args_model.model_validate_json(call.arguments)
            result = await tool.handler(session, args)
            arguments = args.model_dump()
            steps.append(
                AgentStep(
                    tool=tool.name,
                    arguments=arguments,
                    result=result,
                )
            )
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result),
                }
            )
