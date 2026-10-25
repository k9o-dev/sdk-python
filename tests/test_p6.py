"""
Tests for P6 surface families in the Python SDK:
  - client.studio.workflows.*
  - client.studio.dashboards.*
  - client.compute.llms.* + client.org.default_llm
  - client.realtime.subscribe() + replay()

Async surfaces (invoke_stream, subscribe) are driven via asyncio.run to
avoid an asyncio test-runner dependency.
"""

import asyncio
import json

import httpx
import pytest

from k9o import KError, create_client, realtime_topic


def _client(handler, **kw):
    c = create_client(base_url="https://acme.api.k9o.io", project_slug="portal", **kw)
    c._config.transport = httpx.MockTransport(handler)
    return c


def _ok(data):
    def handler(request: httpx.Request) -> httpx.Response:
        handler.url = str(request.url)
        handler.method = request.method
        handler.body = request.content.decode() if request.content else ""
        return httpx.Response(200, json={"data": data, "meta": {}})

    handler.url = handler.method = handler.body = None
    return handler


class TestStudioWorkflows:
    def test_list_and_filters(self):
        h = _ok([])
        c = _client(h)
        c.studio.workflows.list(status="active", trigger_type="manual", limit=10)
        assert h.method == "GET"
        assert "https://acme.api.k9o.io/@portal/workflows" in h.url
        assert "status=active" in h.url and "triggerType=manual" in h.url

    def test_create_read_update_delete(self):
        h = _ok({})
        c = _client(h)
        c.studio.workflows.create({"name": "onboard", "triggerType": "manual", "triggerConfig": {}, "actions": []})
        assert h.method == "POST" and h.url == "https://acme.api.k9o.io/@portal/workflows"
        c.studio.workflows.read("wfl_x")
        assert h.url == "https://acme.api.k9o.io/@portal/workflows/wfl_x"
        c.studio.workflows.update("wfl_x", {"status": "archived"})
        assert h.method == "PATCH"
        c.studio.workflows.delete("wfl_x")
        assert h.method == "DELETE"

    def test_trigger_and_runs(self):
        h = _ok({})
        c = _client(h)
        c.studio.workflows.trigger("wfl_x", {"foo": "bar"})
        assert h.method == "POST" and h.url == "https://acme.api.k9o.io/@portal/workflows/wfl_x/runs"
        assert json.loads(h.body) == {"foo": "bar"}
        c.studio.workflows.runs.list("wfl_x", status="running")
        assert "workflows/wfl_x/runs" in h.url and "status=running" in h.url
        c.studio.workflows.runs.read("wfl_x", "wfr_y")
        assert h.url == "https://acme.api.k9o.io/@portal/workflows/wfl_x/runs/wfr_y"
        c.studio.workflows.runs.cancel("wfl_x", "wfr_y")
        assert h.url == "https://acme.api.k9o.io/@portal/workflows/wfl_x/runs/wfr_y/cancel"


class TestStudioDashboards:
    def test_crud_pin_unpin_data(self):
        h = _ok({})
        c = _client(h)
        c.studio.dashboards.list()
        assert h.url == "https://acme.api.k9o.io/@portal/dashboards"
        c.studio.dashboards.create({"name": "ops"})
        assert h.method == "POST"
        c.studio.dashboards.pin("dsh_x")
        assert h.url == "https://acme.api.k9o.io/@portal/dashboards/dsh_x/pin"
        c.studio.dashboards.unpin("dsh_x")
        assert h.url == "https://acme.api.k9o.io/@portal/dashboards/dsh_x/unpin"


class TestComputeLlms:
    def test_list_read_invoke(self):
        h = _ok({"completion": "hi", "tokensUsed": 2, "latencyMs": 9})
        c = _client(h)
        c.compute.llms.list(modality="embeddings")
        assert "compute/llms" in h.url and "modality=embeddings" in h.url
        c.compute.llms.read("gpt-4o")
        assert h.url == "https://acme.api.k9o.io/@portal/compute/llms/gpt-4o"
        env = c.compute.llms.invoke("mistral-7b", prompt="hello", params={"maxTokens": 16})
        assert h.method == "POST" and h.url == "https://acme.api.k9o.io/@portal/compute/llms/mistral-7b/invoke"
        assert json.loads(h.body)["prompt"] == "hello"
        assert env.data["completion"] == "hi"

    def test_invoke_stream_yields_chunks_until_done(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            sse = (
                'data: {"delta": "Hel"}\n\n'
                'data: {"delta": "lo", "done": true, "tokensUsed": 1}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})

        c = _client(handler)

        async def collect():
            return [chunk async for chunk in c.compute.llms.invoke_stream("gpt-4o", prompt="hi")]

        chunks = asyncio.run(collect())
        assert captured["url"] == "https://acme.api.k9o.io/@portal/compute/llms/gpt-4o/invoke-stream"
        assert "".join(ch["delta"] for ch in chunks) == "Hello"
        assert chunks[1]["done"] is True


class TestOrgDefaultLlm:
    def test_get_and_set(self):
        h = _ok("mistral-7b")
        c = create_client(base_url="https://acme.api.k9o.io")
        c._config.transport = httpx.MockTransport(h)
        c.org.default_llm.get()
        assert h.url == "https://acme.api.k9o.io/org/default-llm"
        c.org.default_llm.set(model_id="claude-3-5-sonnet")
        assert h.method == "PATCH"
        assert json.loads(h.body) == {"modelId": "claude-3-5-sonnet"}


class TestRealtime:
    def test_topic_builders(self):
        assert realtime_topic.collection("orders") == "collections.orders.*"
        assert realtime_topic.workflow_runs() == "studio.workflows.runs.*"
        assert realtime_topic.dashboard_refresh("dsh_x") == "studio.dashboards.refresh.dsh_x"
        assert realtime_topic.function_invocations("fn_x") == "forge.functions.invocations.fn_x"
        assert realtime_topic.audit_org("role_granted") == "audit.org.role_granted"

    def test_replay_posts_with_cursor(self):
        h = _ok([])
        c = _client(h)
        c.realtime.replay(topic=realtime_topic.workflow_runs(), from_sequence=42, limit=100)
        assert h.method == "POST" and h.url == "https://acme.api.k9o.io/@portal/realtime/replay"
        assert json.loads(h.body)["fromSequence"] == 42

    def test_replay_rejects_negative_sequence(self):
        c = create_client(base_url="https://acme.api.k9o.io", project_slug="portal")
        with pytest.raises(KError) as exc:
            c.realtime.replay(topic=realtime_topic.workflow_runs(), from_sequence=-1)
        assert exc.value.code == "K9O_INVALID_FILTER"

    def test_subscribe_sse_yields_events(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            ev1 = {"topic": "collections.orders.*", "type": "row_inserted", "sequence": 1, "payload": {}, "occurredAt": "t1"}
            ev2 = {"topic": "collections.orders.*", "type": "row_updated", "sequence": 2, "payload": {}, "occurredAt": "t2"}
            sse = f"data: {json.dumps(ev1)}\n\ndata: {json.dumps(ev2)}\n\n"
            return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})

        c = _client(handler)

        async def collect():
            return [e async for e in c.realtime.subscribe(realtime_topic.collection("orders"), transport="sse")]

        seen = asyncio.run(collect())
        assert "realtime/subscribe" in captured["url"] and "topic=collections.orders" in captured["url"]
        assert [e["type"] for e in seen] == ["row_inserted", "row_updated"]

    def test_subscribe_poll_yields_then_stops(self):
        ev = {"topic": "studio.workflows.runs.*", "type": "workflow.run.completed", "sequence": 5, "payload": {}, "occurredAt": "t"}
        h = _ok([ev])
        c = _client(h)

        async def collect():
            out = []
            async for e in c.realtime.subscribe(realtime_topic.workflow_runs(), transport="poll", poll_interval_s=0.01):
                out.append(e)
                break  # break terminates the async generator
            return out

        seen = asyncio.run(collect())
        assert h.url == "https://acme.api.k9o.io/@portal/realtime/replay"
        assert seen[0]["type"] == "workflow.run.completed"
