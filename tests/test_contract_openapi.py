"""
Contract test: every public SDK call is sent through a recording transport and checked two ways.

  1. Exactly: HTTP method, path, query and JSON body are asserted per call (the table below is the wire inventory).
  2. Against the gateway's emitted OpenAPI (services/gateway/openapi.json): the (method, path) pair must be a
     declared route (`{param}` matches one path segment), every query parameter must be one the route declares (or be
     listed in EXTRA_QUERY with the handler that reads it), every declared required body field must be present, and
     no body key may fall outside the declared properties. Routes that declare no request body are checked by the
     exact assertions only (the gateway handler is the contract there).

A third test walks the client's public namespaces and fails when a public method is missing from the table, so a
method cannot be added or kept without a route.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from k9o import create_client

SPEC_PATH = Path(__file__).resolve().parents[3] / "services" / "gateway" / "openapi.json"
RAW = object()  # body is not JSON (binary / multipart): only the route is checked

BASE = "https://acme.api.k9o.io"

# Query parameters a gateway handler reads although its OpenAPI entry omits them.
EXTRA_QUERY: dict[tuple[str, str], set[str]] = {
    # services/gateway/src/routes/orgs-crud.ts GET /audit-log reads `type` and `limit`
    ("GET", "/audit-log"): {"type", "limit"},
    # services/gateway/src/routes/project-workflows.ts reads limit and cursor on the runs list
    ("GET", "/@{projectSlug}/workflows/{wflId}/runs"): {"limit", "cursor"},
    # services/gateway/src/routes/vault-secrets.ts reads op (and a legacy region) on the named-secret routes
    ("POST", "/@{projectSlug}/vault/secrets/{name}"): {"op", "region"},
    ("GET", "/@{projectSlug}/vault/secrets/{name}"): {"region"},
    ("PUT", "/@{projectSlug}/vault/secrets/{name}"): {"region"},
    ("DELETE", "/@{projectSlug}/vault/secrets/{name}"): {"region"},
    # services/gateway/src/routes/realtime: the SSE route reads topic and filter
    ("GET", "/@{projectSlug}/realtime/subscribe"): {"topic", "filter"},
    # services/gateway/src/routes/collection-records.ts: data-plane filters are column=op.value query keys
}
# Data-plane routes take column filters as free query keys.
FREE_QUERY_ROUTES = {("GET", "/@{projectSlug}/data/{collection}")}


def _client(**kw):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.method == "HEAD":
            return httpx.Response(200)
        data = {"value": "eA==", "secrets": [{"name": "db/pw"}], "nextCursor": None}
        return httpx.Response(200, json={"data": data, "meta": {}})

    c = create_client(base_url=BASE, project_slug="portal", api_key="k", **kw)
    c.config.transport = httpx.MockTransport(handler)
    return c, seen


def _sent(call) -> httpx.Request:
    c, seen = _client()
    call(c)
    reqs = [r for r in seen if r.method != "HEAD"]
    assert len(reqs) == 1, f"expected one request, got {len(reqs)}"
    return reqs[0]


MANIFEST = {"operations": ["read"], "projects": ["portal"], "resourceClasses": None, "collections": None, "cidrs": None}
MIGRATION = {"version": 1, "slug": "init", "up": [], "down": []}
P = "/@portal"

# (id, call, method, path, query, body)
TABLE = [
    # projects
    ("projects.list", lambda c: c.projects.list(), "GET", "/projects", {}, None),
    ("projects.create", lambda c: c.projects.create(display_name="Demo", slug="demo", custody_mode="PLATFORM_MANAGED"),
     "POST", "/projects", {}, {"displayName": "Demo", "slug": "demo", "custodyMode": "PLATFORM_MANAGED"}),
    ("projects.get", lambda c: c.projects.get("demo"), "GET", "/projects/demo", {}, None),
    ("projects.update", lambda c: c.projects.update("demo", display_name="Renamed"),
     "PATCH", "/projects/demo", {}, {"displayName": "Renamed"}),
    # functions
    ("functions.upload_artifact", lambda c: c.functions.upload_artifact(b"\x00asm", "wasm"),
     "POST", P + "/functions/artifacts", {}, RAW),
    ("functions.deploy", lambda c: c.functions.deploy(name="hello", runtime="bun", tier="sandbox",
                                                       artifact_key="functions/p/abc.tar", version="1"),
     "POST", P + "/functions", {},
     {"name": "hello", "runtime": "bun", "tier": "sandbox", "artifactKey": "functions/p/abc.tar", "version": "1"}),
    ("functions.list", lambda c: c.functions.list(limit=10, status="active"), "GET", P + "/functions",
     {"limit": "10", "status": "active"}, None),
    ("functions.get", lambda c: c.functions.get("hello"), "GET", P + "/functions/hello", {}, None),
    ("functions.delete", lambda c: c.functions.delete("hello"), "DELETE", P + "/functions/hello", {}, None),
    ("functions.invoke", lambda c: c.functions.invoke("hello", {"a": 1}), "POST", P + "/functions/hello/invoke",
     {}, {"payload": {"a": 1}}),
    # policies
    ("policies.current", lambda c: c.policies.current(), "GET", P + "/policy", {}, None),
    ("policies.list", lambda c: c.policies.list(status="published"), "GET", P + "/policies",
     {"status": "published"}, None),
    ("policies.create", lambda c: c.policies.create(policy={"collections": {}}, editor_mode="json"),
     "POST", P + "/policies", {}, {"policy": {"collections": {}}, "editorMode": "json"}),
    ("policies.validate", lambda c: c.policies.validate(policy={"collections": {}}),
     "POST", P + "/policies/validate", {}, {"policy": {"collections": {}}}),
    ("policies.get", lambda c: c.policies.get("pol_1"), "GET", P + "/policies/pol_1", {}, None),
    ("policies.update", lambda c: c.policies.update("pol_1", policy={"collections": {}}),
     "PATCH", P + "/policies/pol_1", {}, {"policy": {"collections": {}}}),
    ("policies.delete", lambda c: c.policies.delete("pol_1"), "DELETE", P + "/policies/pol_1", {}, None),
    ("policies.publish", lambda c: c.policies.publish("pol_1"), "POST", P + "/policies/pol_1/publish", {}, None),
    # audit
    ("audit.query", lambda c: c.audit.query(limit=10), "GET", P + "/audit-log", {"limit": "10"}, None),
    ("audit.query.filters", lambda c: c.audit.query(event_type="auth.sign_in", actor_id="u_1",
                                                    after="2026-01-01", before="2026-02-01"),
     "GET", P + "/audit-log",
     {"eventType": "auth.sign_in", "actorId": "u_1", "after": "2026-01-01", "before": "2026-02-01"}, None),
    ("audit.tail", lambda c: c.audit.tail(since_minutes=5), "GET", P + "/audit-log", {"after": "*", "limit": "100"}, None),
    # orgs / org
    ("orgs.list", lambda c: c.orgs.list(), "GET", "/orgs", {}, None),
    ("orgs.get", lambda c: c.orgs.get("acme"), "GET", "/orgs/acme", {}, None),
    ("orgs.restore", lambda c: c.orgs.restore("org_1"), "POST", "/orgs/org_1/restore", {}, None),
    ("orgs.current", lambda c: c.orgs.current(), "GET", "/org", {}, None),
    ("org.get", lambda c: c.org.get(), "GET", "/org", {}, None),
    ("org.members.list", lambda c: c.org.members.list(status="active", acceptance_status="accepted"), "GET",
     "/members", {"status": "active", "acceptanceStatus": "accepted"}, None),
    ("org.members.invite", lambda c: c.org.members.invite(email="a@b.co", role="ORG_MEMBER"), "POST", "/members", {},
     {"email": "a@b.co", "role": "ORG_MEMBER"}),
    ("org.members.remove", lambda c: c.org.members.remove("u_1"), "DELETE", "/members/u_1", {}, None),
    ("org.groups.list", lambda c: c.org.groups.list(user_id="u_1"), "GET", "/groups", {"userId": "u_1"}, None),
    ("org.groups.get", lambda c: c.org.groups.get("grp_1"), "GET", "/groups/grp_1", {}, None),
    ("org.audit_log.query", lambda c: c.org.audit_log.query(type="data.write.org.role_granted", limit=10), "GET",
     "/audit-log", {"type": "data.write.org.role_granted", "limit": "10"}, None),
    ("org.audit_log.tail", lambda c: c.org.audit_log.tail(since_minutes=5), "GET", "/audit-log", {"limit": "100"}, None),
    ("org.gate.roles.list", lambda c: c.org.gate.roles.list(), "GET", "/role-grants", {}, None),
    ("org.gate.roles.grant", lambda c: c.org.gate.roles.grant(user_id="u_1", role="ORG_ADMIN"), "POST",
     "/role-grants", {}, {"userId": "u_1", "role": "ORG_ADMIN"}),
    ("org.gate.roles.get", lambda c: c.org.gate.roles.get("g_1"), "GET", "/role-grants/g_1", {}, None),
    ("org.gate.roles.revoke", lambda c: c.org.gate.roles.revoke("g_1"), "DELETE", "/role-grants/g_1", {}, None),
    ("org.gate.idp_providers.list", lambda c: c.org.gate.idp_providers.list(), "GET", "/identity-providers", {}, None),
    ("org.gate.idp_providers.create",
     lambda c: c.org.gate.idp_providers.create(idp_provider="saml", display_name="Okta", client_id="cid",
                                               client_secret_ref="ref_1", tier_gating="free_tier_ok"),
     "POST", "/identity-providers", {},
     {"idpProvider": "saml", "displayName": "Okta", "clientId": "cid", "clientSecretRef": "ref_1",
      "tierGating": "free_tier_ok"}),
    ("org.gate.idp_providers.get", lambda c: c.org.gate.idp_providers.get("idp_1"), "GET",
     "/identity-providers/idp_1", {}, None),
    ("org.gate.idp_providers.configure", lambda c: c.org.gate.idp_providers.configure("idp_1", enabled=True),
     "PATCH", "/identity-providers/idp_1", {}, {"enabled": True}),
    ("org.gate.idp_providers.delete", lambda c: c.org.gate.idp_providers.delete("idp_1"), "DELETE",
     "/identity-providers/idp_1", {}, None),
    ("org.smtp.set", lambda c: c.org.smtp.set(host="smtp.x.io", port=587, username="u", password_ref="ref_1",
                                              from_address="a@b.co", from_name="A"),
     "PATCH", "/org", {},
     {"smtpConfig": {"host": "smtp.x.io", "port": 587, "username": "u", "passwordRef": "ref_1",
                     "fromAddress": "a@b.co", "fromName": "A"}}),
    ("org.smtp.test", lambda c: c.org.smtp.test(to="a@b.co"), "POST", "/org/smtp/test-email", {}, {"to": "a@b.co"}),
    ("org.smtp.unset", lambda c: c.org.smtp.unset(), "PATCH", "/org", {}, {"smtpConfig": None}),
    ("org.default_llm.get", lambda c: c.org.default_llm.get(), "GET", "/default-llm", {}, None),
    ("org.default_llm.set", lambda c: c.org.default_llm.set(model_id="llama-3-8b"), "PATCH", "/default-llm", {},
     {"modelId": "llama-3-8b"}),
    # me
    ("me.profile.get", lambda c: c.me.profile.get(), "GET", "/me", {}, None),
    ("me.profile.update", lambda c: c.me.profile.update(display_name="A"), "PATCH", "/me", {}, {"displayName": "A"}),
    ("me.sessions.list", lambda c: c.me.sessions.list(), "GET", "/me/sessions", {}, None),
    ("me.sessions.revoke", lambda c: c.me.sessions.revoke("s_1"), "POST", "/auth/sessions/s_1/revoke", {}, None),
    ("me.sessions.revoke_all", lambda c: c.me.sessions.revoke_all(), "POST", "/me/sessions/revoke-all", {}, None),
    ("me.api_tokens.list", lambda c: c.me.api_tokens.list(), "GET", "/me/api-tokens", {}, None),
    ("me.api_tokens.create", lambda c: c.me.api_tokens.create(label="ci", scope_manifest=MANIFEST, ttl_seconds=3600),
     "POST", "/me/api-tokens", {}, {"label": "ci", "scopeManifest": MANIFEST, "ttlSeconds": 3600}),
    ("me.api_tokens.delete", lambda c: c.me.api_tokens.delete("pat_1"), "DELETE", "/me/api-tokens/pat_1", {}, None),
    # gate
    ("gate.sign_up", lambda c: c.gate.sign_up(email="a@b.co", password="pw", display_name="A"), "POST",
     P + "/gate/signup", {}, {"email": "a@b.co", "password": "pw", "displayName": "A"}),
    ("gate.sign_in", lambda c: c.gate.sign_in(email="a@b.co", password="pw"), "POST", P + "/gate/signin", {},
     {"email": "a@b.co", "password": "pw"}),
    ("gate.sign_out", lambda c: c.gate.sign_out(refresh_token="rt"), "POST", P + "/gate/signout", {},
     {"refreshToken": "rt"}),
    ("gate.whoami", lambda c: c.gate.whoami(), "GET", P + "/gate/whoami", {}, None),
    ("gate.refresh_token", lambda c: c.gate.refresh_token(refresh_token="rt"), "POST", P + "/gate/refresh", {},
     {"refreshToken": "rt"}),
    # migrations
    ("migrations.list", lambda c: c.migrations.list(), "GET", P + "/migrations", {}, None),
    ("migrations.get", lambda c: c.migrations.get(1), "GET", P + "/migrations/1", {}, None),
    ("migrations.apply", lambda c: c.migrations.apply([MIGRATION]), "POST", P + "/migrations/apply", {},
     {"migrations": [MIGRATION]}),
    ("migrations.queue", lambda c: c.migrations.queue([MIGRATION]), "POST", P + "/migrations/queue", {},
     {"migrations": [MIGRATION]}),
    ("migrations.list_pending", lambda c: c.migrations.list_pending(), "GET", P + "/migrations/pending", {}, None),
    ("migrations.apply_pending", lambda c: c.migrations.apply_pending("pm_1"), "POST",
     P + "/migrations/pending/pm_1/apply", {}, None),
    ("migrations.reject_pending", lambda c: c.migrations.reject_pending("pm_1", "no"), "POST",
     P + "/migrations/pending/pm_1/reject", {}, {"reason": "no"}),
    ("migrations.delete_pending", lambda c: c.migrations.delete_pending("pm_1"), "DELETE",
     P + "/migrations/pending/pm_1", {}, None),
    # storage
    ("storage.list_buckets", lambda c: c.storage.list_buckets(), "GET", P + "/storage/buckets", {}, None),
    ("storage.get_bucket", lambda c: c.storage.get_bucket("docs"), "GET", P + "/storage/buckets/docs", {}, None),
    ("storage.create_bucket", lambda c: c.storage.create_bucket("docs", public=False), "POST",
     P + "/storage/buckets", {}, {"name": "docs", "public": False}),
    ("storage.update_bucket", lambda c: c.storage.update_bucket("docs", public=True), "PATCH",
     P + "/storage/buckets/docs", {}, {"public": True}),
    ("storage.delete_bucket", lambda c: c.storage.delete_bucket("docs", empty=True), "DELETE",
     P + "/storage/buckets/docs", {"empty": "true"}, None),
    ("storage.from_.upload", lambda c: c.storage.from_("docs").upload("a.txt", "hello"), "POST",
     P + "/storage/buckets/docs/objects", {}, RAW),
    ("storage.from_.create_signed_url", lambda c: c.storage.from_("docs").create_signed_url("a.txt", expires_in=600),
     "POST", P + "/storage/buckets/docs/objects/sign", {}, {"path": "a.txt", "expiresIn": 600}),
    ("storage.from_.list", lambda c: c.storage.from_("docs").list(prefix="a"), "GET",
     P + "/storage/buckets/docs/objects", {"prefix": "a"}, None),
    ("storage.from_.remove", lambda c: c.storage.from_("docs").remove("a.txt"), "DELETE",
     P + "/storage/buckets/docs/objects", {"path": "a.txt"}, None),
    # ai and compute
    ("ai.embed", lambda c: c.ai.embed(["a", "b"]), "POST", P + "/ai/embeddings", {}, {"input": ["a", "b"]}),
    ("compute.llms.list", lambda c: c.compute.llms.list(), "GET", P + "/compute/llms", {}, None),
    ("compute.llms.read", lambda c: c.compute.llms.read("llama-3-8b"), "GET", P + "/compute/llms/llama-3-8b", {}, None),
    ("compute.llms.invoke", lambda c: c.compute.llms.invoke("llama-3-8b", prompt="hi",
                                                           params={"maxTokens": 10, "temperature": 0.2}),
     "POST", P + "/compute/llms/llama-3-8b/invoke", {}, {"prompt": "hi", "maxTokens": 10, "temperature": 0.2}),
    # studio
    ("studio.workflows.list", lambda c: c.studio.workflows.list(status="active"), "GET", P + "/workflows",
     {"status": "active"}, None),
    ("studio.workflows.create",
     lambda c: c.studio.workflows.create({"name": "w", "triggerType": "manual", "triggerConfig": {},
                                          "actions": [{"index": 0, "action_type": "branch", "config": {}}]}),
     "POST", P + "/workflows", {},
     {"name": "w", "triggerType": "manual", "triggerConfig": {},
      "actions": [{"index": 0, "action_type": "branch", "config": {}}]}),
    ("studio.workflows.read", lambda c: c.studio.workflows.read("wf_1"), "GET", P + "/workflows/wf_1", {}, None),
    ("studio.workflows.update", lambda c: c.studio.workflows.update("wf_1", {"name": "w2"}), "PATCH",
     P + "/workflows/wf_1", {}, {"name": "w2"}),
    ("studio.workflows.delete", lambda c: c.studio.workflows.delete("wf_1"), "DELETE", P + "/workflows/wf_1", {}, None),
    ("studio.workflows.trigger", lambda c: c.studio.workflows.trigger("wf_1", {"k": "v"}), "POST",
     P + "/workflows/wf_1/runs", {}, {"triggerContext": {"k": "v"}}),
    ("studio.workflows.runs.list", lambda c: c.studio.workflows.runs.list("wf_1", limit=5), "GET",
     P + "/workflows/wf_1/runs", {"limit": "5"}, None),
    ("studio.workflows.runs.read", lambda c: c.studio.workflows.runs.read("wf_1", "run_1"), "GET",
     P + "/workflows/wf_1/runs/run_1", {}, None),
    ("studio.workflows.runs.cancel", lambda c: c.studio.workflows.runs.cancel("wf_1", "run_1"), "POST",
     P + "/workflows/wf_1/runs/run_1/cancel", {}, None),
    ("studio.dashboards.list", lambda c: c.studio.dashboards.list(pinned_only=True), "GET", P + "/dashboards",
     {"pinnedOnly": "true"}, None),
    ("studio.dashboards.create", lambda c: c.studio.dashboards.create({"name": "d"}), "POST", P + "/dashboards", {},
     {"name": "d"}),
    ("studio.dashboards.read", lambda c: c.studio.dashboards.read("d_1"), "GET", P + "/dashboards/d_1", {}, None),
    ("studio.dashboards.update", lambda c: c.studio.dashboards.update("d_1", {"name": "d2"}), "PATCH",
     P + "/dashboards/d_1", {}, {"name": "d2"}),
    ("studio.dashboards.delete", lambda c: c.studio.dashboards.delete("d_1"), "DELETE", P + "/dashboards/d_1", {}, None),
    ("studio.dashboards.pin", lambda c: c.studio.dashboards.pin("d_1"), "POST", P + "/dashboards/d_1/pin", {}, None),
    ("studio.dashboards.unpin", lambda c: c.studio.dashboards.unpin("d_1"), "POST", P + "/dashboards/d_1/unpin", {}, None),
    # kibo vault
    ("kibo.vault.secrets.list", lambda c: c.kibo.vault.secrets.list(prefix="db/"), "GET", P + "/vault/secrets",
     {"prefix": "db/"}, None),
    ("kibo.vault.secrets.get", lambda c: c.kibo.vault.secrets.get("db/pw"), "GET", P + "/vault/secrets",
     {"prefix": "db/pw", "limit": "100"}, None),
    ("kibo.vault.secrets.create", lambda c: c.kibo.vault.secrets.create("db/pw", value="x"), "POST",
     P + "/vault/secrets/db%2Fpw", {}, {"value": "eA=="}),
    ("kibo.vault.secrets.reveal_challenge", lambda c: c.kibo.vault.secrets.reveal_challenge("db/pw"), "POST",
     P + "/vault/secrets/db%2Fpw", {"op": "reveal-challenge"}, None),
    ("kibo.vault.secrets.reveal", lambda c: c.kibo.vault.secrets.reveal("db/pw", challenge="ch"), "GET",
     P + "/vault/secrets/db%2Fpw", {}, None),
    ("kibo.vault.secrets.update", lambda c: c.kibo.vault.secrets.update("db/pw", value="y"), "PUT",
     P + "/vault/secrets/db%2Fpw", {}, {"value": "eQ=="}),
    ("kibo.vault.secrets.rotate", lambda c: c.kibo.vault.secrets.rotate("db/pw"), "POST",
     P + "/vault/secrets/db%2Fpw", {"op": "rotate"}, None),
    ("kibo.vault.secrets.move", lambda c: c.kibo.vault.secrets.move("db/pw", new_path="db/pw2"), "POST",
     P + "/vault/secrets/db%2Fpw", {"op": "move"}, {"newPath": "db/pw2"}),
    ("kibo.vault.secrets.delete", lambda c: c.kibo.vault.secrets.delete("db/pw"), "DELETE",
     P + "/vault/secrets/db%2Fpw", {}, None),
    # data plane
    ("from_.select", lambda c: c.from_("posts").select().eq("published", True).limit(5).execute(), "GET",
     P + "/data/posts", {"published": "eq.true", "limit": "5"}, None),
    ("from_.insert", lambda c: c.from_("posts").insert({"title": "t"}), "POST", P + "/data/posts", {}, {"title": "t"}),
    ("from_.update", lambda c: c.from_("posts").update({"title": "u"}).eq("id", "p_1").execute(), "PATCH",
     P + "/data/posts/p_1", {}, {"title": "u"}),
    ("from_.delete", lambda c: c.from_("posts").delete().eq("id", "p_1").execute(), "DELETE", P + "/data/posts/p_1",
     {}, None),
]


# Calls whose reveal() decodes a body; the generic recording response is not a valid reveal payload.
def _spec():
    if not SPEC_PATH.exists():
        pytest.skip(f"gateway OpenAPI not found at {SPEC_PATH}")
    return json.loads(SPEC_PATH.read_text())


def _deref(spec, node):
    for _ in range(20):
        if isinstance(node, dict) and "$ref" in node:
            target = spec
            for part in node["$ref"].lstrip("#/").split("/"):
                target = target[part]
            node = target
        else:
            break
    return node if isinstance(node, dict) else {}


def _summarise(spec, schema):
    """{required, properties} of an object schema; properties None when the schema is open (a union or free-form)."""
    s = _deref(spec, schema)
    required = set(s.get("required") or [])
    props = set(s["properties"]) if s.get("properties") else None
    open_ = s.get("additionalProperties") is True
    for part in s.get("allOf") or []:
        sub = _summarise(spec, part)
        required |= set(sub["required"])
        if sub["properties"] is None:
            open_ = True
        else:
            props = (props or set()) | set(sub["properties"])
    if s.get("oneOf") or s.get("anyOf"):
        open_ = True
    return {"required": required, "properties": None if open_ or props is None else props}


def _route(spec, method: str, path: str):
    """(template, operation) for a sent path; `{param}` matches exactly one segment."""
    hits = []
    for template, item in spec["paths"].items():
        if method.lower() not in item:
            continue
        pattern = "^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)) + "$"
        if re.match(pattern, path):
            hits.append((template, item[method.lower()]))
    if not hits:
        return None
    # Prefer the most literal template (fewest params).
    hits.sort(key=lambda h: h[0].count("{"))
    return hits[0]


@pytest.mark.parametrize("entry", TABLE, ids=[e[0] for e in TABLE])
def test_exact_wire_and_openapi(entry):
    ident, call, method, path, query, body = entry
    req = _sent(call)
    assert req.method == method, ident
    assert req.url.raw_path.decode().split("?")[0] == path, ident

    sent_query = dict(parse_qsl(urlsplit(str(req.url)).query))
    if ident == "audit.tail":
        assert "after" in sent_query and sent_query.pop("after")
        query = {k: v for k, v in query.items() if k != "after"}
    assert sent_query == query, ident

    if body is RAW:
        sent_body = RAW
    elif req.content:
        sent_body = json.loads(req.content)
        assert body == sent_body, ident
    else:
        sent_body = None
        assert body is None, ident

    spec = _spec()
    hit = _route(spec, method, path.replace("%2F", "%2F"))
    assert hit is not None, f"{ident}: {method} {path} is not a route in the gateway OpenAPI"
    template, op = hit

    declared = {_deref(spec, p).get("name") for p in op.get("parameters", []) if _deref(spec, p).get("in") == "query"}
    if (method, template) not in FREE_QUERY_ROUTES:
        allowed = declared | EXTRA_QUERY.get((method, template), set())
        assert set(sent_query) <= allowed, f"{ident}: query {set(sent_query) - allowed} not read by {method} {template}"

    if isinstance(sent_body, dict):
        content = _deref(spec, op.get("requestBody", {})).get("content", {})
        media = content.get("application/json") or (next(iter(content.values())) if content else None)
        if media is not None and media.get("schema"):
            summary = _summarise(spec, media["schema"])
            missing = summary["required"] - set(sent_body)
            assert not missing, f"{ident}: required body fields missing: {missing}"
            if summary["properties"] is not None:
                extra = set(sent_body) - summary["properties"]
                assert not extra, f"{ident}: body fields the gateway does not declare: {extra}"


def test_subscribe_route_is_in_openapi():
    import asyncio

    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=b'data: {"type": "x"}\n\n', headers={"content-type": "text/event-stream"})

    c = create_client(base_url=BASE, project_slug="portal")
    c.config.transport = httpx.MockTransport(handler)

    async def go():
        return [e async for e in c.realtime.subscribe("collections.orders.*", filter={"a": 1})]

    asyncio.run(go())
    req = [r for r in seen if r.method != "HEAD"][0]
    assert req.method == "GET" and req.url.path == "/@portal/realtime/subscribe"
    assert dict(parse_qsl(req.url.query.decode())) == {"topic": "collections.orders.*", "filter": '{"a": 1}'}
    assert _route(_spec(), "GET", req.url.path) is not None


def test_invoke_stream_route_and_flat_body():
    import asyncio

    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=b'data: {"choices": []}\n\ndata: [DONE]\n\n',
                              headers={"content-type": "text/event-stream"})

    c = create_client(base_url=BASE, project_slug="portal")
    c.config.transport = httpx.MockTransport(handler)

    async def go():
        return [x async for x in c.compute.llms.invoke_stream("llama-3-8b", prompt="hi", params={"maxTokens": 3})]

    assert asyncio.run(go()) == [{"choices": []}]
    req = [r for r in seen if r.method != "HEAD"][0]
    assert req.method == "POST" and req.url.path == "/@portal/compute/llms/llama-3-8b/invoke-stream"
    assert json.loads(req.content) == {"prompt": "hi", "maxTokens": 3}
    assert _route(_spec(), "POST", req.url.path) is not None


# Dropped from the SDK: no gateway route serves them.
REMOVED = [
    "metadata",
    "me.notifications", "me.audit_log", "me.data_export",
    "gate.hosted", "gate.hosted_async", "gate.verify_session",
    "org.groups.create", "org.groups.delete", "org.members.get", "org.smtp.get",
    "realtime.replay",
    "policies.evaluate", "identity", "audit.emit",
]


@pytest.mark.parametrize("dotted", REMOVED)
def test_removed_methods_are_gone(dotted):
    c, _ = _client()
    obj = c
    for part in dotted.split("."):
        if not hasattr(obj, part):
            return
        obj = getattr(obj, part)
    pytest.fail(f"{dotted} is still on the client but the gateway has no route for it")


# Public callables that are not one HTTP call each.
NOT_A_CALL = {
    "from_.select", "from_.insert", "from_.update", "from_.delete",  # exercised through the builder entries
    "storage.from_", "from_",  # return builders / handles
    "realtime.subscribe", "compute.llms.invoke_stream",  # SSE generators, tested above
}


def _public_methods(obj, prefix, depth=0):
    out = []
    for name in dir(obj):
        if name.startswith("_") or depth > 5:
            continue
        member = getattr(obj, name)
        dotted = f"{prefix}.{name}" if prefix else name
        if inspect.ismethod(member):
            out.append(dotted)
        elif not callable(member) and not isinstance(member, (str, int, float, dict, list, tuple, type(None), bool)):
            if name in ("config",):
                continue
            out.extend(_public_methods(member, dotted, depth + 1))
    return out


def test_every_public_method_is_in_the_table():
    c, _ = _client()
    tabled = {e[0] for e in TABLE}
    tabled |= {re.sub(r"\.filters$", "", i) for i in tabled}
    missing = []
    for dotted in _public_methods(c, ""):
        if dotted.endswith("_async") or dotted in NOT_A_CALL:
            continue
        if dotted.startswith("storage.") and dotted.count(".") == 1 and dotted not in tabled:
            missing.append(dotted)
            continue
        if dotted not in tabled:
            missing.append(dotted)
    assert not missing, f"public methods with no wire entry in TABLE: {missing}"
