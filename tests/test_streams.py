"""client.streams: exact wire shape, SSE resume across server-closed connections, error mapping."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qsl

import httpx
import pytest

from k9o import KError, create_client
from k9o import streams as streams_mod

BASE = "https://acme.api.k9o.io"


def _client(handler):
    c = create_client(base_url=BASE, project_slug="portal", api_key="k")
    c.config.transport = httpx.MockTransport(handler)
    return c


def _ok(data):
    return httpx.Response(200, json={"data": data, "meta": {}})


def _recording():
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        return _ok({})

    return _client(handler), seen


def _body(req):
    return json.loads(req.content) if req.content else None


def _sent(call):
    c, seen = _recording()
    call(c)
    reqs = [r for r in seen if r.method != "HEAD"]
    assert len(reqs) == 1
    return reqs[0]


CASES = [
    (lambda c: c.streams.create("Orders feed", 1073741824), "POST", "/@portal/data-streams/user",
     {"displayName": "Orders feed", "maxBytes": 1073741824}),
    (lambda c: c.streams.create("Orders feed", 1073741824, retention_seconds=7200), "POST",
     "/@portal/data-streams/user", {"displayName": "Orders feed", "maxBytes": 1073741824, "retentionSeconds": 7200}),
    (lambda c: c.streams.list(), "GET", "/@portal/data-streams/user", None),
    (lambda c: c.streams.get("orders-feed"), "GET", "/@portal/data-streams/user/orders-feed", None),
    (lambda c: c.streams.delete("orders-feed"), "DELETE", "/@portal/data-streams/user/orders-feed", None),
    (lambda c: c.streams.publish("orders-feed", {"id": 1}), "POST",
     "/@portal/data-streams/user/orders-feed/publish", {"data": {"id": 1}}),
    (lambda c: c.streams.publish("orders-feed", [1, 2], subject="eu.new"), "POST",
     "/@portal/data-streams/user/orders-feed/publish", {"data": [1, 2], "subject": "eu.new"}),
    (lambda c: c.streams.publish("orders-feed", None), "POST",
     "/@portal/data-streams/user/orders-feed/publish", {"data": None}),
    (lambda c: c.streams.replay("orders-feed"), "POST", "/@portal/data-streams/user/orders-feed/replay", {}),
    (lambda c: c.streams.replay("orders-feed", from_sequence=5, until_sequence=9, limit=3), "POST",
     "/@portal/data-streams/user/orders-feed/replay", {"fromSequence": 5, "untilSequence": 9, "limit": 3}),
]


@pytest.mark.parametrize("call,method,path,body", CASES)
def test_wire_shape(call, method, path, body):
    req = _sent(call)
    assert req.method == method and req.url.path == path
    assert _body(req) == body


def test_returns_envelope():
    c = _client(lambda req: _ok({"events": [], "nextCursor": None, "hasMore": False}))
    assert c.streams.replay("s").data["hasMore"] is False


def test_requires_project_slug():
    c = create_client(base_url=BASE, api_key="k")
    with pytest.raises(ValueError):
        c.streams.list()


@pytest.mark.parametrize("code,status", [("K9O_STREAM_UNAVAILABLE", 503), ("K9O_STREAM_INVALID", 400)])
def test_stream_errors_are_typed(code, status):
    def handler(req):
        return httpx.Response(status, json={"code": code, "message": "nope", "context": {}})

    c = _client(handler)
    c.config.retry_config = None
    with pytest.raises(KError) as e:
        c.streams.publish("s", {"a": 1}, subject="Bad Subject")
    assert e.value.code == code and e.value.status == status


def _frame(seq, data):
    ev = {"sequence": seq, "subject": "k9o.user.x._", "data": data, "publishedAt": "2026-10-26T00:00:00Z"}
    return f"id: {seq}\ndata: {json.dumps(ev)}\n\n"


def _sse(text):
    return httpx.Response(200, content=text.encode(), headers={"content-type": "text/event-stream"})


def test_subscribe_resumes_from_last_sequence_across_closed_connections(monkeypatch):
    monkeypatch.setattr(streams_mod, "_RECONNECT_DELAY_S", 0)
    seen: list[httpx.Request] = []
    bodies = ["retry: 1000\n:ok\n\n" + _frame("1", {"n": 1}) + _frame("2", {"n": 2}),
              "retry: 1000\n:ok\n\n" + _frame("3", {"n": 3}),
              "retry: 1000\n:ok\n\n"]

    def handler(req):
        if req.method == "HEAD":
            return httpx.Response(200)
        seen.append(req)
        return _sse(bodies[min(len(seen) - 1, len(bodies) - 1)])

    c = _client(handler)

    async def go():
        out = []
        async for ev in c.streams.subscribe("orders-feed"):
            out.append(ev)
            if len(out) == 3:
                break
        return out

    events = asyncio.run(go())
    assert [e["sequence"] for e in events] == ["1", "2", "3"]
    assert [e["data"] for e in events] == [{"n": 1}, {"n": 2}, {"n": 3}]
    reqs = seen
    assert all(r.method == "GET" and r.url.path == "/@portal/data-streams/user/orders-feed/subscribe" for r in reqs)
    assert [dict(parse_qsl(r.url.query.decode())) for r in reqs] == [{}, {"fromSequence": "2"}]


def test_subscribe_starts_at_from_sequence_and_keeps_cursor_when_connection_is_empty(monkeypatch):
    monkeypatch.setattr(streams_mod, "_RECONNECT_DELAY_S", 0)
    seen: list[httpx.Request] = []

    def handler(req):
        if req.method == "HEAD":
            return httpx.Response(200)
        seen.append(req)
        n = len(seen)
        return _sse(_frame("8", "x") if n == 1 else ":ok\n\n" if n == 2 else _frame("9", "y"))

    c = _client(handler)

    async def go():
        out = []
        async for ev in c.streams.subscribe("s", from_sequence=7):
            out.append(ev["sequence"])
            if len(out) == 2:
                break
        return out

    assert asyncio.run(go()) == ["8", "9"]
    assert [dict(parse_qsl(r.url.query.decode())) for r in seen] == [
        {"fromSequence": "7"}, {"fromSequence": "8"}, {"fromSequence": "8"}]


def test_subscribe_503_raises_typed_error():
    def handler(req):
        return httpx.Response(503, json={"code": "K9O_STREAM_UNAVAILABLE", "message": "no plane", "context": {}})

    c = _client(handler)

    async def go():
        async for _ in c.streams.subscribe("s"):
            pass

    with pytest.raises(KError) as e:
        asyncio.run(go())
    assert e.value.code == "K9O_STREAM_UNAVAILABLE" and e.value.status == 503
