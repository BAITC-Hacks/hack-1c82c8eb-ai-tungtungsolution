"""Signed demo sessions and role dependencies."""

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from time import time
from typing import Annotated, Literal, Self

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, model_validator

from app.config import settings

SESSION_COOKIE = "career_quest_session"
type Role = Literal["employee", "hr"]


class SessionPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Role
    employee_id: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if (self.role == "employee") != (self.employee_id is not None):
            raise ValueError("Employee sessions require exactly one employee_id")
        return self


class SessionSigner:
    def __init__(
        self,
        secret: str,
        *,
        max_age_seconds: int,
        clock: Callable[[], float] = time,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("Session secret must contain at least 32 characters")
        if max_age_seconds < 300:
            raise ValueError("Session lifetime must be at least five minutes")
        self._secret = secret.encode()
        self._max_age_seconds = max_age_seconds
        self._clock = clock

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)

    def issue(self, principal: SessionPrincipal) -> str:
        payload = json.dumps(
            {
                **principal.model_dump(),
                "expires_at": int(self._clock()) + self._max_age_seconds,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{self._encode(payload)}.{self._encode(signature)}"

    def verify(self, token: str) -> SessionPrincipal:
        try:
            payload_part, signature_part = token.split(".", maxsplit=1)
            payload = self._decode(payload_part)
            signature = self._decode(signature_part)
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("Invalid signature")
            value = json.loads(payload)
            expires_at = value.pop("expires_at")
            if type(expires_at) is not int or expires_at <= int(self._clock()):
                raise ValueError("Expired session")
            return SessionPrincipal.model_validate(value)
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid session") from exc


signer = SessionSigner(
    settings.session_secret,
    max_age_seconds=settings.session_max_age_seconds,
)


def get_principal(request: Request) -> SessionPrincipal:
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется войти в систему",
        )
    try:
        return signer.verify(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия недействительна или истекла",
        ) from exc


def require_employee(
    principal: Annotated[SessionPrincipal, Depends(get_principal)],
) -> SessionPrincipal:
    if principal.role != "employee":
        raise HTTPException(status_code=403, detail="Доступно только сотруднику")
    return principal


def require_hr(
    principal: Annotated[SessionPrincipal, Depends(get_principal)],
) -> SessionPrincipal:
    if principal.role != "hr":
        raise HTTPException(status_code=403, detail="Доступно только HR")
    return principal


type PrincipalDep = Annotated[SessionPrincipal, Depends(get_principal)]
type EmployeePrincipalDep = Annotated[SessionPrincipal, Depends(require_employee)]
type HRPrincipalDep = Annotated[SessionPrincipal, Depends(require_hr)]
