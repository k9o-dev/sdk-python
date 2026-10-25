"""
Realtime Subscriptions namespace — `client.realtime.*`
(ALL-LIVE primitive).

Python idiomatic shape: `subscribe()` returns an async
iterator — `async for event in client.realtime.subscribe(topic): ...`.
Per `feedback_sdk_abstracted_primitive_default_to_richer_interaction.md`
+ the SDK picks the transport; SPLIT (polling) is the
internal fallback, not a consumer choice. The httpx-based Python SDK
uses SSE as the primary transport (no stdlib WebSocket) with a poll
fallback; the consumer's `async for` is transport-agnostic.

`replay()` is the one-shot historical catch-up (sync; returns Envelope).
Reuses K9O_INVALID_FILTER / K9O_SUBSCRIPTION_LIMIT_EXCEEDED /
K9O_TIER_FEATURE_GATED (no new codes).
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from urllib.parse import quote

from .envelope import Envelope
from .errors import KError
from .http import HttpClientConfig, request, request_async, stream_sse_async
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

    async def subscribe(
        self,
        topic: str,
        *,
        filter: dict[str, Any] | None = None,
        transport: str = "sse",
        poll_interval_s: float = 2.0,
    ) -> AsyncIterator[Any]:
        """Subscribe to a topic; yields RealtimeEvent dicts.

        transport: "sse" (default) or "poll". WebSocket is omitted in the
        httpx-based Python SDK (no stdlib client); SSE is the richest
        portable transport.
        """
        slug = _require_project_slug(self._config)
        if transport == "poll":
            async for event in self._poll(slug, topic, filter, poll_interval_s):
                yield event
            return
        query: dict[str, Any] = {"topic": topic}
        if filter is not None:
            import json

            query["filter"] = json.dumps(filter)
        async for event in stream_sse_async(
            self._config,
            method="GET",
            path=project_path(slug, "realtime/subscribe"),
            query=query,
        ):
            yield event

    async def _poll(self, slug: str, topic: str, filter: dict[str, Any] | None, interval_s: float) -> AsyncIterator[Any]:
        cursor = 0
        while True:
            env = await request_async(
                self._config,
                method="POST",
                path=project_path(slug, "realtime/replay"),
                body={"topic": topic, "filter": filter, "fromSequence": cursor},
            )
            for event in env.data or []:
                seq = event.get("sequence", cursor) if isinstance(event, dict) else cursor
                cursor = max(cursor, seq + 1)
                yield event
            await asyncio.sleep(interval_s)

    def replay(
        self,
        *,
        topic: str,
        from_sequence: int,
        filter: dict[str, Any] | None = None,
        until_sequence: int | None = None,
        limit: int | None = None,
    ) -> Envelope:
        """One-shot historical replay (capped 10k server-side)."""
        slug = _require_project_slug(self._config)
        if not isinstance(from_sequence, int) or from_sequence < 0:
            raise KError(
                code="K9O_INVALID_FILTER",
                message="replay from_sequence must be a non-negative integer",
                context={"fromSequence": from_sequence},
                recommendation="Pass the highest sequence number you have already observed (or 0 to replay from the start).",
            )
        body: dict[str, Any] = {"topic": topic, "fromSequence": from_sequence}
        if filter is not None:
            body["filter"] = filter
        if until_sequence is not None:
            body["untilSequence"] = until_sequence
        if limit is not None:
            body["limit"] = limit
        return request(self._config, method="POST", path=project_path(slug, "realtime/replay"), body=body)
