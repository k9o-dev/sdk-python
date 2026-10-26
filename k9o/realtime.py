"""
Realtime Subscriptions namespace — `client.realtime.*`.

`subscribe()` returns an async iterator — `async for event in client.realtime.subscribe(topic): ...` — over SSE:
`GET /@<slug>/realtime/subscribe?topic=<t>&filter=<json>`. The gateway serves no WebSocket upgrade and no durable
replay, so neither is offered; after an `event: resync` frame, re-read current state from the data plane and
resubscribe.

`filter` and RLS compose (filter narrows, RLS gates). Surfaces K9O_INVALID_FILTER, K9O_SUBSCRIPTION_LIMIT_EXCEEDED and
K9O_TIER_FEATURE_GATED.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from .http import HttpClientConfig, stream_sse_async
from .url_grammar import project_path

# The 6 closed topic families.
REALTIME_TOPIC_FAMILIES = (
    "collections",
    "studio.workflows.runs",
    "studio.queries.executed",
    "studio.dashboards.refresh",
    "forge.functions.invocations",
    "audit.org",
)


class realtime_topic:
    """Typed builders for the 6 topic families."""

    @staticmethod
    def collection(collection: str) -> str:
        return f"collections.{collection}.*"

    @staticmethod
    def workflow_runs() -> str:
        return "studio.workflows.runs.*"

    @staticmethod
    def query_executed(query_id: str) -> str:
        return f"studio.queries.executed.{query_id}"

    @staticmethod
    def dashboard_refresh(dashboard_id: str) -> str:
        return f"studio.dashboards.refresh.{dashboard_id}"

    @staticmethod
    def function_invocations(function_id: str) -> str:
        return f"forge.functions.invocations.{function_id}"

    @staticmethod
    def audit_org(event_family: str) -> str:
        return f"audit.org.{event_family}"


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("realtime operations require project_slug bound on the client")
    return config.project_slug


class RealtimeNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    async def subscribe(self, topic: str, *, filter: dict[str, Any] | None = None) -> AsyncIterator[Any]:
        """Subscribe to a topic over SSE; yields the parsed event dicts."""
        slug = _require_project_slug(self._config)
        query: dict[str, Any] = {"topic": topic}
        if filter is not None:
            query["filter"] = json.dumps(filter)
        async for event in stream_sse_async(
            self._config,
            method="GET",
            path=project_path(slug, "realtime/subscribe"),
            query=query,
        ):
            yield event
