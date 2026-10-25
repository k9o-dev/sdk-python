"""
k9o — Kilimanjaro platform SDK (Python; idiomatic).

Canonical usage:

    from k9o import create_client, KError

    k9o = create_client(
        base_url="https://acme.api.k9o.io",
        api_key=os.environ["K9O_API_KEY"],
        org_slug="acme",
        project_slug="member-portal",
    )

    try:
        response = k9o.from_("posts").select().limit(10).execute()
        for row in response.data:
            print(row)
        session = k9o.gate.sign_in(email="user@example.com", password="…")
        print("signed in:", session.data["user"]["id"])
    except KError as e:
        print(f"[{e.code}] {e.message}: {e.recommendation}")

Architectural posture: hand-authored idiomatic SDK against the platform API specification
+ services/gateway/openapi.json contract source; replaces the prior
OpenAPI-generator output (`k9o_gate` raw client) with idiomatic
shape (snake_case methods + raise KError + envelope dataclass with
typed meta accessor sugar + data DSL).
"""

from __future__ import annotations

from .audit import AuditNamespace
from .client import K9oClient, create_client
from .compute import ComputeNamespace, LlmsNamespace, LLM_MODEL_IDS, LLM_ERROR_CODES
from .data import FromBuilder, SelectBuilder, UpdateBuilder, DeleteBuilder
from .functions import FunctionsNamespace
from .kibo_vault import KiboNamespace, SecretsNamespace, VaultNamespace
from .me import MeNamespace
from .migrations import MigrationsNamespace
from .org import OrgNamespace
from .orgs import OrgsNamespace
from .policies import PoliciesNamespace
from .realtime import RealtimeNamespace, realtime_topic, REALTIME_TOPIC_FAMILIES
from .studio import (
    StudioNamespace,
    WorkflowsNamespace,
    DashboardsNamespace,
    WORKFLOW_ERROR_CODES,
    DASHBOARD_ERROR_CODES,
    WORKFLOW_TRIGGER_TYPES,
    WORKFLOW_ACTION_TYPES,
    WIDGET_TYPES,
)
from .envelope import (
    Envelope,
    Meta,
    MetaContext,
    MetaCursor,
    MetaIdempotency,
    MetaSubscription,
    MetaTiming,
    MetaWarning,
)
from .errors import KError, KErrorWire, kerror_from_wire
from .gate import GateNamespace
from .http import HttpClientConfig, RetryConfig
from .projects import Project, ProjectsNamespace
from .url_grammar import (
    org_path,
    platform_path,
    project_path,
    resolve_base_url,
    validate_base_url,
    validate_slug,
)

__version__ = "1.1.1"

__all__ = [
    "__version__",
    # Factory + client
    "create_client",
    "K9oClient",
    # Error
    "KError",
    "KErrorWire",
    "kerror_from_wire",
    # Envelope + meta
    "Envelope",
    "Meta",
    "MetaContext",
    "MetaCursor",
    "MetaIdempotency",
    "MetaSubscription",
    "MetaTiming",
    "MetaWarning",
    # Data DSL
    "FromBuilder",
    "SelectBuilder",
    "UpdateBuilder",
    "DeleteBuilder",
    # Namespaces
    "ProjectsNamespace",
    "Project",
    "GateNamespace",
    "StudioNamespace",
    "WorkflowsNamespace",
    "DashboardsNamespace",
    "ComputeNamespace",
    "LlmsNamespace",
    "RealtimeNamespace",
    "realtime_topic",
    "OrgNamespace",
    "OrgsNamespace",
    "MigrationsNamespace",
    "FunctionsNamespace",
    "PoliciesNamespace",
    "AuditNamespace",
    "MeNamespace",
    "KiboNamespace",
    "VaultNamespace",
    "SecretsNamespace",
    # P6 closed enums + error-code maps
    "WORKFLOW_ERROR_CODES",
    "DASHBOARD_ERROR_CODES",
    "LLM_ERROR_CODES",
    "WORKFLOW_TRIGGER_TYPES",
    "WORKFLOW_ACTION_TYPES",
    "WIDGET_TYPES",
    "LLM_MODEL_IDS",
    "REALTIME_TOPIC_FAMILIES",
    # URL grammar
    "validate_base_url",
    "resolve_base_url",
    "validate_slug",
    "project_path",
    "org_path",
    "platform_path",
    # HTTP config (advanced use)
    "HttpClientConfig",
    "RetryConfig",
]
