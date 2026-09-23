"""Deterministic eligibility and four-factor recommendation ranking.

All factors are in [0, 1]. Fixed product formula:
score = .40 * gap_closure + .25 * grade_relevance
      + .20 * history_affinity + .15 * format_fit.

gap_closure: covered next-grade gap units / all next-grade gap units (0 if none).
grade_relevance: (2 * critical units closed + other units closed)
                 / (2 * all effective skill gains).
history_affinity: (completed similar voluntary activities + 1)
                  / (finished/abandoned/declined/missed similar activities + 2).
Similarity means the same activity type or a shared developed skill.
In-progress activities have no outcome yet and do not count as failures.
format_fit is a work-arrangement heuristic, not a claimed personal preference:
remote: online/self-paced 1, offline 0; hybrid: all 1;
office: offline 1, online/self-paced .75.
"""

from collections.abc import Collection, Mapping, Sequence
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from app.progress import (
    REPEATABLE_EVENT_IDS,
    ActivityRecord,
    DevelopmentEvent,
    EventFormat,
    SkillChange,
    effective_gain,
    effective_skills,
    simulate_completion,
)
from app.trajectory import DevelopmentProfile, RoleRequirements, calculate_trajectory

type IneligibilityReason = Literal[
    "mandatory",
    "wrong_role",
    "wrong_grade",
    "prerequisites_not_met",
    "already_completed",
    "in_progress",
    "dismissed",
    "no_effective_gain",
    "no_upcoming_session",
]


class Eligibility(BaseModel):
    reasons: list[IneligibilityReason]

    @computed_field
    @property
    def eligible(self) -> bool:
        return not self.reasons


class RecommendationFactors(BaseModel):
    gap_closure: float = Field(ge=0, le=1)
    grade_relevance: float = Field(ge=0, le=1)
    history_affinity: float = Field(ge=0, le=1)
    format_fit: float = Field(ge=0, le=1)

    @computed_field
    @property
    def score(self) -> float:
        return (
            0.40 * self.gap_closure
            + 0.25 * self.grade_relevance
            + 0.20 * self.history_affinity
            + 0.15 * self.format_fit
        )


class HistoryEvidence(BaseModel):
    completed: int = Field(ge=0)
    unsuccessful: int = Field(ge=0)
    record_ids: list[str]

    @computed_field
    @property
    def affinity(self) -> float:
        return (self.completed + 1) / (self.completed + self.unsuccessful + 2)


class Candidate(BaseModel):
    event_id: str
    title: str
    format: EventFormat
    duration_hours: float
    next_session: date | None
    factors: RecommendationFactors
    history: HistoryEvidence
    changes: list[SkillChange]
    readiness_before: float | None
    readiness_after: float | None
    critical_skills_closed: list[str]

    @computed_field
    @property
    def score(self) -> float:
        return self.factors.score


def check_eligibility(
    profile: DevelopmentProfile,
    event: DevelopmentEvent,
    history: Sequence[ActivityRecord],
    *,
    as_of_date: date,
    dismissed_event_ids: Collection[str] = (),
) -> Eligibility:
    """The caller supplies effective (assessment + completed history) skills."""
    reasons: list[IneligibilityReason] = []
    if event.mandatory:
        reasons.append("mandatory")
    if profile.role not in event.target_roles:
        reasons.append("wrong_role")
    if profile.grade not in event.target_grades:
        reasons.append("wrong_grade")
    if any(
        profile.skills.get(skill_id, 0) < minimum
        for skill_id, minimum in event.prerequisites.items()
    ):
        reasons.append("prerequisites_not_met")
    relevant_history = [
        row
        for row in history
        if row.employee_id == profile.employee_id
        and row.event_id == event.event_id
        and row.date <= as_of_date
    ]
    if event.event_id not in REPEATABLE_EVENT_IDS and any(
        row.status == "completed" for row in relevant_history
    ):
        reasons.append("already_completed")
    if any(row.status == "in_progress" for row in relevant_history):
        reasons.append("in_progress")
    if event.event_id in dismissed_event_ids:
        reasons.append("dismissed")
    if not any(
        effective_gain(
            profile.skills.get(effect.skill_id, 0), effect.gain, effect.max_level
        )
        > 0
        for effect in event.develops_skills
    ):
        reasons.append("no_effective_gain")
    if event.format != "self_paced" and not any(
        session >= as_of_date for session in event.upcoming_sessions
    ):
        reasons.append("no_upcoming_session")
    return Eligibility(reasons=reasons)


def history_affinity(
    profile: DevelopmentProfile,
    candidate: DevelopmentEvent,
    events: Mapping[str, DevelopmentEvent],
    history: Sequence[ActivityRecord],
    *,
    as_of_date: date,
) -> HistoryEvidence:
    candidate_skills = {effect.skill_id for effect in candidate.develops_skills}
    completed = unsuccessful = 0
    record_ids: list[str] = []
    for row in sorted(history, key=lambda item: (item.date, item.record_id)):
        if row.employee_id != profile.employee_id or row.date > as_of_date:
            continue
        if row.event_id not in events:
            raise ValueError(f"Unknown event in history: {row.event_id}")
        past_event = events[row.event_id]
        if past_event.mandatory:
            continue
        shared_skills = candidate_skills.intersection(
            effect.skill_id for effect in past_event.develops_skills
        )
        if past_event.type != candidate.type and not shared_skills:
            continue
        if row.status == "completed":
            completed += 1
        elif row.status in {"dropped", "no_show", "declined"}:
            unsuccessful += 1
        else:
            continue
        record_ids.append(row.record_id)
    return HistoryEvidence(
        completed=completed, unsuccessful=unsuccessful, record_ids=record_ids
    )


def format_fit(profile: DevelopmentProfile, event: DevelopmentEvent) -> float:
    if profile.work_format == "hybrid":
        return 1.0
    if profile.work_format == "remote":
        return 0.0 if event.format == "offline" else 1.0
    return 1.0 if event.format == "offline" else 0.75


def rank_candidates(
    profile: DevelopmentProfile,
    events: Sequence[DevelopmentEvent],
    history: Sequence[ActivityRecord],
    requirements: Sequence[RoleRequirements],
    *,
    as_of_date: date,
    dismissed_event_ids: Collection[str] = (),
) -> list[Candidate]:
    """Rank all eligible events. An empty list means none satisfy eligibility.

    Readiness, eligibility and scoring use the same effective skills. Input data
    errors propagate instead of masquerading as an absence of recommendations.
    Equal scores are ordered by event_id so fallback results remain reproducible.
    """
    event_by_id = {event.event_id: event for event in events}
    if len(event_by_id) != len(events):
        raise ValueError("Duplicate event IDs")
    employee_history = [
        row
        for row in history
        if row.employee_id == profile.employee_id and row.date <= as_of_date
    ]
    current = profile.model_copy(
        update={
            "skills": effective_skills(
                profile, event_by_id, employee_history, as_of_date=as_of_date
            )
        }
    )
    # Validate target requirements even when every event is ineligible.
    trajectory = calculate_trajectory(current, requirements)
    gap_by_skill = {skill.skill_id: skill for skill in trajectory.gaps}
    total_gap = sum(skill.gap for skill in trajectory.gaps)
    candidates: list[Candidate] = []
    for event in events:
        if not check_eligibility(
            current,
            event,
            employee_history,
            as_of_date=as_of_date,
            dismissed_event_ids=dismissed_event_ids,
        ).eligible:
            continue
        progress = simulate_completion(current, event, requirements)
        covered = critical_covered = 0
        critical_skills_closed: list[str] = []
        for change in progress.changes:
            gap = gap_by_skill.get(change.skill_id)
            if gap is not None:
                closed = min(gap.gap, change.gain)
                covered += closed
                if gap.is_critical:
                    critical_covered += closed
                    if closed == gap.gap:
                        critical_skills_closed.append(change.skill_id)
        gain = sum(change.gain for change in progress.changes)
        evidence = history_affinity(
            current, event, event_by_id, employee_history, as_of_date=as_of_date
        )
        factors = RecommendationFactors(
            gap_closure=covered / total_gap if total_gap else 0.0,
            grade_relevance=(covered + critical_covered) / (2 * gain),
            history_affinity=evidence.affinity,
            format_fit=format_fit(current, event),
        )
        sessions = [day for day in event.upcoming_sessions if day >= as_of_date]
        candidates.append(
            Candidate(
                event_id=event.event_id,
                title=event.title,
                format=event.format,
                duration_hours=event.duration_hours,
                next_session=min(sessions) if sessions else None,
                factors=factors,
                history=evidence,
                changes=progress.changes,
                readiness_before=progress.before.readiness,
                readiness_after=progress.after.readiness,
                critical_skills_closed=critical_skills_closed,
            )
        )
    return sorted(
        candidates, key=lambda candidate: (-candidate.score, candidate.event_id)
    )
