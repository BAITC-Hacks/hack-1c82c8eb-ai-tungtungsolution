from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.agent import RecommendationAgent
from app.config import settings
from app.db import SessionDep
from app.llm import client
from app.recommendation_data import EmployeeNotFoundError
from app.recommendation_service import RecommendationCache, RecommendationRun, recommend


class HealthOut(BaseModel):
    status: str
    database: str


class AgentRunIn(BaseModel):
    employee_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=4000)


recommendation_agent = RecommendationAgent(
    client=client,
    model=settings.openai_model,
    timeout_seconds=settings.agent_timeout_seconds,
    max_rounds=settings.agent_max_rounds,
)
recommendation_cache = RecommendationCache(
    ttl_seconds=settings.recommendation_cache_ttl_seconds,
    max_entries=settings.recommendation_cache_max_entries,
)


api = APIRouter(prefix="/api")


@api.get("/health", response_model=HealthOut)
async def health(session: SessionDep) -> HealthOut:
    await session.execute(text("SELECT 1"))
    return HealthOut(status="ok", database="ok")


@api.post("/agent/run", response_model=RecommendationRun)
async def run_agent_endpoint(
    payload: AgentRunIn, session: SessionDep
) -> RecommendationRun:
    try:
        return await recommend(
            session,
            employee_id=payload.employee_id,
            message=payload.message,
            agent=recommendation_agent,
            cache=recommendation_cache,
        )
    except EmployeeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Сотрудник не найден") from exc


app = FastAPI()
app.include_router(api)

if settings.frontend_dist is not None:
    app.mount(
        "/",
        StaticFiles(directory=settings.frontend_dist, html=True),
        name="spa",
    )
