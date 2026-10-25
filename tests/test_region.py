"""Regional host resolution: one unauthenticated no-redirect HEAD, strict 308 Location validation, caching."""

import asyncio

import httpx
import pytest

from k9o import create_client
from k9o.http import HttpClientConfig, request
from k9o.region import regional_origin_from_location

DATA = {"data": [], "meta": {}}


def recorder(location, status=308, fail_head=False):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.method == "HEAD":
            if fail_head:
                raise httpx.ConnectError("boom", request=req)
            headers = {} if location is None else {"location": location}
            return httpx.Response(status, headers=headers)
        return httpx.Response(200, json=DATA)

    return calls, httpx.MockTransport(handler)


def mk(transport, base="https://acme.api.k9o.io"):
    c = create_client(
        base_url=base,
        project_slug="portal",
        api_key="secret-key",
        default_headers={"x-extra": "1"},
    )
    c.config.transport = transport
    return c


def heads(calls):
    return [c for c in calls if c.method == "HEAD"]


def test_probe_first_unauthenticated_then_regional_credentialed():
    calls, t = recorder("https://acme.api-de01.k9o.io/")
    mk(t).projects.list()
    assert calls[0].method == "HEAD"
    assert str(calls[0].url) == "https://acme.api.k9o.io/"
    assert "authorization" not in calls[0].headers
    assert "x-extra" not in calls[0].headers
    assert "cookie" not in calls[0].headers
    assert "x-k9o-project-slug" not in calls[0].headers
    assert calls[1].url.host == "acme.api-de01.k9o.io"
    assert calls[1].headers["authorization"] == "Bearer secret-key"


def test_cached_one_probe_for_two_calls_staging():
    calls, t = recorder("https://acme.api-staging-de01.k9o.io/")
    c = mk(t, "https://acme.api-staging.k9o.io")
    c.projects.list()
    c.projects.list()
    assert len(heads(calls)) == 1
    assert calls[2].url.host == "acme.api-staging-de01.k9o.io"


def test_relative_location_resolves_against_base_but_is_refused():
    # a relative Location stays on the region-free host, which is not a regional host
    calls, t = recorder("/elsewhere")
    mk(t).projects.list()
    assert calls[1].url.host == "acme.api.k9o.io"


def test_no_redirect_uses_configured_host_and_is_cached():
    calls, t = recorder(None, status=200)
    c = mk(t)
    c.projects.list()
    c.projects.list()
    assert len(heads(calls)) == 1
    assert calls[1].url.host == "acme.api.k9o.io"


@pytest.mark.parametrize("base", ["https://acme.api-de01.k9o.io", "https://api.example.com", "https://k9o.internal.corp", "https://api.k9o.io", "http://localhost:8080"])
def test_never_probes_other_base_urls(base):
    calls, t = recorder("https://evil.example/")
    mk(t, base).projects.list()
    assert heads(calls) == []
    assert str(calls[0].url).startswith(base)


HOSTILE = [
    "https://evil.example/",
    "https://acme.api-de01.k9o.io.evil.example/",
    "https://evilacme.api-de01.k9o.io/",
    "https://other.api-de01.k9o.io/",
    "https://acme.api-staging-de01.k9o.io/",
    "http://acme.api-de01.k9o.io/",
    "https://user:pw@acme.api-de01.k9o.io/",
    "https://u@acme.api-de01.k9o.io/",
    "https://acme.api-de01.k9o.io:8443/",
    "https://acme.api-deu01.k9o.io/",
    "https://acme.api-de1.k9o.io/",
    "https://acme.api-de01.k9o.io\\@evil.example/",
    "//evil.example/",
]


@pytest.mark.parametrize("loc", HOSTILE)
def test_hostile_location_refused_credential_stays_on_configured_host(loc):
    calls, t = recorder(loc)
    mk(t).projects.list()
    assert calls[1].url.host == "acme.api.k9o.io"
    assert regional_origin_from_location("acme.api.k9o.io", loc, "https://acme.api.k9o.io") is None


def test_apex_family_staging_does_not_accept_prod_regional():
    assert regional_origin_from_location("acme.api-staging.k9o.io", "https://acme.api-de01.k9o.io/", "https://acme.api-staging.k9o.io") is None
    assert regional_origin_from_location("acme.api.k9o.io", "https://acme.api-staging-de01.k9o.io/", "https://acme.api.k9o.io") is None


def test_network_failure_of_probe_not_cached():
    state = {"fail": True, "heads": 0}

    def handler(req):
        if req.method == "HEAD":
            state["heads"] += 1
            if state["fail"]:
                raise httpx.ConnectError("boom", request=req)
            return httpx.Response(308, headers={"location": "https://acme.api-de01.k9o.io/"})
        return httpx.Response(200, json=DATA)

    c = mk(httpx.MockTransport(handler))
    c.projects.list()
    assert state["heads"] == 1
    state["fail"] = False
    c.projects.list()
    assert state["heads"] == 2
    c.projects.list()
    assert state["heads"] == 2


def test_probe_does_not_follow_redirect():
    seen = []

    def handler(req):
        seen.append(req)
        if req.method == "HEAD":
            return httpx.Response(308, headers={"location": "https://evil.example/"})
        return httpx.Response(200, json=DATA)

    mk(httpx.MockTransport(handler)).projects.list()
    assert all(r.url.host != "evil.example" for r in seen)


def test_gate_sign_in_uses_regional_host():
    calls, t = recorder("https://acme.api-de01.k9o.io/")
    mk(t).gate.sign_in(email="a@b.c", password="pw")
    assert calls[0].method == "HEAD" and "authorization" not in calls[0].headers
    assert calls[1].url.host == "acme.api-de01.k9o.io"
    assert calls[1].method == "POST"


def test_async_client_probes_then_goes_regional_and_caches():
    from k9o.http import request_async

    calls, t = recorder("https://acme.api-de01.k9o.io/")
    cfg = HttpClientConfig(base_url="https://acme.api.k9o.io", api_key="secret-key", default_headers={"x-extra": "1"}, transport=t)

    async def go():
        await request_async(cfg, method="GET", path="/projects")
        await request_async(cfg, method="GET", path="/projects")

    asyncio.run(go())
    assert calls[0].method == "HEAD" and "authorization" not in calls[0].headers and "x-extra" not in calls[0].headers
    assert len(heads(calls)) == 1
    assert calls[1].url.host == "acme.api-de01.k9o.io"


def test_async_hostile_location_refused():
    from k9o.http import request_async

    calls, t = recorder("https://acme.api-de01.k9o.io.evil.example/")
    cfg = HttpClientConfig(base_url="https://acme.api.k9o.io", api_key="secret-key", transport=t)
    asyncio.run(request_async(cfg, method="GET", path="/projects"))
    assert calls[1].url.host == "acme.api.k9o.io"


def test_async_stream_uses_regional_host():
    from k9o.http import stream_sse_async

    seen = []

    def handler(req):
        seen.append(req)
        if req.method == "HEAD":
            return httpx.Response(308, headers={"location": "https://acme.api-de01.k9o.io/"})
        return httpx.Response(200, content=b'data: {"a":1}\n\ndata: [DONE]\n\n', headers={"content-type": "text/event-stream"})

    cfg = HttpClientConfig(base_url="https://acme.api.k9o.io", api_key="secret-key", transport=httpx.MockTransport(handler))

    async def go():
        return [x async for x in stream_sse_async(cfg, method="GET", path="/s")]

    assert asyncio.run(go()) == [{"a": 1}]
    assert seen[0].method == "HEAD" and "authorization" not in seen[0].headers
    assert seen[1].url.host == "acme.api-de01.k9o.io"


def test_probe_not_applied_to_regional_via_request():
    calls, t = recorder("https://evil.example/")
    cfg = HttpClientConfig(base_url="https://acme.api-de01.k9o.io", transport=t)
    request(cfg, method="GET", path="/x")
    assert heads(calls) == []
