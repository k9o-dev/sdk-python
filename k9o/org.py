"""
Org-plane bound namespace — `client.org.*`.

Singular bound-org namespace (distinct from the `client.orgs` collection): members / groups / smtp / audit_log /
gate (roles + idp_providers) / default_llm. Org-plane routes carry no `@<projectSlug>/` prefix; the org comes from
the host the client is bound to.

Wire mapping:
  - get()                                  GET    /org
  - members.list / invite / remove         GET / POST /members, DELETE /members/<userId>
  - groups.list / get                      GET    /groups, /groups/<groupId>
  - audit_log.query / tail                 GET    /audit-log   (the route reads `type` and `limit`)
  - gate.roles.*                           /role-grants[/<grantId>]
  - gate.idp_providers.*                   /identity-providers[/<idpId>]
  - smtp.set / unset                       PATCH  /org  {smtpConfig}
  - smtp.test                              POST   /org/smtp/test-email
  - default_llm.get / set                  GET / PATCH /default-llm
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


def _q(value: str) -> str:
    return quote(value, safe="")


class _Members:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self, *, user_id: str | None = None, role: str | None = None, acceptance_status: str | None = None,
             status: str | None = None, state: str | None = None) -> Envelope:
        """GET /members. The route is not paged; it filters by userId, role, acceptanceStatus
        ("accepted" | "pending"), status ("active" | "suspended") and state."""
        return request(self._config, method="GET", path=org_path("members"),
                       query=_clean({"userId": user_id, "role": role, "acceptanceStatus": acceptance_status,
                                     "status": status, "state": state}))

    def invite(self, *, email: str, role: str) -> Envelope:
        """POST /members — invite a new org member by email."""
        return request(self._config, method="POST", path=org_path("members"),
                       body={"email": email, "role": role})

    def remove(self, user_id: str) -> Envelope:
        """DELETE /members/<user_id>."""
        return request(self._config, method="DELETE", path=org_path(f"members/{_q(user_id)}"))


class _Groups:
    """Read-only: groups are retired by design, so there is no create or delete."""

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self, *, user_id: str | None = None) -> Envelope:
        """GET /groups; `user_id` narrows to the groups of one user."""
        return request(self._config, method="GET", path=org_path("groups"), query=_clean({"userId": user_id}))

    def get(self, group_id: str) -> Envelope:
        return request(self._config, method="GET", path=org_path(f"groups/{_q(group_id)}"))


class _OrgAuditLog:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def query(self, *, type: str | None = None, limit: int | None = None) -> Envelope:
        """GET /audit-log (org-plane), newest first. The route filters by exact event `type` and caps at `limit`
        (default 100, max 500); it has no time, actor or cursor parameters."""
        return request(self._config, method="GET", path=org_path("audit-log"),
                       query=_clean({"type": type, "limit": limit}))

    def tail(self, *, since_minutes: int = 5, limit: int = 100) -> Envelope:
        """Convenience: the newest events, keeping those whose `createdAt` is within the last `since_minutes`.

        The route has no time filter, so the window is applied here to the `limit` newest rows.
        """
        env = self.query(limit=limit)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

        def recent(row: Any) -> bool:
            stamp = row.get("createdAt") if isinstance(row, dict) else None
            if not isinstance(stamp, str):
                return True
            try:
                return datetime.fromisoformat(stamp.replace("Z", "+00:00")) >= cutoff
            except ValueError:
                return True

        data = [r for r in env.data if recent(r)] if isinstance(env.data, list) else env.data
        return Envelope(data=data, meta=env.meta)


class _GateRoles:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self) -> Envelope:
        """GET /role-grants."""
        return request(self._config, method="GET", path=org_path("role-grants"))

    def grant(self, *, user_id: str, role: str, decision_reason: str | None = None) -> Envelope:
        """POST /role-grants."""
        return request(self._config, method="POST", path=org_path("role-grants"),
                       body=_clean({"userId": user_id, "role": role, "decisionReason": decision_reason}))

    def get(self, grant_id: str) -> Envelope:
        return request(self._config, method="GET", path=org_path(f"role-grants/{_q(grant_id)}"))

    def revoke(self, grant_id: str, *, decision_reason: str | None = None) -> Envelope:
        """DELETE /role-grants/<grant_id> (soft delete; sets revokedAt)."""
        body = _clean({"decisionReason": decision_reason})
        return request(self._config, method="DELETE", path=org_path(f"role-grants/{_q(grant_id)}"),
                       body=body or None)


class _GateIdpProviders:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> Envelope:
        """GET /identity-providers."""
        return request(self._config, method="GET", path=org_path("identity-providers"),
                       query=_clean({"limit": limit, "cursor": cursor}))

    def create(self, *, idp_provider: str, display_name: str, client_id: str, client_secret_ref: str,
               tier_gating: str, redirect_uri: str | None = None, metadata_url: str | None = None,
               attribute_map: dict[str, Any] | None = None, enabled: bool | None = None) -> Envelope:
        """POST /identity-providers. `client_secret_ref` references a stored secret, never the secret itself;
        `tier_gating` is "free_tier_ok" | "ridge_plus"."""
        return request(self._config, method="POST", path=org_path("identity-providers"),
                       body=_clean({"idpProvider": idp_provider, "displayName": display_name,
                                    "clientId": client_id, "clientSecretRef": client_secret_ref,
                                    "tierGating": tier_gating, "redirectUri": redirect_uri,
                                    "metadataUrl": metadata_url, "attributeMap": attribute_map,
                                    "enabled": enabled}))

    def get(self, idp_id: str) -> Envelope:
        return request(self._config, method="GET", path=org_path(f"identity-providers/{_q(idp_id)}"))

    def configure(self, idp_id: str, *, display_name: str | None = None, client_id: str | None = None,
                  client_secret_ref: str | None = None, redirect_uri: str | None = None,
                  metadata_url: str | None = None, attribute_map: dict[str, Any] | None = None,
                  enabled: bool | None = None) -> Envelope:
        """PATCH /identity-providers/<idp_id> — only the fields given are sent."""
        return request(self._config, method="PATCH", path=org_path(f"identity-providers/{_q(idp_id)}"),
                       body=_clean({"displayName": display_name, "clientId": client_id,
                                    "clientSecretRef": client_secret_ref, "redirectUri": redirect_uri,
                                    "metadataUrl": metadata_url, "attributeMap": attribute_map,
                                    "enabled": enabled}))

    def delete(self, idp_id: str) -> Envelope:
        return request(self._config, method="DELETE", path=org_path(f"identity-providers/{_q(idp_id)}"))


class _Gate:
    def __init__(self, config: HttpClientConfig) -> None:
        self.roles = _GateRoles(config)
        self.idp_providers = _GateIdpProviders(config)


class _Smtp:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def set(self, *, host: str, port: int, username: str, password_ref: str, from_address: str,
            from_name: str | None = None) -> Envelope:
        """Set or update the org SMTP config: PATCH /org with `{smtpConfig}`.

        The password is never sent: `password_ref` references the stored SMTP password.
        """
        smtp = _clean({"host": host, "port": port, "username": username, "passwordRef": password_ref,
                       "fromAddress": from_address, "fromName": from_name})
        return request(self._config, method="PATCH", path=org_path("org"), body={"smtpConfig": smtp})

    def test(self, *, to: str, subject: str | None = None) -> Envelope:
        """POST /org/smtp/test-email — send a diagnostic email (5/hour rate limit)."""
        return request(self._config, method="POST", path=org_path("org/smtp/test-email"),
                       body=_clean({"to": to, "subject": subject}))

    def unset(self) -> Envelope:
        """Clear the org-level SMTP config: PATCH /org with `{smtpConfig: null}`."""
        return request(self._config, method="PATCH", path=org_path("org"), body={"smtpConfig": None})


class DefaultLlmNamespace:
    """`client.org.default_llm` (ORG_ADMIN to set)."""

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def get(self) -> Envelope:
        """GET /default-llm — read the org-default LLM model id."""
        return request(self._config, method="GET", path=org_path("default-llm"))

    def set(self, *, model_id: str) -> Envelope:
        """PATCH /default-llm with `{modelId}` (ORG_ADMIN or ORG_OWNER; tier-gated)."""
        return request(self._config, method="PATCH", path=org_path("default-llm"), body={"modelId": model_id})


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
        """GET /org — read the current org (slug + name + status + settings)."""
        return request(self._config, method="GET", path=org_path("org"))
