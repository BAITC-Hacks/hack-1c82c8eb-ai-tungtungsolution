"""State-aware bounded cache and durable audit for recommendation requests."""

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import AgentResult, AgentStep, RecommendationAgent
from app.recommendation_data import (
    RecommendationSnapshot,
    load_snapshot,
    prepare_context,
)

type CacheKey = tuple[str, str]


@dataclass(frozen=True)
class CacheEntry:
    result: AgentResult
    source_run_id: int
    expires_at: float


class RecommendationCache:
    """Per-process LRU. Changed DB inputs invalidate entries across workers too.

    Reload inputs before lookup: a completed activity, dismissal or jury upload
    changes the key even if an explicit invalidation happens in another worker.
    Mutation endpoints may also invalidate_employee()/clear() after committing.
    Failures are not cached so a restored AI service is retried on the next request.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if ttl_seconds <= 0 or max_entries < 1:
            raise ValueError("Cache TTL and capacity must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._entries: OrderedDict[CacheKey, CacheEntry] = OrderedDict()

    @staticmethod
    def key(snapshot: RecommendationSnapshot, message: str, model: str) -> CacheKey:
        encoded = json.dumps(
            {
                "snapshot": snapshot.model_dump(mode="json"),
                "message": message,
                "model": model,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return snapshot.profile.employee_id, hashlib.sha256(encoded).hexdigest()

    def get(self, key: CacheKey) -> CacheEntry | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self.clock():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return CacheEntry(
            entry.result.model_copy(deep=True),
            entry.source_run_id,
            entry.expires_at,
        )

    def put(self, key: CacheKey, result: AgentResult, *, source_run_id: int) -> None:
        if result.fallback_used:
            return
        now = self.clock()
        for expired in [
            key for key, entry in self._entries.items() if entry.expires_at <= now
        ]:
            del self._entries[expired]
        self._entries[key] = CacheEntry(
            result.model_copy(deep=True), source_run_id, now + self.ttl_seconds
        )
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def invalidate_employee(self, employee_id: str) -> None:
        for key in [key for key in self._entries if key[0] == employee_id]:
            del self._entries[key]

    def clear(self) -> None:
        self._entries.clear()


class RecommendationRun(AgentResult):
    id: int
    created_at: datetime


async def recommend(
    session: AsyncSession,
    *,
    employee_id: str,
    message: str,
    agent: RecommendationAgent,
    cache: RecommendationCache,
) -> RecommendationRun:
    from app.models import AgentRun

    started = monotonic()
    snapshot = await load_snapshot(session, employee_id)
    key = cache.key(snapshot, message, agent.model)
    cached = cache.get(key)
    if cached is None:
        result = await agent.run(prepare_context(snapshot), message)
    else:
        result = cached.result.model_copy(
            update={
                "cache_hit": True,
                "steps": [
                    AgentStep(
                        tool="recommendation_cache",
                        arguments={},
                        result={"source_run_id": cached.source_run_id},
                    )
                ],
            }
        )
    result.latency_ms = int((monotonic() - started) * 1000)
    audit_steps = [step.model_dump(mode="json") for step in result.steps]
    audit_steps.append(
        AgentStep(
            tool="recommendation_result",
            arguments={},
            result=result.model_dump(mode="json", exclude={"steps", "answer"}),
        ).model_dump(mode="json")
    )
    row = AgentRun(
        employee_id=employee_id,
        kind="recommendation",
        user_input=message,
        answer=result.answer,
        steps=audit_steps,
        latency_ms=result.latency_ms,
        fallback_used=result.fallback_used,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    # Do not publish a cache entry for a run whose audit failed to persist.
    if cached is None:
        cache.put(key, result, source_run_id=row.id)
    return RecommendationRun(
        **result.model_dump(), id=row.id, created_at=row.created_at
    )
