"""
KError — the closed-taxonomy error class raised by every k9o surface
on non-2xx gateway responses or SDK-side validation failures.

Raise on error in Python (snake_case fields preserved
from the wire payload via wire_to_python field translation at the
boundary; `code` stays SCREAMING_SNAKE_CASE constant
casing).

Fields:
  - code: closed-taxonomy string (e.g. `K9O_TIER_CAP_HIT`); unknown
    codes pass through verbatim (open code-space; catalogue is
    centrally curated)
  - message: human-readable explanation
  - context: structured per-code payload (frozen dict; immutable)
  - recommendation: actionable next step (may be None)
  - status: HTTP status the gateway returned (or None for SDK-side
    construct-time errors)
  - request_id: gateway-emitted trace id for downstream correlation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


class KError(Exception):
    """The customer-facing error type raised by k9o surfaces.

    Inherits from Exception Python idiom; catch with
    `except KError as e:` and narrow on `e.code`.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        context: dict[str, Any] | None = None,
        recommendation: str | None = None,
        status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context: Mapping[str, Any] = MappingProxyType(dict(context or {}))
        self.recommendation = recommendation
        self.status = status
        self.request_id = request_id

    def __repr__(self) -> str:
        return (
            f"KError(code={self.code!r}, message={self.message!r}, "
            f"status={self.status!r}, request_id={self.request_id!r})"
        )


@dataclass(frozen=True)
class KErrorWire:
    """Wire-shape sentinel matching the gateway's KError JSON payload."""

    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    recommendation: str | None = None
    request_id: str | None = None


def kerror_from_wire(wire: dict[str, Any], status: int) -> KError:
    """Rehydrate a wire KError payload into a typed KError instance.

    No allow-list — gateway's KError code-space is open-ended and
    curated centrally; preserves whatever code the gateway
    sends. Field-name translation: wire `requestId` (camelCase) →
    Python `request_id` (snake_case) casing rule.
    """
    return KError(
        code=wire["code"],
        message=wire["message"],
        context=wire.get("context") or {},
        recommendation=wire.get("recommendation"),
        status=status,
        request_id=wire.get("requestId") or wire.get("request_id"),
    )
