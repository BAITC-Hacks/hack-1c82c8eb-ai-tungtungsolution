import pytest
from fastapi import HTTPException


def test_signed_session_round_trip_tamper_and_expiry(configured_backend: None) -> None:
    from app.auth import SessionPrincipal, SessionSigner

    now = [1_000.0]
    signer = SessionSigner(
        "a-secret-value-that-is-longer-than-thirty-two-characters",
        max_age_seconds=300,
        clock=lambda: now[0],
    )
    principal = SessionPrincipal(role="employee", employee_id="E0001")
    token = signer.issue(principal)
    assert signer.verify(token) == principal
    payload, signature = token.split(".")
    replacement = "A" if signature[-1] != "A" else "B"
    with pytest.raises(ValueError, match="Invalid session"):
        signer.verify(f"{payload}.{signature[:-1]}{replacement}")
    now[0] = 1_300.0
    with pytest.raises(ValueError, match="Invalid session"):
        signer.verify(token)


@pytest.mark.parametrize(
    "role,employee_id",
    [("employee", None), ("hr", "E0001")],
)
def test_session_identity_shape_is_strict(
    configured_backend: None, role: str, employee_id: str | None
) -> None:
    from pydantic import ValidationError

    from app.auth import SessionPrincipal

    with pytest.raises(ValidationError):
        SessionPrincipal(role=role, employee_id=employee_id)  # type: ignore[arg-type]


def test_role_guards(configured_backend: None) -> None:
    from app.auth import SessionPrincipal, require_employee, require_hr

    employee = SessionPrincipal(role="employee", employee_id="E0001")
    hr = SessionPrincipal(role="hr")
    assert require_employee(employee) == employee
    assert require_hr(hr) == hr
    with pytest.raises(HTTPException) as employee_error:
        require_employee(hr)
    with pytest.raises(HTTPException) as hr_error:
        require_hr(employee)
    assert employee_error.value.status_code == 403
    assert hr_error.value.status_code == 403
