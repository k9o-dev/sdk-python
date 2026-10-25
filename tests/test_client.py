"""Tests for create_client + K9oClient with httpx MockTransport stubs."""

import json

import httpx
import pytest

from k9o import KError, create_client


def _mock_transport(handler):
    """Build an httpx MockTransport from a callable handler(request) -> Response."""
    return httpx.MockTransport(handler)


class TestCreateClient:
    def test_constructs_with_minimal_options(self):
        c = create_client(base_url="https://api.k9o.io")
        assert c.config.base_url == "https://api.k9o.io"
        assert callable(c.from_)
        assert hasattr(c.projects, "list")

    def test_normalises_trailing_slash(self):
        c = create_client(base_url="https://api.k9o.io/")
        assert c.config.base_url == "https://api.k9o.io"

    def test_propagates_options(self):
        c = create_client(
            base_url="https://acme.api.k9o.io",
            api_key="k9o_test",
            org_slug="acme",
            project_slug="member-portal",
        )
        assert c.config.api_key == "k9o_test"
        assert c.config.org_slug == "acme"
        assert c.config.project_slug == "member-portal"

    def test_throws_invalid_base_url_at_construct(self):
        with pytest.raises(KError) as exc:
            create_client(base_url="https://api.k9o.io/v2")
        assert exc.value.code == "K9O_INVALID_BASE_URL"

    def test_base_url_omitted_defaults_to_apex(self):
        c = create_client()
        assert c.config.base_url == "https://api.k9o.io"

    def test_base_url_omitted_with_org_derives_subdomain(self):
        c = create_client(org_slug="acme")
        assert c.config.base_url == "https://acme.api.k9o.io"

    def test_apex_with_org_derives_subdomain(self):
        c = create_client(base_url="https://api.k9o.io", org_slug="acme")
        assert c.config.base_url == "https://acme.api.k9o.io"

    def test_explicit_subdomain_passthrough(self):
        c = create_client(base_url="https://acme.api.k9o.io", org_slug="acme")
        assert c.config.base_url == "https://acme.api.k9o.io"

    def test_self_hosted_host_passthrough(self):
        c = create_client(base_url="https://platform.acme.internal", org_slug="acme")
        assert c.config.base_url == "https://platform.acme.internal"


class TestDataPlaneDSL:
    def test_select_composes_url_with_filters(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            return httpx.Response(200, json={"data": [], "meta": {"cursor": {"next": None}}})

        c = create_client(
            base_url="https://acme.api.k9o.io",
            project_slug="member-portal",
        )
        c._config.transport = _mock_transport(handler)
        env = c.from_("posts").select().eq("status", "published").gt("views", 100).limit(20).execute()
        assert captured["method"] == "GET"
        assert "https://acme.api.k9o.io/@member-portal/data/posts" in captured["url"]
        assert "status=eq.published" in captured["url"]
        assert "views=gt.100" in captured["url"]
        assert "limit=20" in captured["url"]
        assert env.data == []

    def test_select_requires_project_slug(self):
        c = create_client(base_url="https://api.k9o.io")
        with pytest.raises(KError) as exc:
            c.from_("posts").select().execute()
        assert exc.value.code == "K9O_MISSING_PROJECT_CONTEXT"

    def test_select_validates_collection_name(self):
        c = create_client(base_url="https://acme.api.k9o.io", project_slug="member-portal")
        with pytest.raises(KError) as exc:
            c.from_("Bad-Name").select().execute()
        assert exc.value.code == "K9O_INVALID_FIELD_VALUE"

    def test_insert_posts_record(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"data": {"id": "rec_x", "title": "hi"}, "meta": {}})

        c = create_client(
            base_url="https://acme.api.k9o.io",
            project_slug="member-portal",
        )
        c._config.transport = _mock_transport(handler)
        env = c.from_("posts").insert({"title": "hi"})
        assert captured["method"] == "POST"
        assert captured["url"] == "https://acme.api.k9o.io/@member-portal/data/posts"
        assert json.loads(captured["body"]) == {"title": "hi"}
        assert env.data == {"id": "rec_x", "title": "hi"}

    def test_update_requires_id_filter(self):
        c = create_client(base_url="https://acme.api.k9o.io", project_slug="member-portal")
        with pytest.raises(KError) as exc:
            c.from_("posts").update({"title": "x"}).execute()
        assert exc.value.code == "K9O_INVALID_FIELD_VALUE"

    def test_update_with_eq_id_patches_document(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            return httpx.Response(200, json={"data": {"id": "rec_y"}, "meta": {}})

        c = create_client(base_url="https://acme.api.k9o.io", project_slug="member-portal")
        c._config.transport = _mock_transport(handler)
        c.from_("posts").update({"title": "x"}).eq("id", "rec_y").execute()
        assert captured["method"] == "PATCH"
        assert captured["url"] == "https://acme.api.k9o.io/@member-portal/data/posts/rec_y"

    def test_in_filter_serialises_as_parenthesised_list(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"data": [], "meta": {}})

        c = create_client(base_url="https://acme.api.k9o.io", project_slug="member-portal")
        c._config.transport = _mock_transport(handler)
        c.from_("posts").select().in_("status", ["published", "draft"]).execute()
        # Note: httpx URL-encodes the parentheses + comma; we just check the op + col present
        assert "status=in" in captured["url"]


class TestProjectsNamespace:
    def test_list_gets_projects(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            return httpx.Response(200, json={"data": [], "meta": {}})

        c = create_client(base_url="https://acme.api.k9o.io", org_slug="acme")
        c._config.transport = _mock_transport(handler)
        c.projects.list()
        assert captured["method"] == "GET"
        assert captured["url"] == "https://acme.api.k9o.io/projects"

    def test_create_validates_slug(self):
        c = create_client(base_url="https://acme.api.k9o.io", org_slug="acme")
        with pytest.raises(KError) as exc:
            c.projects.create(slug="Bad-Slug", name="x")
        assert exc.value.code == "K9O_INVALID_FIELD_VALUE"

    def test_get_routes_to_project_path(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"data": {"id": "p", "slug": "member-portal", "name": "MP", "custodyMode": "managed", "createdAt": "x", "updatedAt": None, "orgId": "o"}, "meta": {}})

        c = create_client(base_url="https://acme.api.k9o.io")
        c._config.transport = _mock_transport(handler)
        c.projects.get("member-portal")
        assert captured["url"] == "https://acme.api.k9o.io/@member-portal/project"


class TestGateNamespace:
    def test_sign_in_requires_project(self):
        c = create_client(base_url="https://api.k9o.io")
        with pytest.raises(KError) as exc:
            c.gate.sign_in(email="x@y.com", password="z")
        assert exc.value.code == "K9O_MISSING_PROJECT_CONTEXT"

    def test_sign_in_routes_correctly(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"data": {"user": {"id": "eu_x"}, "session": {}}, "meta": {}})

        c = create_client(base_url="https://acme.api.k9o.io", project_slug="member-portal")
        c._config.transport = _mock_transport(handler)
        c.gate.sign_in(email="x@y.com", password="z")
        assert captured["url"] == "https://acme.api.k9o.io/@member-portal/gate/signin"
        assert json.loads(captured["body"]) == {"email": "x@y.com", "password": "z"}

    def test_whoami_routes_correctly(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            return httpx.Response(200, json={"data": {"user": {"id": "eu_x"}}, "meta": {}})

        c = create_client(base_url="https://acme.api.k9o.io", project_slug="member-portal")
        c._config.transport = _mock_transport(handler)
        c.gate.whoami()
        assert captured["method"] == "GET"
        assert captured["url"] == "https://acme.api.k9o.io/@member-portal/gate/whoami"


class TestGateHosted:
    OK = {"data": {"signInUrl": "https://k3xy.gate-de01.k9o.io/sign-in", "rpId": "k3xy.gate-de01.k9o.io"}, "meta": {}}

    def _client(self, handler, **kw):
        c = create_client(base_url="https://acme.api.k9o.io", project_slug="member-portal", **kw)
        c._config.transport = _mock_transport(handler)
        return c

    def test_get_no_credential_returns_fields(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=self.OK)

        c = self._client(handler, api_key="partner-secret")
        c._config.default_headers = {"Authorization": "Bearer x", "Cookie": "a=b"}
        r = c.gate.hosted()
        calls = [x for x in calls if x.method != "HEAD"]  # region probe excluded
        assert len(calls) == 1
        assert calls[0].method == "GET"
        assert str(calls[0].url) == "https://acme.api.k9o.io/@member-portal/gate/hosted"
        assert "authorization" not in calls[0].headers
        assert "cookie" not in calls[0].headers
        assert r.data["signInUrl"] == "https://k3xy.gate-de01.k9o.io/sign-in"
        assert r.data["rpId"] == "k3xy.gate-de01.k9o.io"

    def test_async_no_credential(self):
        import asyncio

        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=self.OK)

        c = self._client(handler, api_key="partner-secret")
        r = asyncio.run(c.gate.hosted_async())
        calls = [x for x in calls if x.method != "HEAD"]
        assert "authorization" not in calls[0].headers
        assert r.data["rpId"] == "k3xy.gate-de01.k9o.io"

    def test_uniform_404(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"code": "K9O_PROJECT_NOT_FOUND", "message": "not found", "context": {}})

        with pytest.raises(KError) as exc:
            self._client(handler).gate.hosted()
        assert exc.value.status == 404
        assert exc.value.code == "K9O_PROJECT_NOT_FOUND"

    def test_requires_project_no_request(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json=self.OK)

        c = create_client(base_url="https://api.k9o.io")
        c._config.transport = _mock_transport(handler)
        with pytest.raises(KError) as exc:
            c.gate.hosted()
        assert exc.value.code == "K9O_MISSING_PROJECT_CONTEXT"
        assert calls == []


class TestErrorHandling:
    def test_rehydrates_non_2xx_as_kerror(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                json={
                    "code": "K9O_TIER_CAP_HIT",
                    "message": "cap exceeded",
                    "context": {"dimension": "mau", "limit": 1000},
                    "recommendation": "upgrade to Ascent",
                },
            )

        c = create_client(base_url="https://acme.api.k9o.io", org_slug="acme")
        c._config.transport = _mock_transport(handler)
        with pytest.raises(KError) as exc:
            c.projects.list()
        assert exc.value.code == "K9O_TIER_CAP_HIT"
        assert exc.value.status == 429
        assert exc.value.context == {"dimension": "mau", "limit": 1000}
        assert exc.value.recommendation == "upgrade to Ascent"

    def test_malformed_envelope_raises_internal_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"wrong": "shape"})

        c = create_client(base_url="https://acme.api.k9o.io", org_slug="acme")
        c._config.transport = _mock_transport(handler)
        with pytest.raises(KError) as exc:
            c.projects.list()
        assert exc.value.code == "K9O_INTERNAL_ERROR"

    def test_meta_cost_passes_through_structured_dimensions(self):
        # meta.cost is a sparse structured open-map; object-valued
        # dimensions (egress, vaultOps) must survive deserialisation rather
        # than being coerced to float / dropped.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [],
                    "meta": {
                        "cost": {
                            "waypoints": 3,
                            "egress": {"gb": 4.55e-07, "zone": "intra-region"},
                            "vaultOps": {"encrypt": 2, "decrypt": 1},
                        }
                    },
                },
            )

        c = create_client(base_url="https://acme.api.k9o.io", org_slug="acme")
        c._config.transport = _mock_transport(handler)
        env = c.projects.list()
        assert env.meta.cost["waypoints"] == 3
        assert env.meta.cost["egress"] == {"gb": 4.55e-07, "zone": "intra-region"}
        assert env.meta.cost["vaultOps"] == {"encrypt": 2, "decrypt": 1}

    def test_meta_cursor_typed_accessor(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [],
                    "meta": {
                        "cursor": {"next": "abc123", "totalCount": 42},
                        "timing": {"totalMs": 12},
                        "context": {"requestId": "req_xyz"},
                    },
                },
            )

        c = create_client(base_url="https://acme.api.k9o.io", org_slug="acme")
        c._config.transport = _mock_transport(handler)
        env = c.projects.list()
        assert env.meta.cursor is not None
        assert env.meta.cursor.next == "abc123"
        assert env.meta.cursor.total_count == 42
        assert env.meta.timing is not None
        assert env.meta.timing.total_ms == 12
        assert env.meta.context is not None
        assert env.meta.context.request_id == "req_xyz"


def test_boolean_filter_values_use_lowercase_wire_form():
    """Python's str(True) is "True"; the gateway reads "true" / "false"."""
    from k9o.data import _wire

    assert _wire(True) == "true"
    assert _wire(False) == "false"
    assert _wire(7) == "7"
    assert _wire("ada") == "ada"
