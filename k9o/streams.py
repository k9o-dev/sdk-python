"""
User data streams namespace: `client.streams.*`.

Control plane and data plane of a project's user streams, under `/@<slug>/data-streams/user`:
  - create(display_name, max_bytes, retention_seconds=)   POST   .../user
  - list()                                                GET    .../user
  - get(slug)                                             GET    .../user/<slug>
  - delete(slug)                                          DELETE .../user/<slug>
  - publish(slug, data, subject=)                         POST   .../user/<slug>/publish
  - replay(slug, from_sequence=, until_sequence=, limit=) POST   .../user/<slug>/replay
  - subscribe(slug, from_sequence=)                       GET    .../user/<slug>/subscribe  (SSE, async iterator)

Publish needs project admin; subscribe and replay need admin or auditor. While the stream data plane is not
available the gateway answers K9O_STREAM_UNAVAILABLE (503); a bad subject answers K9O_STREAM_INVALID. Both raise KError.

`subscribe()` tails live events. The gateway bounds each connection and closes it; the iterator reconnects from the
last sequence it yielded, so no event is repeated or skipped. Leave the loop (or close the generator) to stop.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request, stream_sse_async
from .url_grammar import project_path

# Pause before reconnecting after the server closes a connection.
_RECONNECT_DELAY_S = 0.25


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("streams operations require project_slug bound on the client")
    return config.project_slug


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _stream_path(config: HttpClientConfig, stream_slug: str = "", suffix: str = "") -> str:
    path = "data-streams/user"
    if stream_slug:
        path += "/" + quote(stream_slug, safe="")
    if suffix:
        path += "/" + suffix
    return project_path(_require_project_slug(config), path)


class StreamsNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def create(self, display_name: str, max_bytes: int, retention_seconds: int | None = None) -> Envelope:
        """Create a stream. `max_bytes` is the storage ceiling; the slug is derived from `display_name`."""
        return request(self._config, method="POST", path=_stream_path(self._config),
                       body=_clean({"displayName": display_name, "maxBytes": max_bytes,
                                    "retentionSeconds": retention_seconds}))

    def list(self) -> Envelope:
        """List the project's active user streams."""
        return request(self._config, method="GET", path=_stream_path(self._config))

    def get(self, slug: str) -> Envelope:
        """Read one stream by slug."""
        return request(self._config, method="GET", path=_stream_path(self._config, slug))

    def delete(self, slug: str) -> Envelope:
        """Retire a stream."""
        return request(self._config, method="DELETE", path=_stream_path(self._config, slug))

    def publish(self, slug: str, data: Any, subject: str | None = None) -> Envelope:
        """Append an event. `data` is any JSON value; `subject` is an optional dot-separated routing suffix."""
        return request(self._config, method="POST", path=_stream_path(self._config, slug, "publish"),
                       body={"data": data} if subject is None else {"data": data, "subject": subject})

    def replay(self, slug: str, from_sequence: int | str | None = None, until_sequence: int | str | None = None,
               limit: int | None = None) -> Envelope:
        """Read a bounded range of past events: `data.events`, `data.nextCursor`, `data.hasMore`."""
        return request(self._config, method="POST", path=_stream_path(self._config, slug, "replay"),
                       body=_clean({"fromSequence": from_sequence, "untilSequence": until_sequence, "limit": limit}))

    async def subscribe(self, slug: str, from_sequence: int | str | None = None) -> AsyncIterator[dict[str, Any]]:
        """Tail a stream; yields events `{sequence, subject, data, publishedAt}` and reconnects after the server closes."""
        path = _stream_path(self._config, slug, "subscribe")
        cursor = from_sequence
        while True:
            query = {"fromSequence": cursor} if cursor is not None else None
            async for event in stream_sse_async(self._config, method="GET", path=path, query=query):
                if isinstance(event, dict) and "sequence" in event:
                    cursor = event["sequence"]
                    yield event
            await asyncio.sleep(_RECONNECT_DELAY_S)
