from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('recommendation', 'debug')", name="ck_agent_runs_kind"
        ),
        CheckConstraint("latency_ms >= 0", name="ck_agent_runs_latency_ms"),
        Index("ix_agent_runs_employee_created_at", "employee_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_input: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    steps: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    employee_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("employees.employee_id", name="fk_agent_runs_employee_id")
    )
    kind: Mapped[str] = mapped_column(Text, server_default="debug")
    latency_ms: Mapped[int | None]
    fallback_used: Mapped[bool] = mapped_column(server_default=false())


class DatasetMetadata(Base):
    __tablename__ = "dataset_metadata"

    source_filename: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    as_of_date: Mapped[date]
    proficiency_scale: Mapped[dict[str, str] | None] = mapped_column(
        JSONB(none_as_null=True)
    )


class RoleProfile(Base):
    __tablename__ = "role_profiles"
    __table_args__ = (
        CheckConstraint(
            "grade IN ('Junior', 'Middle', 'Senior', 'Lead')",
            name="ck_role_profiles_grade",
        ),
    )

    role: Mapped[str] = mapped_column(Text, primary_key=True)
    grade: Mapped[str] = mapped_column(Text, primary_key=True)


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        ForeignKeyConstraint(
            ["role", "grade"],
            ["role_profiles.role", "role_profiles.grade"],
            name="fk_employees_role_profile",
        ),
        CheckConstraint("tenure_months >= 0", name="ck_employees_tenure_months"),
        CheckConstraint(
            "work_format IN ('office', 'hybrid', 'remote')",
            name="ck_employees_work_format",
        ),
        CheckConstraint(
            "preferred_language IN ('kk', 'ru', 'en')",
            name="ck_employees_preferred_language",
        ),
        CheckConstraint(
            "last_review_date >= hire_date", name="ck_employees_review_after_hire"
        ),
        CheckConstraint(
            "manager_id <> employee_id", name="ck_employees_manager_not_self"
        ),
    )

    employee_id: Mapped[str] = mapped_column(Text, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text)
    department: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    grade: Mapped[str] = mapped_column(Text)
    # Deferral allows employees and their managers to be upserted in any order
    # within one import transaction; the reference is checked at commit.
    manager_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("employees.employee_id", deferrable=True, initially="DEFERRED"),
    )
    hire_date: Mapped[date]
    tenure_months: Mapped[int]
    work_format: Mapped[str] = mapped_column(Text)
    preferred_language: Mapped[str] = mapped_column(Text)
    career_goal: Mapped[dict[str, str] | None] = mapped_column(JSONB(none_as_null=True))
    last_review_date: Mapped[date]


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        CheckConstraint("type IN ('hard', 'soft')", name="ck_skills_type"),
    )

    skill_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)


class GradeRequirement(Base):
    __tablename__ = "grade_requirements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["role", "grade"],
            ["role_profiles.role", "role_profiles.grade"],
            name="fk_grade_requirements_role_profile",
        ),
        CheckConstraint(
            "required_level BETWEEN 0 AND 5", name="ck_grade_requirements_level"
        ),
    )

    role: Mapped[str] = mapped_column(Text, primary_key=True)
    grade: Mapped[str] = mapped_column(Text, primary_key=True)
    skill_id: Mapped[str] = mapped_column(
        Text, ForeignKey("skills.skill_id"), primary_key=True
    )
    required_level: Mapped[int] = mapped_column(SmallInteger)
    is_critical: Mapped[bool]


class EmployeeSkill(Base):
    """Assessed levels at last_review_date, before subsequent completed activities."""

    __tablename__ = "employee_skills"
    __table_args__ = (
        CheckConstraint("level BETWEEN 0 AND 5", name="ck_employee_skills_level"),
    )

    employee_id: Mapped[str] = mapped_column(
        Text, ForeignKey("employees.employee_id"), primary_key=True
    )
    skill_id: Mapped[str] = mapped_column(
        Text, ForeignKey("skills.skill_id"), primary_key=True
    )
    level: Mapped[int] = mapped_column(SmallInteger)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "type IN ('compliance', 'onboarding', 'course', 'workshop', "
            "'mentoring', 'certification', 'meetup')",
            name="ck_events_type",
        ),
        CheckConstraint(
            "format IN ('online', 'offline', 'self_paced')", name="ck_events_format"
        ),
        CheckConstraint("duration_hours > 0", name="ck_events_duration_hours"),
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(Text)
    duration_hours: Mapped[float] = mapped_column(Float)
    mandatory: Mapped[bool]
    target_roles: Mapped[list[str]] = mapped_column(ARRAY(Text))
    target_grades: Mapped[list[str]] = mapped_column(ARRAY(Text))
    prerequisites: Mapped[dict[str, int]] = mapped_column(JSONB)
    upcoming_sessions: Mapped[list[date]] = mapped_column(ARRAY(Date))


class EventSkill(Base):
    __tablename__ = "event_skills"
    __table_args__ = (
        CheckConstraint("gain > 0", name="ck_event_skills_gain"),
        CheckConstraint("max_level BETWEEN 0 AND 5", name="ck_event_skills_max_level"),
    )

    event_id: Mapped[str] = mapped_column(
        Text, ForeignKey("events.event_id"), primary_key=True
    )
    skill_id: Mapped[str] = mapped_column(
        Text, ForeignKey("skills.skill_id"), primary_key=True
    )
    gain: Mapped[int] = mapped_column(SmallInteger)
    max_level: Mapped[int] = mapped_column(SmallInteger)


class ActivityHistory(Base):
    __tablename__ = "activity_history"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'in_progress', 'dropped', 'no_show', "
            "'declined', 'overdue')",
            name="ck_activity_history_status",
        ),
        CheckConstraint(
            "completion_pct BETWEEN 0 AND 100",
            name="ck_activity_history_completion_pct",
        ),
        CheckConstraint("score BETWEEN 0 AND 100", name="ck_activity_history_score"),
        CheckConstraint(
            "feedback_rating BETWEEN 1 AND 5",
            name="ck_activity_history_feedback_rating",
        ),
        CheckConstraint(
            "assigned_by IN ('self', 'manager', 'hr')",
            name="ck_activity_history_assigned_by",
        ),
        Index("ix_activity_history_employee_date", "employee_id", "date"),
    )

    record_id: Mapped[str] = mapped_column(Text, primary_key=True)
    employee_id: Mapped[str] = mapped_column(Text, ForeignKey("employees.employee_id"))
    event_id: Mapped[str] = mapped_column(
        Text, ForeignKey("events.event_id"), index=True
    )
    date: Mapped[date]
    due_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(Text)
    completion_pct: Mapped[int] = mapped_column(SmallInteger)
    score: Mapped[int | None] = mapped_column(SmallInteger)
    feedback_rating: Mapped[int | None] = mapped_column(SmallInteger)
    assigned_by: Mapped[str] = mapped_column(Text)


class Dismissal(Base):
    __tablename__ = "dismissals"
    __table_args__ = (Index("ix_dismissals_employee_event", "employee_id", "event_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[str] = mapped_column(Text, ForeignKey("employees.employee_id"))
    event_id: Mapped[str] = mapped_column(Text, ForeignKey("events.event_id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
