"""
Retry + backoff behaviour.

Idempotent methods are retried on transient failures (transport / 502 /
503 / 504 / 429); non-idempotent methods and semantic 4xx are not.
Uses backoff="none" so the tests don't sleep.
"""

import httpx
import pytest

from k9o import KError, RetryConfig
from k9o.http import HttpClientConfig, request


def _config(handler, retry_config) -> HttpClientConfig:
    # Regional base: never probed (see tests/test_region.py), so call counts stay exact.
    return HttpClientConfig(
        base_url="https://acme.api-de01.k9o.io",
        transport=httpx.MockTransport(handler),
        retry_config=retry_config,
    )


NO_SLEEP = RetryConfig(max_retries=3, backoff="none")


def test_get_retries_transient_then_succeeds():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"code": "K9O_UPSTREAM_UNAVAILABLE", "message": "down"})
        return httpx.Response(200, json={"data": {"ok": True}, "meta": {}})

    env = request(_config(handler, NO_SLEEP), method="GET", path="/orgs")
    assert env.data == {"ok": True}
    assert calls["n"] == 3  # 2 failures + 1 success


def test_get_exhausts_retries_then_raises():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"code": "K9O_UPSTREAM_UNAVAILABLE", "message": "down"})

    with pytest.raises(KError):
        request(_config(handler, NO_SLEEP), method="GET", path="/orgs")
    assert calls["n"] == 4  # max_retries (3) + 1 initial


def test_post_is_not_retried():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"code": "K9O_UPSTREAM_UNAVAILABLE", "message": "down"})

    with pytest.raises(KError):
        request(_config(handler, NO_SLEEP), method="POST", path="/projects", body={"x": 1})
    assert calls["n"] == 1  # non-idempotent → single attempt


def test_get_semantic_4xx_is_not_retried():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, json={"code": "K9O_NOT_FOUND", "message": "nope"})

    with pytest.raises(KError):
        request(_config(handler, NO_SLEEP), method="GET", path="/orgs/missing")
    assert calls["n"] == 1  # 404 is semantic, not transient


def test_get_429_is_retried():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, json={"code": "K9O_RATE_LIMITED", "message": "slow down"})
        return httpx.Response(200, json={"data": None, "meta": {}})

    request(_config(handler, NO_SLEEP), method="GET", path="/orgs")
    assert calls["n"] == 2
