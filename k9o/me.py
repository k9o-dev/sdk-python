"""
Operator-self namespace — `client.me.*`.

Cross-org; no tenant context required (org-plane routes under /me).
Sub-namespaces: profile / sessions / api_tokens / notifications /
audit_log / data_export. Python idiomatic.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import org_path


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class _Profile:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def get(self) -> Envelope:
        return request(self._config, method="GET", path=org_path("me"))

    def update(self, *, display_name: str | None = None) -> Envelope:
        return request(self._config, method="PATCH", path=org_path("me"),
                       body={"displayName": display_name})


class _Sessions:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self) -> Envelope:
        return request(self._config, method="GET", path=org_path("me/sessions"))

    def revoke(self, session_id: str) -> Envelope:
        return request(self._config, method="DELETE", path=org_path(f"me/sessions/{quote(session_id)}"))

    def revoke_all(self) -> Envelope:
        return request(self._config, method="DELETE", path=org_path("me/sessions"))


class _ApiTokens:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self) -> Envelope:
        return request(self._config, method="GET", path=org_path("me/api-tokens"))

    def create(self, *, name: str, expires_in_days: int | None = None, scope: str | None = None) -> Envelope:
        return request(self._config, method="POST", path=org_path("me/api-tokens"),
                       body=_clean({"name": name, "expiresInDays": expires_in_days, "scope": scope}))

    def delete(self, token_id: str) -> Envelope:
        return request(self._config, method="DELETE", path=org_path(f"me/api-tokens/{quote(token_id)}"))


class _Notifications:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self, *, unread_only: bool | None = None, limit: int | None = None, cursor: str | None = None) -> Envelope:
        return request(self._config, method="GET", path=org_path("me/notifications"),
                       query=_clean({"unreadOnly": unread_only, "limit": limit, "cursor": cursor}))

    def mark_read(self, notification_id: str) -> Envelope:
        return request(self._config, method="PATCH",
                       path=org_path(f"me/notifications/{quote(notification_id)}"), body={"read": True})

    def mark_all_read(self) -> Envelope:
        return request(self._config, method="PATCH", path=org_path("me/notifications"), body={"read": True})


class _MeAuditLog:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def query(self, *, since: str | None = None, until: str | None = None, type: str | None = None,
              limit: int | None = None, cursor: str | None = None) -> Envelope:
        return request(self._config, method="GET", path=org_path("me/audit-log"),
                       query=_clean({"since": since, "until": until, "type": type,
                                     "limit": limit, "cursor": cursor}))


class _DataExport:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def request(self, *, format: str = "json") -> Envelope:
        return request(self._config, method="POST", path=org_path("me/data-export"), body={"format": format})

    def status(self, job_id: str) -> Envelope:
        return request(self._config, method="GET", path=org_path(f"me/data-export/{quote(job_id)}"))


class MeNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self.profile = _Profile(config)
        self.sessions = _Sessions(config)
        self.api_tokens = _ApiTokens(config)
        self.notifications = _Notifications(config)
        self.audit_log = _MeAuditLog(config)
        self.data_export = _DataExport(config)
