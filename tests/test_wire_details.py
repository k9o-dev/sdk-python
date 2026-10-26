"""Wire details beyond the method/path/body inventory in test_contract_openapi.py."""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from k9o import create_client


def _client(data=None, **kw):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"data": data, "meta": {}})

    c = create_client(base_url="https://acme.api.corp.internal", project_slug="portal", api_key="k", **kw)
    c.config.transport = httpx.MockTransport(handler)
    return c, seen


def _calls(seen):
    return [r for r in seen if r.method != "HEAD"]


def test_upload_artifact_sends_raw_bytes_with_artifact_content_type():
    c, seen = _client({"artifactKey": "functions/p/abc.wasm"})
    env = c.functions.upload_artifact(b"\x00asm\x01\x00\x00\x00", "wasm")
    req = _calls(seen)[0]
    assert req.method == "POST" and req.url.path == "/@portal/functions/artifacts"
    assert req.headers["content-type"] == "application/wasm"
    assert req.content == b"\x00asm\x01\x00\x00\x00"
    assert env.data["artifactKey"] == "functions/p/abc.wasm"
    c.functions.upload_artifact(b"tarbytes", "tar")
    assert _calls(seen)[1].headers["content-type"] == "application/x-tar"
    with pytest.raises(ValueError):
        c.functions.upload_artifact(b"x", "zip")


def test_invoke_without_payload_sends_no_payload_key_and_carries_options():
    c, seen = _client({})
    c.functions.invoke("hello")
    assert json.loads(_calls(seen)[0].content) == {}
    c.functions.invoke("hello", {"a": 1}, background=True, on_behalf_of="u_1")
    assert json.loads(_calls(seen)[1].content) == {"payload": {"a": 1}, "background": True, "onBehalfOf": "u_1"}


def test_trigger_without_context_sends_empty_trigger_context():
    c, seen = _client({})
    c.studio.workflows.trigger("wf_1")
    assert json.loads(_calls(seen)[0].content) == {"triggerContext": {}}


def test_role_revoke_carries_decision_reason_in_the_delete_body():
    c, seen = _client({})
    c.org.gate.roles.revoke("g_1", decision_reason="left the team")
    req = _calls(seen)[0]
    assert req.method == "DELETE" and json.loads(req.content) == {"decisionReason": "left the team"}


def test_smtp_set_never_sends_a_password_and_omits_unset_from_name():
    c, seen = _client({})
    c.org.smtp.set(host="h", port=25, username="u", password_ref="ref", from_address="a@b.co")
    body = json.loads(_calls(seen)[0].content)
    assert body == {"smtpConfig": {"host": "h", "port": 25, "username": "u", "passwordRef": "ref",
                                   "fromAddress": "a@b.co"}}


def test_org_audit_tail_applies_the_window_client_side():
    now = datetime.now(timezone.utc)
    rows = [
        {"id": "a", "createdAt": (now - timedelta(minutes=1)).isoformat()},
        {"id": "b", "createdAt": (now - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")},
    ]
    c, seen = _client(rows)
    env = c.org.audit_log.tail(since_minutes=5, limit=50)
    req = _calls(seen)[0]
    assert req.url.path == "/audit-log" and dict(req.url.params) == {"limit": "50"}
    assert [r["id"] for r in env.data] == ["a"]


def test_project_update_renames_through_the_body_slug():
    c, seen = _client({})
    c.projects.update("demo", new_slug="demo2", description="d")
    req = _calls(seen)[0]
    assert req.method == "PATCH" and req.url.path == "/projects/demo"
    assert json.loads(req.content) == {"slug": "demo2", "description": "d"}


def test_sign_out_requires_a_refresh_token():
    c, _ = _client({})
    with pytest.raises(TypeError):
        c.gate.sign_out()


def test_base_url_is_used_as_given_for_an_internal_org_host():
    c, seen = _client({})
    c.projects.list()
    assert [r.url.host for r in _calls(seen)] == ["acme.api.corp.internal"]
