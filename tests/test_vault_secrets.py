"""
Wire-shape tests for `client.kibo.vault.secrets.*` — the full
family: list / get / create / reveal_challenge / reveal / update / rotate /
move / delete. Python parity port of the TS reference
`packages/kibo/test/secrets.test.ts`.

Verifies URL/query/method/body against the LIVE-VERIFIED contract (not just
the documented OpenAPI schema, which is inaccurate for `update`/`rotate`/
`move`'s response shape — see `k9o/kibo_vault.py` docstrings), including:
  - `region` required on every named-secret op except `list`
  - `value` base64-encoded on write, base64-decoded on reveal
  - the `X-K9O-Reveal-Challenge` header on `reveal`
  - `project_slug` required on every op (including `list`) — raises
    KError(K9O_MISSING_PROJECT_CONTEXT)

No real network calls: every test binds an httpx.MockTransport stub, per
this package's existing convention (see tests/test_client.py, tests/test_p6.py).
"""

import base64
import json

import httpx
import pytest

from k9o import KError, create_client

SUMMARY = {
    "id": "sec_abc", "name": "db/pw", "ownerId": "usr_1", "visibility": {"kind": "private"}, "version": 1,
    "kid": "vkey_1", "createdAt": "t", "createdBy": "usr_1", "updatedAt": "t", "updatedBy": "usr_1",
    "rotatedAt": None, "retiredAt": None, "metadata": {},
}


def _client(handler, **kw):
    c = create_client(base_url="https://acme.api.k9o.io", project_slug="member-portal", **kw)
    c._config.transport = httpx.MockTransport(handler)
    return c


def _ok(data, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        handler.url = str(request.url)
        handler.method = request.method
        handler.headers = dict(request.headers)
        handler.body = request.content.decode() if request.content else ""
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json={"data": data, "meta": {}})

    handler.url = handler.method = handler.body = None
    handler.headers = {}
    return handler


class TestList:
    def test_gets_vault_secrets_with_prefix_cursor_limit_no_region(self):
        h = _ok({"secrets": [SUMMARY], "nextCursor": None})
        c = _client(h)
        env = c.kibo.vault.secrets.list(prefix="db/", limit=10)
        assert h.method == "GET"
        assert h.url == "https://acme.api.k9o.io/@member-portal/vault/secrets?prefix=db%2F&limit=10"
        assert env.data["secrets"][0]["id"] == "sec_abc"

    def test_omits_unset_query_params(self):
        h = _ok({"secrets": [], "nextCursor": None})
        c = _client(h)
        c.kibo.vault.secrets.list()
        assert h.url == "https://acme.api.k9o.io/@member-portal/vault/secrets"

    def test_requires_project_slug(self):
        c = create_client(base_url="https://api.k9o.io")
        with pytest.raises(KError) as exc:
            c.kibo.vault.secrets.list()
        assert exc.value.code == "K9O_MISSING_PROJECT_CONTEXT"


class TestGet:
    def test_get_reads_metadata_from_the_list_route_exact_name(self):
        h = _ok({"secrets": [{**SUMMARY, "name": "db/pw-old"}, {**SUMMARY, "name": "db/pw"}], "nextCursor": None})
        c = _client(h)
        env = c.kibo.vault.secrets.get("db/pw")
        assert h.method == "GET"
        assert h.url == "https://acme.api.k9o.io/@member-portal/vault/secrets?prefix=db%2Fpw&limit=100"
        assert env.data["name"] == "db/pw"

    def test_get_not_found_is_404(self):
        h = _ok({"secrets": [], "nextCursor": None})
        c = _client(h)
        with pytest.raises(KError) as exc:
            c.kibo.vault.secrets.get("db/pw")
        assert exc.value.code == "K9O_NOT_FOUND" and exc.value.status == 404

    def test_requires_project_slug(self):
        c = create_client(base_url="https://api.k9o.io")
        with pytest.raises(KError) as exc:
            c.kibo.vault.secrets.get("db/pw", region="us01")
        assert exc.value.code == "K9O_MISSING_PROJECT_CONTEXT"


class TestCreate:
    def test_posts_with_region_query_and_base64_encoded_value(self):
        h = _ok(SUMMARY)
        c = _client(h)
        c.kibo.vault.secrets.create("db/pw", value="hunter2", region="us01", visibility={"kind": "private"})
        assert h.method == "POST"
        assert h.url == "https://acme.api.k9o.io/@member-portal/vault/secrets/db%2Fpw?region=us01"
        body = json.loads(h.body)
        assert body["value"] == base64.b64encode(b"hunter2").decode("ascii")
        assert body["value"] != "hunter2"
        assert body["visibility"] == {"kind": "private"}

    def test_omits_unset_visibility_and_metadata(self):
        h = _ok(SUMMARY)
        c = _client(h)
        c.kibo.vault.secrets.create("db/pw", value="hunter2", region="us01")
        body = json.loads(h.body)
        assert "visibility" not in body
        assert "metadata" not in body

    def test_requires_project_slug(self):
        c = create_client(base_url="https://api.k9o.io")
        with pytest.raises(KError) as exc:
            c.kibo.vault.secrets.create("db/pw", value="hunter2", region="us01")
        assert exc.value.code == "K9O_MISSING_PROJECT_CONTEXT"


class TestRevealChallenge:
    def test_posts_op_reveal_challenge_and_region(self):
        h = _ok({"challenge": "rvc_1", "expiresAt": "t"})
        c = _client(h)
        env = c.kibo.vault.secrets.reveal_challenge("db/pw", region="us01")
        assert h.method == "POST"
        assert "op=reveal-challenge" in h.url
        assert "region=us01" in h.url
        assert env.data["challenge"] == "rvc_1"


class TestReveal:
    def test_gets_with_challenge_header_and_decodes_base64_value(self):
        wire_value = base64.b64encode(b"hunter2").decode("ascii")
        h = _ok({
            "id": "sec_abc", "name": "db/pw", "version": 1, "value": wire_value,
            "revealedAt": "t", "attestationTier": {"urn": "u", "operator": "platform", "verified": True},
        })
        c = _client(h)
        env = c.kibo.vault.secrets.reveal("db/pw", region="us01", challenge="rvc_1")
        assert h.method == "GET"
        assert h.headers.get("x-k9o-reveal-challenge") == "rvc_1"
        assert env.data["value"] == "hunter2"
        assert env.data["attestationTier"]["operator"] == "platform"

    def test_requires_project_slug(self):
        c = create_client(base_url="https://api.k9o.io")
        with pytest.raises(KError) as exc:
            c.kibo.vault.secrets.reveal("db/pw", region="us01", challenge="rvc_1")
        assert exc.value.code == "K9O_MISSING_PROJECT_CONTEXT"


class TestUpdate:
    def test_puts_with_region_query_and_base64_value_returns_narrow_shape(self):
        h = _ok({"id": "sec_abc", "name": "db/pw", "version": 2})
        c = _client(h)
        env = c.kibo.vault.secrets.update("db/pw", region="us01", value="newpw")
        assert h.method == "PUT"
        assert h.url == "https://acme.api.k9o.io/@member-portal/vault/secrets/db%2Fpw?region=us01"
        assert json.loads(h.body)["value"] == base64.b64encode(b"newpw").decode("ascii")
        assert env.data == {"id": "sec_abc", "name": "db/pw", "version": 2}

    def test_includes_metadata_when_given(self):
        h = _ok({"id": "sec_abc", "name": "db/pw", "version": 2})
        c = _client(h)
        c.kibo.vault.secrets.update("db/pw", region="us01", value="newpw", metadata={"env": "prod"})
        assert json.loads(h.body)["metadata"] == {"env": "prod"}


class TestRotate:
    def test_posts_op_rotate_region_no_body(self):
        h = _ok({"id": "sec_abc", "name": "db/pw", "version": 2, "rotatedAt": "t", "ledgerSequenceNumber": 2})
        c = _client(h)
        env = c.kibo.vault.secrets.rotate("db/pw", region="us01")
        assert h.method == "POST"
        assert "op=rotate" in h.url
        assert h.body == ""
        assert env.data["ledgerSequenceNumber"] == 2


class TestMove:
    def test_posts_op_move_region_with_new_path_body(self):
        h = _ok({"id": "sec_abc", "name": "db/pw2", "event": "SECRET_PATH_CHANGED"})
        c = _client(h)
        env = c.kibo.vault.secrets.move("db/pw", region="us01", new_path="db/pw2")
        assert h.method == "POST"
        assert "op=move" in h.url
        assert json.loads(h.body) == {"newPath": "db/pw2"}
        assert env.data["event"] == "SECRET_PATH_CHANGED"


class TestDelete:
    def test_deletes_with_region_and_handles_204(self):
        h = _ok(None, status=204)
        c = _client(h)
        env = c.kibo.vault.secrets.delete("db/pw", region="us01")
        assert h.method == "DELETE"
        assert h.url == "https://acme.api.k9o.io/@member-portal/vault/secrets/db%2Fpw?region=us01"
        assert env.data is None

    def test_requires_project_slug(self):
        c = create_client(base_url="https://api.k9o.io")
        with pytest.raises(KError) as exc:
            c.kibo.vault.secrets.delete("db/pw", region="us01")
        assert exc.value.code == "K9O_MISSING_PROJECT_CONTEXT"
