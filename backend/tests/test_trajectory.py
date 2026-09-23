import pytest
from pydantic import ValidationError

from app.trajectory import (
    DevelopmentProfile,
    RoleRequirements,
    calculate_readiness,
    calculate_trajectory,
    next_grade,
)


@pytest.mark.parametrize(
    "current, expected",
    [
        ("Junior", "Middle"),
        ("Middle", "Senior"),
        ("Senior", "Lead"),
        ("Lead", None),
    ],
)
def test_next_grade(current: str, expected: str | None) -> None:
    assert next_grade(current) == expected


def test_unknown_grade_is_an_error() -> None:
    with pytest.raises(ValueError, match="Unknown grade"):
        next_grade("Expert")


def test_readiness_caps_surplus_and_treats_missing_skills_as_zero() -> None:
    assert calculate_readiness({"a": 5, "b": 1}, {"a": 3, "b": 3}) == pytest.approx(
        200 / 3
    )
    assert calculate_readiness({"a": 5, "unrelated": 5}, {"a": 3, "b": 3}) == 50


def test_zero_requirements_are_satisfied() -> None:
    assert calculate_readiness({}, {}) == 100
    assert calculate_readiness({}, {"a": 0}) == 100


@pytest.mark.parametrize("level", [-1, 6, True])
def test_invalid_levels_are_rejected(level: int) -> None:
    with pytest.raises(ValueError, match="skill level"):
        calculate_readiness({"a": level}, {"a": 3})


def test_critical_gap_is_visible_even_with_high_readiness(
    profile: DevelopmentProfile,
) -> None:
    target = RoleRequirements(
        role=profile.role,
        grade="Senior",
        required_skills={"SK_SYSTEM_DESIGN": 3, "SK_PYTHON": 4},
        critical_skills=["SK_SYSTEM_DESIGN"],
    )
    trajectory = calculate_trajectory(profile, [target])
    assert trajectory.readiness == pytest.approx(600 / 7)
    assert not trajectory.critical_skills_met
    assert not trajectory.promotion_ready
    assert [(item.skill_id, item.gap) for item in trajectory.gaps] == [
        ("SK_SYSTEM_DESIGN", 1)
    ]


def test_missing_next_grade_profile_is_an_error(profile: DevelopmentProfile) -> None:
    with pytest.raises(ValueError, match="Expected one requirements profile"):
        calculate_trajectory(profile, [])


def test_duplicate_requirements_are_an_error(
    profile: DevelopmentProfile,
    requirements: list[RoleRequirements],
) -> None:
    with pytest.raises(ValueError, match="found 2"):
        calculate_trajectory(profile, requirements * 2)


def test_lead_has_no_invented_promotion_target(profile: DevelopmentProfile) -> None:
    trajectory = calculate_trajectory(profile.model_copy(update={"grade": "Lead"}), [])
    assert trajectory.target_grade is None
    assert trajectory.readiness is None
    assert trajectory.critical_skills_met is None
    assert not trajectory.promotion_ready


def test_invalid_critical_skill_reference_is_an_error() -> None:
    with pytest.raises(ValidationError, match="included in required_skills"):
        RoleRequirements(
            role="Backend Engineer",
            grade="Senior",
            required_skills={"SK_PYTHON": 3},
            critical_skills=["SK_UNKNOWN"],
        )
