from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text

from app.agent import RecommendationAgent
from app.config import settings
from app.db import SessionDep
from app.employee_api import create_router
from app.hr_api import create_router as create_hr_router
from app.llm import client
from app.recommendation_service import RecommendationCache


class HealthOut(BaseModel):
    status: str
    database: str


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


app = FastAPI()
app.include_router(api)
app.include_router(
    create_router(
        recommendation_cache=recommendation_cache,
        recommendation_agent=recommendation_agent,
    )
)
app.include_router(create_hr_router(recommendation_cache=recommendation_cache))

if settings.frontend_dist is not None:
    app.mount(
        "/",
        StaticFiles(directory=settings.frontend_dist, html=True),
        name="spa",
    )
