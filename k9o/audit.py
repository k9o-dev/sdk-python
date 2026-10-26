"""
Project-plane audit log namespace — `client.audit.*`.

Distinct from `client.org.audit_log` (org-plane). Wire mapping:
  - query(event_type=, actor_id=, after=, before=, limit=, cursor=)  GET /@<slug>/audit-log?...

Option names map to the gateway's query parameters (`eventType`, `actorId`, `after`, `before`, `limit`, `cursor`).
`event_type` is a prefix match on the audit-event name (e.g. `data.write.access.insert`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

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

    def query(self, *, event_type: str | None = None, actor_id: str | None = None, after: str | None = None,
              before: str | None = None, limit: int | None = None, cursor: str | None = None) -> Envelope:
        """Query the audit log (reverse-chronological; filters AND-compose).

        `after` / `before` are ISO 8601 bounds (events after / before that instant).
        """
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, "audit-log"),
                       query=_clean({"eventType": event_type, "actorId": actor_id, "after": after,
                                     "before": before, "limit": limit, "cursor": cursor}))

    def tail(self, *, since_minutes: int = 1, limit: int = 100) -> Envelope:
        """Convenience: recent events within a since-window (a single read with `after` set)."""
        slug = _require_project_slug(self._config)
        after = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat()
        return request(self._config, method="GET", path=project_path(slug, "audit-log"),
                       query={"after": after, "limit": limit})
