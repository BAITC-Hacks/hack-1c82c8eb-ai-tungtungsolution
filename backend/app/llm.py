from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings

client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    timeout=settings.agent_timeout_seconds,
    max_retries=0,
    _strict_response_validation=True,
)


async def structured[T: BaseModel](
    *, instructions: str, input: str, schema: type[T]
) -> T:
    response = await client.responses.parse(
        model=settings.openai_model,
        instructions=instructions,
        input=input,
        text_format=schema,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise ValueError("The model returned no structured output")
    return parsed
