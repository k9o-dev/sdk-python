"""
Org-plane bound namespace — `client.org.*`.

Singular bound-org namespace (distinct from `client.orgs` collection):
members / groups / smtp / audit_log / gate (roles + idp_providers) +
default_llm. Org-plane URL grammar routes against the
`<orgSlug>.api.k9o.io/` subdomain without the `@<projectSlug>/` prefix.
Python idiomatic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import org_path


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class _Members:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self, *, limit: int | None = None, cursor: str | None = None, status: str | None = None) -> Envelope:
        return request(self._config, method="GET", path=org_path("members"),
                       query=_clean({"limit": limit, "cursor": cursor, "status": status}))

    def invite(self, *, email: str, role: str) -> Envelope:
        return request(self._config, method="POST", path=org_path("members"),
                       body={"email": email, "role": role})

    def get(self, user_id: str) -> Envelope:
        return request(self._config, method="GET", path=org_path(f"members/{quote(user_id)}"))

    def remove(self, user_id: str) -> Envelope:
        return request(self._config, method="DELETE", path=org_path(f"members/{quote(user_id)}"))


class _Groups:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> Envelope:
        return request(self._config, method="GET", path=org_path("groups"),
                       query=_clean({"limit": limit, "cursor": cursor}))

    def create(self, *, name: str) -> Envelope:
        return request(self._config, method="POST", path=org_path("groups"), body={"name": name})

    def get(self, group_id: str) -> Envelope:
        return request(self._config, method="GET", path=org_path(f"groups/{quote(group_id)}"))

    def delete(self, group_id: str) -> Envelope:
        return request(self._config, method="DELETE", path=org_path(f"groups/{quote(group_id)}"))


class _OrgAuditLog:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def query(self, *, since: str | None = None, until: str | None = None, type: str | None = None,
              actor_id: str | None = None, target_kind: str | None = None, target_id: str | None = None,
              limit: int | None = None, cursor: str | None = None) -> Envelope:
        return request(self._config, method="GET", path=org_path("audit-log"),
                       query=_clean({"since": since, "until": until, "type": type, "actorId": actor_id,
                                     "targetKind": target_kind, "targetId": target_id,
                                     "limit": limit, "cursor": cursor}))

    def tail(self, *, since_minutes: int = 5, limit: int = 100) -> Envelope:
        since = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat()
        return request(self._config, method="GET", path=org_path("audit-log"),
                       query={"since": since, "limit": limit})


class _GateRoles:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self, *, user_id: str | None = None, role: str | None = None, include_revoked: bool | None = None) -> Envelope:
        return request(self._config, method="GET", path=org_path("org-role-grants"),
                       query=_clean({"userId": user_id, "role": role, "includeRevoked": include_revoked}))

    def grant(self, *, user_id: str, role: str) -> Envelope:
        return request(self._config, method="POST", path=org_path("org-role-grants"),
                       body={"userId": user_id, "role": role})

    def get(self, grant_id: str) -> Envelope:
        return request(self._config, method="GET", path=org_path(f"org-role-grants/{quote(grant_id)}"))

    def revoke(self, grant_id: str) -> Envelope:
        return request(self._config, method="DELETE", path=org_path(f"org-role-grants/{quote(grant_id)}"))


class _GateIdpProviders:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self) -> Envelope:
        return request(self._config, method="GET", path=org_path("idp-providers"))

    def create(self, *, name: str, kind: str, config: dict[str, Any]) -> Envelope:
        return request(self._config, method="POST", path=org_path("idp-providers"),
                       body={"name": name, "kind": kind, "config": config})

    def get(self, idp_id: str) -> Envelope:
        return request(self._config, method="GET", path=org_path(f"idp-providers/{quote(idp_id)}"))

    def configure(self, idp_id: str, *, name: str | None = None, enabled: bool | None = None,
                  config: dict[str, Any] | None = None) -> Envelope:
        return request(self._config, method="PATCH", path=org_path(f"idp-providers/{quote(idp_id)}"),
                       body=_clean({"name": name, "enabled": enabled, "config": config}))

    def delete(self, idp_id: str) -> Envelope:
        return request(self._config, method="DELETE", path=org_path(f"idp-providers/{quote(idp_id)}"))


class _Gate:
    def __init__(self, config: HttpClientConfig) -> None:
        self.roles = _GateRoles(config)
        self.idp_providers = _GateIdpProviders(config)


class _Smtp:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def get(self) -> Envelope:
        """Read current SMTP config (None when no org-level SMTP configured)."""
        return request(self._config, method="GET", path=org_path("org/smtp"))

    def set(self, *, host: str, port: int, username: str, password: str, from_email: str,
            from_name: str, encryption: str, reply_to_email: str | None = None) -> Envelope:
        """Set or update SMTP. Password routes through Kibo enclave."""
        smtp = _clean({"host": host, "port": port, "username": username, "password": password,
                       "fromEmail": from_email, "fromName": from_name, "encryption": encryption,
                       "replyToEmail": reply_to_email})
        return request(self._config, method="PATCH", path=org_path("org"), body={"smtpConfig": smtp})

    def test(self, *, to: str, from_override: str | None = None) -> Envelope:
        return request(self._config, method="POST", path=org_path("org/smtp/test-email"),
                       body=_clean({"to": to, "fromOverride": from_override}))

    def unset(self) -> Envelope:
        return request(self._config, method="PATCH", path=org_path("org"), body={"smtpConfig": None})


class DefaultLlmNamespace:
    """`client.org.default_llm` (ORG_ADMIN)."""

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def get(self) -> Envelope:
        """Read the org-default LLM model id (None when unset → gateway defaults to mistral-7b)."""
        return request(self._config, method="GET", path=org_path("org/default-llm"))

    def set(self, *, model_id: str) -> Envelope:
        """Set the org-default LLM (ORG_ADMIN; tier-gated)."""
        return request(self._config, method="PATCH", path=org_path("org/default-llm"), body={"modelId": model_id})


class OrgNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self.members = _Members(config)
        self.groups = _Groups(config)
        self.audit_log = _OrgAuditLog(config)
        self.gate = _Gate(config)
        self.smtp = _Smtp(config)
        self.default_llm = DefaultLlmNamespace(config)
        self._config = config

    def get(self) -> Envelope:
        """Read the current org (slug + name + status + settings)."""
        return request(self._config, method="GET", path=org_path("org"))
