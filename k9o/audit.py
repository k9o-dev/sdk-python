"""
Project-plane audit log namespace — `client.audit.*`.

Distinct from `client.org.audit_log` (org-plane) and
`client.me.audit_log` (operator-self). Python idiomatic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import project_path


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("audit operations require project_slug bound on the client")
    return config.project_slug


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class AuditNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def query(self, *, since: str | None = None, until: str | None = None, type: str | None = None,
              actor_id: str | None = None, target_kind: str | None = None, target_id: str | None = None,
              limit: int | None = None, cursor: str | None = None) -> Envelope:
        """Query the audit log (reverse-chronological; filters AND-compose)."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, "audit-log"),
                       query=_clean({"since": since, "until": until, "type": type, "actorId": actor_id,
                                     "targetKind": target_kind, "targetId": target_id,
                                     "limit": limit, "cursor": cursor}))

    def tail(self, *, since_minutes: int = 1, limit: int = 100) -> Envelope:
        """Convenience: recent events within a since-window."""
        slug = _require_project_slug(self._config)
        since = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat()
        return request(self._config, method="GET", path=project_path(slug, "audit-log"),
                       query={"since": since, "limit": limit})
