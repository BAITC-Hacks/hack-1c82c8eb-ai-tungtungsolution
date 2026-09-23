"""Pure next-grade calculations; no database, configuration or AI required."""

from collections.abc import Mapping, Sequence
from datetime import date
from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

type Grade = Literal["Junior", "Middle", "Senior", "Lead"]
type SkillLevel = Annotated[int, Field(strict=True, ge=0, le=5)]
GRADES: tuple[Grade, ...] = ("Junior", "Middle", "Senior", "Lead")


class DevelopmentProfile(BaseModel):
    """Calculation input projected from an employee record and assessed skills."""

    model_config = ConfigDict(frozen=True)

    employee_id: str
    role: str
    grade: Grade
    work_format: Literal["office", "hybrid", "remote"]
    skills: dict[str, SkillLevel]
    last_review_date: date


class RoleRequirements(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    grade: Grade
    required_skills: dict[str, SkillLevel]
    critical_skills: list[str]

    @model_validator(mode="after")
    def validate_critical_skills(self) -> Self:
        if len(self.critical_skills) != len(set(self.critical_skills)):
            raise ValueError("critical_skills must not contain duplicates")
        if not set(self.critical_skills) <= self.required_skills.keys():
            raise ValueError("critical_skills must be included in required_skills")
        return self


class SkillGap(BaseModel):
    skill_id: str
    current: SkillLevel
    required: SkillLevel
    gap: SkillLevel
    is_critical: bool


class Trajectory(BaseModel):
    employee_id: str
    role: str
    current_grade: Grade
    target_grade: Grade | None
    readiness: float | None = Field(ge=0, le=100)
    critical_skills_met: bool | None
    skills: list[SkillGap]

    @computed_field
    @property
    def gaps(self) -> list[SkillGap]:
        return [skill for skill in self.skills if skill.gap > 0]

    @computed_field
    @property
    def promotion_ready(self) -> bool:
        # This is skills readiness, not an automatic promotion decision.
        return self.target_grade is not None and not self.gaps


def validate_levels(levels: Mapping[str, int]) -> None:
    for skill_id, level in levels.items():
        if type(level) is not int or not 0 <= level <= 5:
            raise ValueError(f"{skill_id}: skill level must be an integer from 0 to 5")


def next_grade(grade: str) -> Grade | None:
    if grade not in GRADES:
        raise ValueError(f"Unknown grade: {grade}")
    for current, following in pairwise(GRADES):
        if grade == current:
            return following
    return None


def calculate_readiness(
    skills: Mapping[str, int], required_skills: Mapping[str, int]
) -> float:
    """A known profile with no positive requirements is fully satisfied."""
    validate_levels(skills)
    validate_levels(required_skills)
    total = sum(required_skills.values())
    if total == 0:
        return 100.0
    fulfilled = sum(
        min(skills.get(skill_id, 0), required)
        for skill_id, required in required_skills.items()
    )
    return fulfilled / total * 100


def calculate_trajectory(
    profile: DevelopmentProfile, requirements: Sequence[RoleRequirements]
) -> Trajectory:
    target = next_grade(profile.grade)
    if target is None:
        # The dataset defines no grade beyond Lead; do not invent a target.
        return Trajectory(
            employee_id=profile.employee_id,
            role=profile.role,
            current_grade=profile.grade,
            target_grade=None,
            readiness=None,
            critical_skills_met=None,
            skills=[],
        )
    matches = [
        item
        for item in requirements
        if item.role == profile.role and item.grade == target
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one requirements profile for {profile.role}/{target}, "
            f"found {len(matches)}"
        )
    target_requirements = matches[0]
    skills = [
        SkillGap(
            skill_id=skill_id,
            current=profile.skills.get(skill_id, 0),
            required=required,
            gap=max(0, required - profile.skills.get(skill_id, 0)),
            is_critical=skill_id in target_requirements.critical_skills,
        )
        for skill_id, required in sorted(target_requirements.required_skills.items())
    ]
    return Trajectory(
        employee_id=profile.employee_id,
        role=profile.role,
        current_grade=profile.grade,
        target_grade=target,
        readiness=calculate_readiness(
            profile.skills, target_requirements.required_skills
        ),
        critical_skills_met=all(
            skill.gap == 0 for skill in skills if skill.is_critical
        ),
        skills=skills,
    )
