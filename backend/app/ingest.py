import csv
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActivityHistory,
    DatasetMetadata,
    Employee,
    EmployeeSkill,
    Event,
    EventSkill,
    GradeRequirement,
    RoleProfile,
    Skill,
)

GRADES = ("Junior", "Middle", "Senior", "Lead")
HISTORY_COLUMNS = (
    "record_id",
    "employee_id",
    "event_id",
    "date",
    "due_date",
    "status",
    "completion_pct",
    "score",
    "feedback_rating",
    "assigned_by",
)


class IngestValidationError(ValueError):
    pass


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetMeta(InputModel):
    dataset: str
    version: str
    as_of_date: date


class CareerGoal(InputModel):
    target_role: str
    target_grade: str


class EmployeeRecord(InputModel):
    employee_id: str
    full_name: str
    department: str
    role: str
    grade: Literal["Junior", "Middle", "Senior", "Lead"]
    manager_id: str | None
    hire_date: date
    tenure_months: int = Field(ge=0)
    work_format: Literal["office", "hybrid", "remote"]
    preferred_language: Literal["kk", "ru", "en"]
    career_goal: CareerGoal | None
    skills: dict[str, int]
    last_review_date: date

    @field_validator("skills")
    @classmethod
    def validate_skill_levels(cls, value: dict[str, int]) -> dict[str, int]:
        if any(type(level) is not int or not 0 <= level <= 5 for level in value.values()):
            raise ValueError("every skill level must be an integer from 0 to 5")
        return value


class SkillRecord(InputModel):
    skill_id: str
    name: str
    type: Literal["hard", "soft"]
    category: str
    description: str


class RoleProfileRecord(InputModel):
    role: str
    grade: Literal["Junior", "Middle", "Senior", "Lead"]
    required_skills: dict[str, int]
    critical_skills: list[str]

    @field_validator("required_skills")
    @classmethod
    def validate_required_levels(cls, value: dict[str, int]) -> dict[str, int]:
        if any(type(level) is not int or not 0 <= level <= 5 for level in value.values()):
            raise ValueError("every required level must be an integer from 0 to 5")
        return value


class EventSkillRecord(InputModel):
    skill_id: str
    gain: int = Field(gt=0)
    max_level: int = Field(ge=0, le=5)


class EventRecord(InputModel):
    event_id: str
    title: str
    description: str
    type: Literal[
        "compliance",
        "onboarding",
        "course",
        "workshop",
        "mentoring",
        "certification",
        "meetup",
    ]
    format: Literal["online", "offline", "self_paced"]
    duration_hours: float = Field(gt=0)
    mandatory: bool
    target_roles: list[str]
    target_grades: list[Literal["Junior", "Middle", "Senior", "Lead"]]
    develops_skills: list[EventSkillRecord]
    prerequisites: dict[str, int]
    upcoming_sessions: list[date]

    @field_validator("prerequisites")
    @classmethod
    def validate_prerequisite_levels(cls, value: dict[str, int]) -> dict[str, int]:
        if any(type(level) is not int or not 0 <= level <= 5 for level in value.values()):
            raise ValueError("every prerequisite level must be an integer from 0 to 5")
        return value


class HistoryRecord(InputModel):
    record_id: str
    employee_id: str
    event_id: str
    date: date
    due_date: date | None
    status: Literal[
        "completed", "in_progress", "dropped", "no_show", "declined", "overdue"
    ]
    completion_pct: int = Field(ge=0, le=100)
    score: int | None = Field(default=None, ge=0, le=100)
    feedback_rating: int | None = Field(default=None, ge=1, le=5)
    assigned_by: Literal["self", "manager", "hr"]


@dataclass(frozen=True)
class EmployeesDocument:
    meta: DatasetMeta
    employees: list[EmployeeRecord]


@dataclass(frozen=True)
class EventsDocument:
    meta: DatasetMeta
    events: list[EventRecord]


@dataclass(frozen=True)
class SkillsDocument:
    meta: DatasetMeta
    proficiency_scale: dict[str, str]
    skills: list[SkillRecord]
    role_profiles: list[RoleProfileRecord]


@dataclass(frozen=True)
class DatasetBundle:
    employees: EmployeesDocument
    events: EventsDocument
    skills: SkillsDocument
    history: list[HistoryRecord]


@dataclass(frozen=True)
class IngestCounts:
    metadata: int
    employees: int
    employee_skills: int
    skills: int
    role_profiles: int
    grade_requirements: int
    events: int
    event_skills: int
    activity_history: int


def _error(filename: str, record: str, message: str) -> IngestValidationError:
    return IngestValidationError(f"{filename} record {record}: {message}")


def _validate[T: InputModel](
    model: type[T], value: object, *, filename: str, record: str
) -> T:
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise _error(filename, record, str(exc)) from exc


def _load_json(raw: bytes, filename: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error(filename, "document", str(exc)) from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _error(filename, "document", "top-level value must be an object")
    return cast(dict[str, object], value)


def _require_keys(
    value: dict[str, object], expected: set[str], *, filename: str, record: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise _error(filename, record, f"missing fields {missing}; unexpected fields {extra}")


def _record_list(value: object, *, filename: str, field: str) -> list[object]:
    if not isinstance(value, list):
        raise _error(filename, "document", f"{field} must be an array")
    return cast(list[object], value)


def _record_label(value: object, field: str, index: int) -> str:
    if isinstance(value, dict):
        identifier = value.get(field)
        if isinstance(identifier, str):
            return identifier
    return f"index {index}"


def parse_employees_json(raw: bytes, filename: str = "employees.json") -> EmployeesDocument:
    value = _load_json(raw, filename)
    _require_keys(value, {"meta", "employees"}, filename=filename, record="document")
    meta = _validate(DatasetMeta, value["meta"], filename=filename, record="meta")
    employees = [
        _validate(
            EmployeeRecord,
            record,
            filename=filename,
            record=_record_label(record, "employee_id", index),
        )
        for index, record in enumerate(
            _record_list(value["employees"], filename=filename, field="employees")
        )
    ]
    return EmployeesDocument(meta=meta, employees=employees)


def parse_events_json(raw: bytes, filename: str = "events.json") -> EventsDocument:
    value = _load_json(raw, filename)
    _require_keys(value, {"meta", "events"}, filename=filename, record="document")
    meta = _validate(DatasetMeta, value["meta"], filename=filename, record="meta")
    events = [
        _validate(
            EventRecord,
            record,
            filename=filename,
            record=_record_label(record, "event_id", index),
        )
        for index, record in enumerate(
            _record_list(value["events"], filename=filename, field="events")
        )
    ]
    return EventsDocument(meta=meta, events=events)


def parse_skills_json(raw: bytes, filename: str = "skills.json") -> SkillsDocument:
    value = _load_json(raw, filename)
    _require_keys(
        value,
        {"meta", "proficiency_scale", "skills", "role_profiles"},
        filename=filename,
        record="document",
    )
    meta = _validate(DatasetMeta, value["meta"], filename=filename, record="meta")
    scale = value["proficiency_scale"]
    if not isinstance(scale, dict) or not all(
        isinstance(key, str) and isinstance(description, str)
        for key, description in scale.items()
    ):
        raise _error(filename, "proficiency_scale", "must map strings to strings")
    proficiency_scale = cast(dict[str, str], scale)
    if set(proficiency_scale) != {str(level) for level in range(6)}:
        raise _error(filename, "proficiency_scale", "must define levels 0 through 5")
    skills = [
        _validate(
            SkillRecord,
            record,
            filename=filename,
            record=_record_label(record, "skill_id", index),
        )
        for index, record in enumerate(
            _record_list(value["skills"], filename=filename, field="skills")
        )
    ]
    profiles = [
        _validate(
            RoleProfileRecord,
            record,
            filename=filename,
            record=(
                f"{record.get('role')}/{record.get('grade')}"
                if isinstance(record, dict)
                else f"index {index}"
            ),
        )
        for index, record in enumerate(
            _record_list(
                value["role_profiles"], filename=filename, field="role_profiles"
            )
        )
    ]
    return SkillsDocument(
        meta=meta,
        proficiency_scale=proficiency_scale,
        skills=skills,
        role_profiles=profiles,
    )


def _csv_int(value: str, *, filename: str, record: str, field: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise _error(filename, record, f"{field} must be an integer") from exc


def _csv_optional_int(
    value: str, *, filename: str, record: str, field: str
) -> int | None:
    if value == "":
        return None
    return _csv_int(value, filename=filename, record=record, field=field)


def parse_history_csv(
    raw: bytes, filename: str = "activity_history.csv"
) -> list[HistoryRecord]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _error(filename, "document", str(exc)) from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != HISTORY_COLUMNS:
        raise _error(
            filename,
            "header",
            f"expected columns {list(HISTORY_COLUMNS)}, got {reader.fieldnames}",
        )

    records: list[HistoryRecord] = []
    for row_number, row in enumerate(reader, start=2):
        record = row.get("record_id") or f"row {row_number}"
        if None in row:
            raise _error(filename, record, "row has more values than the header")
        parsed: dict[str, object] = {
            "record_id": row["record_id"],
            "employee_id": row["employee_id"],
            "event_id": row["event_id"],
            "date": row["date"],
            "due_date": row["due_date"] or None,
            "status": row["status"],
            "completion_pct": _csv_int(
                row["completion_pct"],
                filename=filename,
                record=record,
                field="completion_pct",
            ),
            "score": _csv_optional_int(
                row["score"], filename=filename, record=record, field="score"
            ),
            "feedback_rating": _csv_optional_int(
                row["feedback_rating"],
                filename=filename,
                record=record,
                field="feedback_rating",
            ),
            "assigned_by": row["assigned_by"],
        }
        history = _validate(
            HistoryRecord, parsed, filename=filename, record=record
        )
        if history.status == "completed" and history.completion_pct != 100:
            raise _error(filename, record, "completed records must have completion_pct 100")
        if history.status in {"no_show", "declined"} and history.completion_pct != 0:
            raise _error(
                filename, record, f"{history.status} records must have completion_pct 0"
            )
        records.append(history)
    return records


def _unique_by[T: InputModel](
    records: list[T], key: str, *, filename: str
) -> dict[str, T]:
    indexed: dict[str, T] = {}
    for record in records:
        identifier = getattr(record, key)
        if not isinstance(identifier, str):
            raise TypeError(f"{key} must be a string")
        if identifier in indexed:
            raise _error(filename, identifier, f"duplicate {key}")
        indexed[identifier] = record
    return indexed


def validate_dataset(bundle: DatasetBundle) -> None:
    employees = _unique_by(
        bundle.employees.employees, "employee_id", filename="employees.json"
    )
    events = _unique_by(bundle.events.events, "event_id", filename="events.json")
    skills = _unique_by(bundle.skills.skills, "skill_id", filename="skills.json")
    _unique_by(bundle.history, "record_id", filename="activity_history.csv")

    metas = {
        (document.meta.dataset, document.meta.version, document.meta.as_of_date)
        for document in (bundle.employees, bundle.events, bundle.skills)
    }
    if len(metas) != 1:
        raise _error("dataset", "meta", "JSON metadata must match across all files")
    snapshot_date = bundle.employees.meta.as_of_date

    profiles: dict[tuple[str, str], RoleProfileRecord] = {}
    for profile in bundle.skills.role_profiles:
        key = (profile.role, profile.grade)
        label = f"{profile.role}/{profile.grade}"
        if key in profiles:
            raise _error("skills.json", label, "duplicate role/grade profile")
        profiles[key] = profile
        unknown = set(profile.required_skills) - skills.keys()
        if unknown:
            raise _error("skills.json", label, f"unknown required skills {sorted(unknown)}")
        if not set(profile.critical_skills) <= profile.required_skills.keys():
            raise _error(
                "skills.json", label, "critical_skills must also be required_skills"
            )

    roles = {role for role, _grade in profiles}
    for role in roles:
        missing_grades = set(GRADES) - {grade for item_role, grade in profiles if item_role == role}
        if missing_grades:
            raise _error(
                "skills.json", role, f"missing grade profiles {sorted(missing_grades)}"
            )
        for lower, higher in pairwise(GRADES):
            lower_requirements = profiles[(role, lower)].required_skills
            higher_requirements = profiles[(role, higher)].required_skills
            decreased = [
                skill_id
                for skill_id, level in lower_requirements.items()
                if higher_requirements.get(skill_id, 0) < level
            ]
            if decreased:
                raise _error(
                    "skills.json",
                    f"{role}/{higher}",
                    f"requirements decrease for {sorted(decreased)}",
                )

    for employee in employees.values():
        label = employee.employee_id
        if (employee.role, employee.grade) not in profiles:
            raise _error("employees.json", label, "role and grade have no profile")
        unknown_skills = set(employee.skills) - skills.keys()
        if unknown_skills:
            raise _error(
                "employees.json", label, f"unknown skills {sorted(unknown_skills)}"
            )
        if employee.manager_id is not None:
            manager = employees.get(employee.manager_id)
            if manager is None:
                raise _error("employees.json", label, "manager_id does not exist")
            if manager.department != employee.department or manager.grade != "Lead":
                raise _error(
                    "employees.json", label, "manager must be a Lead in the same department"
                )
        if employee.career_goal is not None and (
            employee.career_goal.target_role,
            employee.career_goal.target_grade,
        ) not in profiles:
            raise _error("employees.json", label, "career_goal has no role/grade profile")
        if not employee.hire_date <= employee.last_review_date <= snapshot_date:
            raise _error(
                "employees.json",
                label,
                "hire_date, last_review_date and snapshot date are out of order",
            )
        tenure = (
            (snapshot_date.year - employee.hire_date.year) * 12
            + snapshot_date.month
            - employee.hire_date.month
            - (snapshot_date.day < employee.hire_date.day)
        )
        if employee.tenure_months != tenure:
            raise _error(
                "employees.json",
                label,
                f"tenure_months must be {tenure} for the dataset snapshot",
            )

    for event in events.values():
        label = event.event_id
        unknown_roles = set(event.target_roles) - roles
        if unknown_roles:
            raise _error("events.json", label, f"unknown target roles {sorted(unknown_roles)}")
        developed_ids = [item.skill_id for item in event.develops_skills]
        if len(developed_ids) != len(set(developed_ids)):
            raise _error("events.json", label, "develops_skills contains duplicates")
        unknown_skills = (set(developed_ids) | set(event.prerequisites)) - skills.keys()
        if unknown_skills:
            raise _error("events.json", label, f"unknown skills {sorted(unknown_skills)}")
        if event.format == "self_paced" and event.upcoming_sessions:
            raise _error("events.json", label, "self_paced events cannot have sessions")
        if event.format != "self_paced" and not event.upcoming_sessions:
            raise _error("events.json", label, "scheduled events need upcoming_sessions")
        if any(session_date < snapshot_date for session_date in event.upcoming_sessions):
            raise _error("events.json", label, "upcoming_sessions cannot be in the past")

    for history in bundle.history:
        label = history.record_id
        employee = employees.get(history.employee_id)
        event = events.get(history.event_id)
        if employee is None:
            raise _error("activity_history.csv", label, "employee_id does not exist")
        if event is None:
            raise _error("activity_history.csv", label, "event_id does not exist")
        if not employee.hire_date <= history.date <= snapshot_date:
            raise _error(
                "activity_history.csv", label, "date is outside employment/snapshot range"
            )
        if (history.due_date is not None) != event.mandatory:
            raise _error(
                "activity_history.csv",
                label,
                "due_date must be present exactly for mandatory events",
            )


def load_dataset(data_dir: Path) -> DatasetBundle:
    bundle = DatasetBundle(
        employees=parse_employees_json((data_dir / "employees.json").read_bytes()),
        events=parse_events_json((data_dir / "events.json").read_bytes()),
        skills=parse_skills_json((data_dir / "skills.json").read_bytes()),
        history=parse_history_csv((data_dir / "activity_history.csv").read_bytes()),
    )
    validate_dataset(bundle)
    return bundle


async def _upsert(
    session: AsyncSession,
    table_clause: object,
    rows: Sequence[Mapping[str, object]],
    key_columns: tuple[str, ...],
) -> None:
    if not rows:
        return
    table = cast(Table, table_clause)
    statement = insert(table).values([dict(row) for row in rows])
    updates = {
        column.name: statement.excluded[column.name]
        for column in table.columns
        if column.name not in key_columns
    }
    key_elements = [table.c[name] for name in key_columns]
    upsert = (
        statement.on_conflict_do_update(index_elements=key_elements, set_=updates)
        if updates
        else statement.on_conflict_do_nothing(index_elements=key_elements)
    )
    await session.execute(upsert)


async def ingest_dataset(session: AsyncSession, bundle: DatasetBundle) -> IngestCounts:
    metadata_rows: list[dict[str, object]] = [
        {
            "source_filename": filename,
            "dataset": document.meta.dataset,
            "version": document.meta.version,
            "as_of_date": document.meta.as_of_date,
            "proficiency_scale": (
                bundle.skills.proficiency_scale if filename == "skills.json" else None
            ),
        }
        for filename, document in (
            ("employees.json", bundle.employees),
            ("events.json", bundle.events),
            ("skills.json", bundle.skills),
        )
    ]
    skill_rows = [record.model_dump() for record in bundle.skills.skills]
    profile_rows = [
        {"role": record.role, "grade": record.grade}
        for record in bundle.skills.role_profiles
    ]
    requirement_rows = [
        {
            "role": profile.role,
            "grade": profile.grade,
            "skill_id": skill_id,
            "required_level": required_level,
            "is_critical": skill_id in profile.critical_skills,
        }
        for profile in bundle.skills.role_profiles
        for skill_id, required_level in profile.required_skills.items()
    ]
    employee_rows = [
        record.model_dump(exclude={"skills"}) for record in bundle.employees.employees
    ]
    employee_skill_rows = [
        {"employee_id": employee.employee_id, "skill_id": skill_id, "level": level}
        for employee in bundle.employees.employees
        for skill_id, level in employee.skills.items()
    ]
    event_rows = [
        record.model_dump(exclude={"develops_skills"})
        for record in bundle.events.events
    ]
    event_skill_rows = [
        {"event_id": event.event_id, **skill.model_dump()}
        for event in bundle.events.events
        for skill in event.develops_skills
    ]
    history_rows = [record.model_dump() for record in bundle.history]

    await _upsert(session, DatasetMetadata.__table__, metadata_rows, ("source_filename",))
    await _upsert(session, RoleProfile.__table__, profile_rows, ("role", "grade"))
    await _upsert(session, Skill.__table__, skill_rows, ("skill_id",))
    await _upsert(session, Employee.__table__, employee_rows, ("employee_id",))
    await _upsert(
        session,
        GradeRequirement.__table__,
        requirement_rows,
        ("role", "grade", "skill_id"),
    )
    await _upsert(
        session,
        EmployeeSkill.__table__,
        employee_skill_rows,
        ("employee_id", "skill_id"),
    )
    await _upsert(session, Event.__table__, event_rows, ("event_id",))
    await _upsert(
        session, EventSkill.__table__, event_skill_rows, ("event_id", "skill_id")
    )
    await _upsert(
        session, ActivityHistory.__table__, history_rows, ("record_id",)
    )

    return IngestCounts(
        metadata=len(metadata_rows),
        employees=len(employee_rows),
        employee_skills=len(employee_skill_rows),
        skills=len(skill_rows),
        role_profiles=len(profile_rows),
        grade_requirements=len(requirement_rows),
        events=len(event_rows),
        event_skills=len(event_skill_rows),
        activity_history=len(history_rows),
    )
