"""
Envelope + meta namespace types.

Python idiomatic shape: `response.data` + `response.meta.cursor.next`
accessor sugar via nested dataclasses. Field names match the per-language
casing rule — Python snake_case at the SDK boundary; the wire
shape stays camelCase invariant.

The HTTP client deserialises camelCase wire keys to snake_case Python
attributes at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class MetaCursor:
    """Pagination cursor."""

    next: str | None = None
    total_count: int | None = None


@dataclass
class MetaSubscription:
    """Subscription delivery metadata."""

    is_initial: bool = False


@dataclass
class MetaIdempotency:
    """Idempotency replay flag."""

    replayed: bool = False


@dataclass
class MetaWarning:
    """Non-fatal warning."""

    code: str
    message: str


@dataclass
class MetaTiming:
    """Wall-clock timing."""

    total_ms: int


@dataclass
class MetaContext:
    """Request-correlation metadata."""

    request_id: str


@dataclass
class Meta:
    """Structured meta accessor sugar.

    Built lazily from the wire `meta` payload at the HTTP boundary;
    populated only when the gateway sends the corresponding sub-namespace.
    Attribute access on unset sub-namespaces returns None.
    """

    cursor: MetaCursor | None = None
    subscription: MetaSubscription | None = None
    idempotency: MetaIdempotency | None = None
    warnings: list[MetaWarning] = field(default_factory=list)
    cost: dict[str, Any] = field(default_factory=dict)
    timing: MetaTiming | None = None
    context: MetaContext | None = None
    # Raw wire payload preserved for forward-compat access to fields
    # the typed accessor doesn't yet know about.
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Envelope(Generic[T]):
    """Standard envelope. Returned by every k9o surface on success."""

    data: T
    meta: Meta = field(default_factory=Meta)


def meta_from_wire(wire: dict[str, Any] | None) -> Meta:
    """Build a typed `Meta` from the wire dict payload.

    Wire fields use camelCase invariant; translated to
    snake_case attributes here. Unknown wire fields preserved on `raw`.
    """
    if wire is None:
        return Meta()
    m = Meta(raw=dict(wire))

    cursor_w = wire.get("cursor")
    if isinstance(cursor_w, dict):
        m.cursor = MetaCursor(
            next=cursor_w.get("next"),
            total_count=cursor_w.get("totalCount"),
        )

    sub_w = wire.get("subscription")
    if isinstance(sub_w, dict):
        m.subscription = MetaSubscription(is_initial=bool(sub_w.get("isInitial", False)))

    idem_w = wire.get("idempotency")
    if isinstance(idem_w, dict):
        m.idempotency = MetaIdempotency(replayed=bool(idem_w.get("replayed", False)))

    warnings_w = wire.get("warnings")
    if isinstance(warnings_w, list):
        m.warnings = [
            MetaWarning(code=w.get("code", ""), message=w.get("message", ""))
            for w in warnings_w
            if isinstance(w, dict)
        ]

    cost_w = wire.get("cost")
    if isinstance(cost_w, dict):
        # cost is a sparse, structured open-map (string -> open value),
        # e.g. {"egress": {"gb": 4.55e-07, "zone": "intra-region"}}. Pass it
        # through verbatim so structured dimensions (egress, vaultOps, ...)
        # survive; coercing to float here silently dropped object-valued
        # dimensions.
        m.cost = dict(cost_w)

    timing_w = wire.get("timing")
    if isinstance(timing_w, dict) and "totalMs" in timing_w:
        m.timing = MetaTiming(total_ms=int(timing_w["totalMs"]))

    context_w = wire.get("context")
    if isinstance(context_w, dict) and "requestId" in context_w:
        m.context = MetaContext(request_id=context_w["requestId"])

    return m
