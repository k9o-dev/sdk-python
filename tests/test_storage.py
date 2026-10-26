"""`client.storage` buckets and objects: routes, multipart body, expires_in bounds, encoding, guards, passthrough."""

import asyncio
import io
import json

import httpx
import pytest

from k9o import KError, create_client

BUCKET = {"name": "avatars", "public": False}
OK = {"data": BUCKET, "meta": {}}


def _client(cap, body=OK, status=200, project_slug="member-portal"):
    cap.setdefault("calls", [])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":  # regional-host probe, not a storage call
            return httpx.Response(200)
        cap["calls"].append(request)
        cap["url"] = str(request.url)
        cap["method"] = request.method
        cap["raw"] = request.content
        cap["headers"] = request.headers
        return httpx.Response(status, json=body)

    c = create_client(base_url="https://acme.api.k9o.io", api_key="k9o_test", project_slug=project_slug)
    c._config.transport = httpx.MockTransport(handler)
    return c


BASE = "https://acme.api.k9o.io/@member-portal/storage/buckets"


class TestBuckets:
    def test_list(self):
        cap = {}
        _client(cap).storage.list_buckets()
        assert (cap["method"], cap["url"]) == ("GET", BASE)

    def test_get_encodes_name(self):
        cap = {}
        _client(cap).storage.get_bucket("a b/c")
        assert (cap["method"], cap["url"]) == ("GET", BASE + "/a%20b%2Fc")

    def test_create_body_wire_names_and_omits_unset(self):
        cap = {}
        _client(cap).storage.create_bucket(
            "avatars", public=True, file_size_limit=1024, allowed_mime_types=["image/png"],
            versioning=False, delete_after_days=7, byos_binding_id="loc_1",
        )
        assert (cap["method"], cap["url"]) == ("POST", BASE)
        assert json.loads(cap["raw"]) == {
            "name": "avatars", "public": True, "fileSizeLimit": 1024, "allowedMimeTypes": ["image/png"],
            "versioning": False, "deleteAfterDays": 7, "byosBindingId": "loc_1",
        }
        _client(cap).storage.create_bucket("plain")
        assert json.loads(cap["raw"]) == {"name": "plain"}

    def test_update_patch_null_clears(self):
        cap = {}
        _client(cap).storage.update_bucket("avatars", file_size_limit=None, public=True, byos_binding_id=None)
        assert (cap["method"], cap["url"]) == ("PATCH", BASE + "/avatars")
        assert json.loads(cap["raw"]) == {"fileSizeLimit": None, "public": True, "byosBindingId": None}

    def test_delete_empty_flag(self):
        cap = {}
        c = _client(cap)
        c.storage.delete_bucket("avatars")
        assert (cap["method"], cap["url"]) == ("DELETE", BASE + "/avatars")
        c.storage.delete_bucket("avatars", empty=False)
        assert cap["url"] == BASE + "/avatars"
        c.storage.delete_bucket("avatars", empty=True)
        assert cap["url"] == BASE + "/avatars?empty=true"

    def test_empty_bucket_name_refused_without_request(self):
        cap = {}
        with pytest.raises(KError) as e:
            _client(cap).storage.get_bucket("")
        assert e.value.code == "K9O_INVALID_FIELD_VALUE"
        assert cap["calls"] == []


class TestDotSegmentBucket:
    @pytest.mark.parametrize("name", [".", ".."])
    def test_dot_names_refused_before_any_request(self, name):
        cap = {}
        c = _client(cap)
        s = c.storage
        h = s.from_(name)
        calls = (
            lambda: s.get_bucket(name),
            lambda: s.update_bucket(name, public=True),
            lambda: s.delete_bucket(name),
            lambda: h.upload("p", "d"),
            lambda: h.create_signed_url("p", expires_in=5),
            lambda: h.list(),
            lambda: h.remove("p"),
        )
        for call in calls:
            with pytest.raises(KError) as e:
                call()
            assert e.value.code == "K9O_INVALID_FIELD_VALUE"
            assert e.value.context == {"field": "bucket", "reason": "dot_segment"}

        async def run():
            for call in (
                lambda: s.get_bucket_async(name),
                lambda: s.update_bucket_async(name, public=True),
                lambda: s.delete_bucket_async(name),
                lambda: h.upload_async("p", "d"),
                lambda: h.create_signed_url_async("p", expires_in=5),
                lambda: h.list_async(),
                lambda: h.remove_async("p"),
            ):
                with pytest.raises(KError) as e:
                    await call()
                assert e.value.context == {"field": "bucket", "reason": "dot_segment"}

        asyncio.run(run())
        assert cap["calls"] == []

    def test_ordinary_name_still_goes_out(self):
        cap = {}
        c = _client(cap)
        c.storage.get_bucket("avatars")
        c.storage.from_("avatars").list()
        assert len(cap["calls"]) == 2


class TestUpload:
    def test_multipart_parts_and_no_json_content_type(self):
        cap = {}
        _client(cap, body={"data": {"path": "a/b.txt"}, "meta": {}}).storage.from_("avatars").upload(
            "a/b.txt", "héllo", content_type="text/plain", upsert=True, metadata={"k": "v"},
        )
        assert (cap["method"], cap["url"]) == ("POST", BASE + "/avatars/objects")
        ct = cap["headers"]["content-type"]
        assert ct.startswith("multipart/form-data; boundary=")
        assert "json" not in ct
        raw = cap["raw"]
        boundary = ct.split("boundary=")[1].encode()
        assert raw.count(b"--" + boundary) == 6  # 5 parts + closing marker
        assert b'name="file"; filename="b.txt"' in raw
        assert "héllo".encode("utf-8") in raw
        assert b"Content-Type: text/plain" in raw
        assert b'name="path"\r\n\r\na/b.txt\r\n' in raw
        assert b'name="contentType"\r\n\r\ntext/plain\r\n' in raw
        assert b'name="upsert"\r\n\r\ntrue\r\n' in raw
        assert b'name="metadata"\r\n\r\n{"k": "v"}\r\n' in raw
        assert cap["headers"]["authorization"] == "Bearer k9o_test"

    def test_defaults_upsert_false_and_optional_parts_absent(self):
        cap = {}
        _client(cap).storage.from_("avatars").upload("x.bin", b"\x00\x01\xff")
        raw = cap["raw"]
        assert b'name="upsert"\r\n\r\nfalse\r\n' in raw
        assert b'name="contentType"' not in raw and b'name="metadata"' not in raw
        assert b"\x00\x01\xff" in raw

    def test_file_object_bytes_as_given(self):
        cap = {}
        _client(cap).storage.from_("avatars").upload("x.bin", io.BytesIO(b"stream-bytes"))
        assert b"stream-bytes" in cap["raw"]

    def test_empty_path_refused_without_request(self):
        cap = {}
        with pytest.raises(KError) as e:
            _client(cap).storage.from_("avatars").upload("", "x")
        assert e.value.code == "K9O_INVALID_FIELD_VALUE"
        assert cap["calls"] == []

    def test_path_with_dotdot_and_leading_slash_not_rewritten(self):
        cap = {}
        _client(cap).storage.from_("avatars").upload("/../etc/x", "d")
        assert b'name="path"\r\n\r\n/../etc/x\r\n' in cap["raw"]
        assert cap["url"] == BASE + "/avatars/objects"

    def test_bucket_encoded_in_path(self):
        cap = {}
        _client(cap).storage.from_("../x").upload("a", "d")
        assert cap["url"] == BASE + "/..%2Fx/objects"


class TestSignedUrl:
    SIGNED = {"data": {"signedUrl": "https://x", "expiresIn": 60}, "meta": {}}

    def test_posts_body(self):
        cap = {}
        r = _client(cap, body=self.SIGNED).storage.from_("avatars").create_signed_url(
            "a b.png", expires_in=60, download=True
        )
        assert (cap["method"], cap["url"]) == ("POST", BASE + "/avatars/objects/sign")
        assert json.loads(cap["raw"]) == {"path": "a b.png", "expiresIn": 60, "download": True}
        assert r.data["signedUrl"] == "https://x"

    def test_download_omitted_when_not_given(self):
        cap = {}
        _client(cap, body=self.SIGNED).storage.from_("avatars").create_signed_url("a", expires_in=1)
        assert json.loads(cap["raw"]) == {"path": "a", "expiresIn": 1}

    @pytest.mark.parametrize("ok", [1, 604800])
    def test_bounds_accepted(self, ok):
        cap = {}
        _client(cap, body=self.SIGNED).storage.from_("avatars").create_signed_url("a", expires_in=ok)
        assert json.loads(cap["raw"])["expiresIn"] == ok

    @pytest.mark.parametrize("bad", [0, -1, 604801, 1.5, 60.0, "60", None, True])
    def test_bounds_refused_without_request(self, bad):
        cap = {}
        with pytest.raises(KError) as e:
            _client(cap).storage.from_("avatars").create_signed_url("a", expires_in=bad)
        assert e.value.code == "K9O_INVALID_FIELD_VALUE"
        assert cap["calls"] == []

    def test_expires_in_is_required(self):
        cap = {}
        with pytest.raises(TypeError):
            _client(cap).storage.from_("avatars").create_signed_url("a")  # type: ignore[call-arg]
        assert cap["calls"] == []

    def test_no_signed_put_copy_or_transform(self):
        h = _client({}).storage.from_("avatars")
        assert not hasattr(h, "create_signed_upload_url") and not hasattr(h, "copy")
        with pytest.raises(TypeError):
            h.create_signed_url("a", expires_in=60, transform={})  # type: ignore[call-arg]


class TestListRemove:
    def test_list_with_and_without_prefix(self):
        cap = {}
        h = _client(cap, body={"data": [], "meta": {}}).storage.from_("avatars")
        h.list()
        assert (cap["method"], cap["url"]) == ("GET", BASE + "/avatars/objects")
        h.list(prefix="a b&c=d/")
        req = cap["calls"][-1]
        assert req.url.params["prefix"] == "a b&c=d/"
        assert "a b&c" not in str(req.url) and "&c=d" not in str(req.url)

    def test_remove_query_encoding(self):
        cap = {}
        _client(cap).storage.from_("avatars").remove("dir/a b&c.png")
        assert cap["method"] == "DELETE"
        req = cap["calls"][-1]
        assert req.url.path == "/@member-portal/storage/buckets/avatars/objects"
        assert req.url.params.multi_items() == [("path", "dir/a b&c.png")]
        assert "&c.png" not in str(req.url)

    def test_remove_empty_path_refused(self):
        cap = {}
        with pytest.raises(KError):
            _client(cap).storage.from_("avatars").remove("")
        assert cap["calls"] == []


class TestGuardsAndErrors:
    def test_missing_slug_refused_everywhere_without_request(self):
        cap = {}
        s = _client(cap, project_slug=None).storage
        for call in (
            lambda: s.list_buckets(),
            lambda: s.get_bucket("a"),
            lambda: s.create_bucket("abc"),
            lambda: s.update_bucket("a", public=True),
            lambda: s.delete_bucket("a"),
            lambda: s.from_("a").upload("p", "d"),
            lambda: s.from_("a").create_signed_url("p", expires_in=5),
            lambda: s.from_("a").list(),
            lambda: s.from_("a").remove("p"),
        ):
            with pytest.raises(KError) as e:
                call()
            assert e.value.code == "K9O_MISSING_PROJECT_CONTEXT"
        assert cap["calls"] == []

    def test_409_bucket_not_empty_passthrough(self):
        cap = {}
        body = {"code": "K9O_BUCKET_NOT_EMPTY", "message": "bucket_not_empty", "context": {}, "recommendation": None}
        with pytest.raises(KError) as e:
            _client(cap, body=body, status=409).storage.delete_bucket("avatars")
        assert e.value.code == "K9O_BUCKET_NOT_EMPTY" and e.value.status == 409

    def test_invalid_bucket_name_passthrough(self):
        body = {"code": "K9O_INVALID_BUCKET_NAME", "message": "bad name", "context": {}}
        with pytest.raises(KError) as e:
            _client({}, body=body, status=400).storage.create_bucket("Bad_Name")
        assert e.value.code == "K9O_INVALID_BUCKET_NAME"

    def test_upload_error_never_contains_object_bytes(self):
        secret = "TOP-SECRET-OBJECT-BYTES"
        body = {"code": "K9O_ALREADY_EXISTS", "message": "exists", "context": {"path": "x"}}
        with pytest.raises(KError) as e:
            _client({}, body=body, status=409).storage.from_("avatars").upload("x", secret)
        assert secret not in str(e.value) and secret not in repr(e.value) and secret not in e.value.message
        # SDK-side refusals do not echo the bytes either
        with pytest.raises(KError) as e2:
            _client({}).storage.from_("avatars").upload("", secret)
        assert secret not in str(e2.value) and secret not in repr(e2.value)


class TestAsync:
    def test_async_delete_bucket_empty_flag(self):
        cap = {}
        c = _client(cap)

        async def run():
            await c.storage.delete_bucket_async("avatars")
            await c.storage.delete_bucket_async("avatars", empty=False)
            await c.storage.delete_bucket_async("avatars", empty=True)

        asyncio.run(run())
        urls = [str(r.url) for r in cap["calls"]]
        assert urls == [BASE + "/avatars", BASE + "/avatars", BASE + "/avatars?empty=true"]
        assert {r.method for r in cap["calls"]} == {"DELETE"}

    def test_async_remove_query_encoding(self):
        cap = {}
        c = _client(cap)
        asyncio.run(c.storage.from_("avatars").remove_async("dir/a b&c.png"))
        req = cap["calls"][-1]
        assert req.method == "DELETE"
        assert req.url.path == "/@member-portal/storage/buckets/avatars/objects"
        assert req.url.params.multi_items() == [("path", "dir/a b&c.png")]
        assert "&c.png" not in str(req.url)

    def test_async_twins(self):
        cap = {}
        c = _client(cap, body={"data": {"signedUrl": "u", "expiresIn": 9}, "meta": {}})
        h = c.storage.from_("avatars")

        async def run():
            await c.storage.list_buckets_async()
            await c.storage.create_bucket_async("abc", public=True)
            await c.storage.update_bucket_async("abc", file_size_limit=None)
            await c.storage.delete_bucket_async("abc", empty=True)
            await h.upload_async("a/b.txt", "data", content_type="text/plain")
            await h.create_signed_url_async("a", expires_in=9)
            await h.list_async(prefix="p")
            await h.remove_async("a")
            with pytest.raises(KError):
                await h.create_signed_url_async("a", expires_in=604801)

        asyncio.run(run())
        calls = [(r.method, r.url.path) for r in cap["calls"]]
        assert calls == [
            ("GET", "/@member-portal/storage/buckets"),
            ("POST", "/@member-portal/storage/buckets"),
            ("PATCH", "/@member-portal/storage/buckets/abc"),
            ("DELETE", "/@member-portal/storage/buckets/abc"),
            ("POST", "/@member-portal/storage/buckets/avatars/objects"),
            ("POST", "/@member-portal/storage/buckets/avatars/objects/sign"),
            ("GET", "/@member-portal/storage/buckets/avatars/objects"),
            ("DELETE", "/@member-portal/storage/buckets/avatars/objects"),
        ]
        assert cap["calls"][3].url.query == b"empty=true"
        assert cap["calls"][4].headers["content-type"].startswith("multipart/form-data; boundary=")
        assert b'name="file"; filename="b.txt"' in cap["calls"][4].content
