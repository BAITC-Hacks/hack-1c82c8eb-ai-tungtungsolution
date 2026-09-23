from datetime import datetime

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.agent import TOOLS, AgentStep, run_agent
from app.config import settings
from app.db import SessionDep
from app.models import AgentRun


class HealthOut(BaseModel):
    status: str
    database: str


class AgentRunIn(BaseModel):
    message: str = Field(min_length=1)


class AgentRunOut(BaseModel):
    id: int
    answer: str
    steps: list[AgentStep]
    created_at: datetime


api = APIRouter(prefix="/api")


@api.get("/health", response_model=HealthOut)
async def health(session: SessionDep) -> HealthOut:
    await session.execute(text("SELECT 1"))
    return HealthOut(status="ok", database="ok")


@api.post("/agent/run", response_model=AgentRunOut)
async def run_agent_endpoint(payload: AgentRunIn, session: SessionDep) -> AgentRunOut:
    answer, steps = await run_agent(session, payload.message, TOOLS)
    row = AgentRun(
        user_input=payload.message,
        answer=answer.answer,
        steps=[step.model_dump() for step in steps],
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return AgentRunOut(
        id=row.id,
        answer=row.answer,
        steps=steps,
        created_at=row.created_at,
    )


app = FastAPI()
app.include_router(api)

if settings.frontend_dist is not None:
    app.mount(
        "/",
        StaticFiles(directory=settings.frontend_dist, html=True),
        name="spa",
    )
