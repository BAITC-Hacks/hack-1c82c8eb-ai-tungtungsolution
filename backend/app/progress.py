"""Capped skill effects, assessment/history reconciliation and progress previews."""

from collections.abc import Mapping, Sequence
from datetime import date as DateValue
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.trajectory import (
    DevelopmentProfile,
    Grade,
    RoleRequirements,
    SkillLevel,
    Trajectory,
    calculate_trajectory,
    validate_levels,
)

REPEATABLE_EVENT_IDS = frozenset({"EV_036"})
type EventFormat = Literal["online", "offline", "self_paced"]
type ActivityStatus = Literal[
    "completed", "in_progress", "dropped", "no_show", "declined", "overdue"
]


class SkillEffect(BaseModel):
    skill_id: str
    gain: int = Field(strict=True, gt=0)
    max_level: SkillLevel


class DevelopmentEvent(BaseModel):
    """Domain projection; the existing ingest parsers validate uploaded documents."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    title: str
    type: Literal[
        "compliance",
        "onboarding",
        "course",
        "workshop",
        "mentoring",
        "certification",
        "meetup",
    ]
    format: EventFormat
    duration_hours: float = Field(gt=0, allow_inf_nan=False)
    mandatory: bool
    target_roles: list[str]
    target_grades: list[Grade]
    develops_skills: list[SkillEffect]
    prerequisites: dict[str, SkillLevel]
    upcoming_sessions: list[DateValue]

    @model_validator(mode="after")
    def validate_unique_effects(self) -> Self:
        identifiers = [effect.skill_id for effect in self.develops_skills]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("develops_skills must not contain duplicate skills")
        return self


class ActivityRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: str
    employee_id: str
    event_id: str
    date: DateValue
    status: ActivityStatus


class SkillChange(BaseModel):
    skill_id: str
    before: SkillLevel
    after: SkillLevel

    @computed_field
    @property
    def gain(self) -> int:
        return self.after - self.before


class ProgressDiff(BaseModel):
    before: Trajectory
    after: Trajectory
    skills_after: dict[str, SkillLevel]
    changes: list[SkillChange]


def effective_gain(current: int, gain: int, max_level: int) -> int:
    validate_levels({"current": current, "max_level": max_level})
    if type(gain) is not int or gain <= 0:
        raise ValueError("gain must be a positive integer")
    return max(0, min(gain, max_level - current))


def apply_skill_gains(
    skills: Mapping[str, int], effects: Sequence[SkillEffect]
) -> dict[str, int]:
    validate_levels(skills)
    updated = dict(skills)
    seen: set[str] = set()
    for effect in effects:
        if effect.skill_id in seen:
            raise ValueError(f"Duplicate skill effect: {effect.skill_id}")
        seen.add(effect.skill_id)
        current = skills.get(effect.skill_id, 0)
        gain = effective_gain(current, effect.gain, effect.max_level)
        if gain > 0:
            updated[effect.skill_id] = current + gain
    return updated


def effective_skills(
    profile: DevelopmentProfile,
    events: Mapping[str, DevelopmentEvent],
    history: Sequence[ActivityRecord],
    *,
    as_of_date: DateValue,
) -> dict[str, int]:
    """Replay only this employee's completions strictly after the assessment.

    Always start with assessed levels. Reusing the same input is idempotent;
    persisting these derived levels as assessed levels would double-count history.
    Same-day effects use record_id order as the dataset has no completion time.
    """
    if profile.last_review_date > as_of_date:
        raise ValueError("The assessment cannot be after the snapshot date")
    records = sorted(
        (
            row
            for row in history
            if row.employee_id == profile.employee_id and row.date <= as_of_date
        ),
        key=lambda row: (row.date, row.record_id),
    )
    skills = dict(profile.skills)
    seen_records: set[str] = set()
    completed: set[str] = set()
    for row in records:
        if row.record_id in seen_records:
            raise ValueError(f"Duplicate activity record: {row.record_id}")
        seen_records.add(row.record_id)
        if row.event_id not in events:
            raise ValueError(f"Unknown event in history: {row.event_id}")
        if row.status != "completed":
            continue
        # Organizer data repeats annual mandatory compliance training. The
        # non-repeatability rule applies to voluntary recommendation targets.
        if (
            row.event_id in completed
            and row.event_id not in REPEATABLE_EVENT_IDS
            and not events[row.event_id].mandatory
        ):
            raise ValueError(f"Non-repeatable event completed twice: {row.event_id}")
        completed.add(row.event_id)
        if row.date > profile.last_review_date:
            skills = apply_skill_gains(skills, events[row.event_id].develops_skills)
    return skills


def simulate_completion(
    profile: DevelopmentProfile,
    event: DevelopmentEvent,
    requirements: Sequence[RoleRequirements],
) -> ProgressDiff:
    """Preview one completion using effective levels supplied by the caller."""
    updated = apply_skill_gains(profile.skills, event.develops_skills)
    after_profile = profile.model_copy(update={"skills": updated})
    return ProgressDiff(
        before=calculate_trajectory(profile, requirements),
        after=calculate_trajectory(after_profile, requirements),
        skills_after=updated,
        changes=[
            SkillChange(
                skill_id=skill_id,
                before=profile.skills.get(skill_id, 0),
                after=level,
            )
            for skill_id, level in sorted(updated.items())
            if level != profile.skills.get(skill_id, 0)
        ],
    )
