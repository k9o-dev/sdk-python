"""
Function lifecycle namespace — `client.functions.*`.

Member-plane routes. Wire mapping:
  - upload_artifact(data, kind)   POST   /@<slug>/functions/artifacts  (raw bytes)
  - deploy(...)                   POST   /@<slug>/functions
  - list()                        GET    /@<slug>/functions
  - get(name)                     GET    /@<slug>/functions/<name>
  - delete(name)                  DELETE /@<slug>/functions/<name>
  - invoke(name, payload)         POST   /@<slug>/functions/<name>/invoke   body {payload, ...}

A function's bytes are uploaded first (`upload_artifact` returns the content-addressed `artifactKey`); `deploy`
references that artifact.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import project_path


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("functions operations require project_slug bound on the client")
    return config.project_slug


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


_ARTIFACT_CONTENT_TYPES = {"wasm": "application/wasm", "tar": "application/x-tar"}


class FunctionsNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def upload_artifact(self, data: bytes | bytearray | memoryview, kind: Literal["wasm", "tar"]) -> Envelope:
        """Upload a function artifact; `data` is `{artifactKey}` to pass to `deploy`.

        `POST /@<slug>/functions/artifacts` with the raw bytes: a WebAssembly module for the gateway tier
        (`kind="wasm"`, up to 16 MiB) or an OCI image archive for the sandbox tier (`kind="tar"`, up to 256 MiB).
        Uploading the same bytes again returns the same key.
        """
        slug = _require_project_slug(self._config)
        if kind not in _ARTIFACT_CONTENT_TYPES:
            raise ValueError('kind must be "wasm" or "tar"')
        return request(
            self._config,
            method="POST",
            path=project_path(slug, "functions/artifacts"),
            multipart={"content": bytes(data)},
            headers={"content-type": _ARTIFACT_CONTENT_TYPES[kind]},
        )

    def deploy(self, *, name: str, runtime: str, tier: str, artifact_key: str, version: str,
               description: str | None = None) -> Envelope:
        """Deploy or redeploy a function from an uploaded artifact. Returns the record with status `deploying`.

        Body keys are the gateway's: `name` (1 to 128 chars), `runtime` ("bun", "python", "go", ...),
        `tier` ("gateway" runs WebAssembly in the gateway; "sandbox" runs an OCI image archive),
        `artifactKey`, `version` (1 to 64 chars) and optional `description`.
        """
        slug = _require_project_slug(self._config)
        body = _clean({"name": name, "runtime": runtime, "tier": tier, "artifactKey": artifact_key,
                       "version": version, "description": description})
        return request(self._config, method="POST", path=project_path(slug, "functions"), body=body)

    def list(self, *, limit: int | None = None, cursor: str | None = None, status: str | None = None,
             tier: str | None = None, source: str | None = None) -> Envelope:
        """List deployed functions (cursor pagination)."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, "functions"),
                       query=_clean({"limit": limit, "cursor": cursor, "status": status, "tier": tier,
                                     "source": source}))

    def get(self, name: str) -> Envelope:
        """Get a function by name."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, f"functions/{quote(name, safe='')}"))

    def delete(self, name: str) -> Envelope:
        """Retire a function (the name enters a 24h cooldown)."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="DELETE", path=project_path(slug, f"functions/{quote(name, safe='')}"))

    def invoke(self, name: str, payload: Any = None, *, background: bool | None = None,
               delegation: dict[str, Any] | None = None, on_behalf_of: str | None = None,
               confined_to: str | None = None) -> Envelope:
        """Invoke a function. `payload` is sent as the body's `payload` field and passed to the runtime verbatim.

        Optional controls (the gateway's `background`, `delegation`, `onBehalfOf`, `confinedTo`) are sent only
        when given. `payload=None` sends no `payload` key.
        """
        slug = _require_project_slug(self._config)
        body: dict[str, Any] = {}
        if payload is not None:
            body["payload"] = payload
        body.update(_clean({"background": background, "delegation": delegation, "onBehalfOf": on_behalf_of,
                            "confinedTo": confined_to}))
        return request(self._config, method="POST",
                       path=project_path(slug, f"functions/{quote(name, safe='')}/invoke"), body=body)
