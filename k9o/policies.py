"""
Policy bundle lifecycle namespace — `client.policies.*`.

Member-plane routes. Wire mapping:
  - current()                  GET    /@<slug>/policy             (active policy)
  - list(status=)              GET    /@<slug>/policies
  - create(policy=, ...)       POST   /@<slug>/policies           (draft bundle)
  - validate(policy=, ...)     POST   /@<slug>/policies/validate  (lint without persist)
  - get(id)                    GET    /@<slug>/policies/<id>
  - update(id, policy=, ...)   PATCH  /@<slug>/policies/<id>
  - delete(id)                 DELETE /@<slug>/policies/<id>
  - publish(id)                POST   /@<slug>/policies/<id>/publish

`policy` is the policy document: sections keyed by resource kind (`collections`, `storage`, `tools`, `functions`,
`secrets`, `streams`, `analytics`); other keys are allowed.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import project_path


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("policies operations require project_slug bound on the client")
    return config.project_slug


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class PoliciesNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def current(self) -> Envelope:
        """Read the currently-active policy bundle (data is None when none active)."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, "policy"))

    def list(self, *, status: str | None = None) -> Envelope:
        """List all policy bundles (draft, published, deactivated); `status` filters."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, "policies"),
                       query=_clean({"status": status}))

    def create(self, *, policy: dict[str, Any], rules: Any = None, editor_mode: str | None = None) -> Envelope:
        """Create a draft policy bundle. `editor_mode` is "visual" | "json" | "unspecified"."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST", path=project_path(slug, "policies"),
                       body=_clean({"policy": policy, "rules": rules, "editorMode": editor_mode}))

    def validate(self, *, policy: dict[str, Any], rules: Any = None) -> Envelope:
        """Lint a candidate policy document without persisting it."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST", path=project_path(slug, "policies/validate"),
                       body=_clean({"policy": policy, "rules": rules}))

    def get(self, bundle_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, f"policies/{quote(bundle_id, safe='')}"))

    def update(self, bundle_id: str, *, policy: dict[str, Any], rules: Any = None,
               editor_mode: str | None = None) -> Envelope:
        """Replace a draft bundle's policy document. Published bundles cannot be patched."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="PATCH",
                       path=project_path(slug, f"policies/{quote(bundle_id, safe='')}"),
                       body=_clean({"policy": policy, "rules": rules, "editorMode": editor_mode}))

    def delete(self, bundle_id: str) -> Envelope:
        """Delete a draft bundle. Published bundles cannot be deleted."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="DELETE",
                       path=project_path(slug, f"policies/{quote(bundle_id, safe='')}"))

    def publish(self, bundle_id: str, *, acknowledge_self_lockout: bool | None = None) -> Envelope:
        """Publish a draft bundle (makes it the active policy).

        `acknowledge_self_lockout` is sent as the gateway's `acknowledgeSelfLockout` only when given.
        """
        slug = _require_project_slug(self._config)
        body = _clean({"acknowledgeSelfLockout": acknowledge_self_lockout})
        return request(self._config, method="POST",
                       path=project_path(slug, f"policies/{quote(bundle_id, safe='')}/publish"),
                       body=body or None)
