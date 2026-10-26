"""
Full-coverage parity tests for the Python SDK namespaces that bring it to
TS surface parity: migrations / functions / policies / audit / orgs / me /
full org (members/groups/smtp/audit_log/gate). Routes verified via httpx
MockTransport.
"""

import json

import httpx

from k9o import create_client


def _client(handler, **kw):
    c = create_client(base_url="https://acme.api.k9o.io", **kw)
    c._config.transport = httpx.MockTransport(handler)
    return c


def _capture():
    cap = {}

    def handler(request: httpx.Request) -> httpx.Response:
        cap["url"] = str(request.url)
        cap["method"] = request.method
        cap["body"] = request.content.decode() if request.content else ""
        return httpx.Response(200, json={"data": None, "meta": {}})

    return cap, handler


class TestMigrations:
    def test_routes(self):
        cap, h = _capture()
        c = _client(h, project_slug="portal")
        migration = {
            "version": 1,
            "slug": "init",
            "up": [
                {
                    "create_table": {
                        "name": "users",
                        "columns": [
                            {"name": "id", "type": "uuid", "primary_key": True},
                            {"name": "email", "type": "text", "not_null": True, "unique": True},
                            {
                                "name": "ssn",
                                "type": "text",
                                "encrypted": {"store": "vault", "searchable": True},
                                "blind_indexed": True,
                            },
                        ],
                        "indexes": [{"name": "users_email_idx", "columns": ["email"], "unique": True}],
                    }
                }
            ],
            "down": [{"drop_table": "users"}],
        }
        c.migrations.apply([migration])
        assert cap["method"] == "POST"
        assert cap["url"] == "https://acme.api.k9o.io/@portal/migrations/apply"
        # Structured DDL wire shape (snake_case keys; nested `searchable`).
        body = json.loads(cap["body"])
        op = body["migrations"][0]["up"][0]
        assert "create_table" in op
        assert op["create_table"]["columns"][0]["primary_key"] is True
        ssn = op["create_table"]["columns"][2]
        assert ssn["encrypted"] == {"store": "vault", "searchable": True}
        assert ssn["blind_indexed"] is True
        assert body["migrations"][0]["down"][0] == {"drop_table": "users"}
        c.migrations.list()
        assert cap["url"] == "https://acme.api.k9o.io/@portal/migrations"
        c.migrations.apply_pending("pend_x")
        assert cap["url"] == "https://acme.api.k9o.io/@portal/migrations/pending/pend_x/apply"
        c.migrations.reject_pending("pend_x", reason="nope")
        assert "nope" in cap["body"]


class TestFunctions:
    def test_routes(self):
        cap, h = _capture()
        c = _client(h, project_slug="portal")
        c.functions.deploy(name="greet", runtime="bun", tier="sandbox", artifact_key="functions/p/abc.tar", version="1")
        assert cap["method"] == "POST" and cap["url"] == "https://acme.api.k9o.io/@portal/functions"
        c.functions.invoke("greet", {"name": "World"})
        assert cap["url"] == "https://acme.api.k9o.io/@portal/functions/greet/invoke"
        assert json.loads(cap["body"]) == {"payload": {"name": "World"}}


class TestPolicies:
    def test_routes(self):
        cap, h = _capture()
        c = _client(h, project_slug="portal")
        c.policies.current()
        assert cap["url"] == "https://acme.api.k9o.io/@portal/policy"
        c.policies.create(policy={"collections": {}})
        assert cap["method"] == "POST" and cap["url"] == "https://acme.api.k9o.io/@portal/policies"
        c.policies.publish("pol_x")
        assert cap["url"] == "https://acme.api.k9o.io/@portal/policies/pol_x/publish"


class TestAudit:
    def test_query_and_tail(self):
        cap, h = _capture()
        c = _client(h, project_slug="portal")
        c.audit.query(event_type="data.write.access.insert", limit=50)
        assert cap["url"] == "https://acme.api.k9o.io/@portal/audit-log?eventType=data.write.access.insert&limit=50"
        c.audit.tail(since_minutes=10)
        assert "audit-log?after=" in cap["url"]


class TestOrgs:
    def test_routes(self):
        cap, h = _capture()
        c = _client(h, org_slug="acme")
        c.orgs.list()
        assert cap["url"] == "https://acme.api.k9o.io/orgs"
        c.orgs.current()
        assert cap["url"] == "https://acme.api.k9o.io/org"
        c.orgs.restore("org_x")
        assert cap["method"] == "POST" and cap["url"] == "https://acme.api.k9o.io/orgs/org_x/restore"


class TestMe:
    def test_routes(self):
        cap, h = _capture()
        c = _client(h)
        c.me.profile.get()
        assert cap["url"] == "https://acme.api.k9o.io/me"
        c.me.sessions.revoke_all()
        assert cap["method"] == "POST" and cap["url"] == "https://acme.api.k9o.io/me/sessions/revoke-all"
        c.me.api_tokens.create(label="ci", scope_manifest={})
        assert cap["url"] == "https://acme.api.k9o.io/me/api-tokens"


class TestOrgFull:
    def test_members_groups_gate_smtp(self):
        cap, h = _capture()
        c = _client(h)
        c.org.members.invite(email="x@y.com", role="ORG_MEMBER")
        assert cap["method"] == "POST" and cap["url"] == "https://acme.api.k9o.io/members"
        assert "ORG_MEMBER" in cap["body"]
        c.org.groups.list()
        assert cap["url"] == "https://acme.api.k9o.io/groups"
        c.org.gate.roles.grant(user_id="u_a", role="ORG_ADMIN")
        assert cap["url"] == "https://acme.api.k9o.io/role-grants"
        c.org.gate.idp_providers.list()
        assert cap["url"] == "https://acme.api.k9o.io/identity-providers"
        c.org.smtp.set(host="smtp.x.com", port=587, username="u", password_ref="ref_1",
                       from_address="n@x.com", from_name="X")
        assert cap["method"] == "PATCH" and cap["url"] == "https://acme.api.k9o.io/org"
        assert "smtpConfig" in cap["body"] and "smtp.x.com" in cap["body"]
        c.org.audit_log.query(type="data.write.org.role_granted")
        assert "audit-log?type=data.write.org.role_granted" in cap["url"]
        c.org.default_llm.get()
        assert cap["url"] == "https://acme.api.k9o.io/default-llm"
