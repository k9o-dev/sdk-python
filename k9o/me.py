"""
Operator-self namespace — `client.me.*`.

Cross-org; no tenant context required (org-plane routes under /me).
Sub-namespaces: profile / sessions / api_tokens. Wire mapping:
  - profile.get / update      GET / PATCH  /me
  - sessions.list             GET          /me/sessions
  - sessions.revoke(id)       POST         /auth/sessions/<id>/revoke
  - sessions.revoke_all()     POST         /me/sessions/revoke-all
  - api_tokens.list / create / delete   GET / POST / DELETE  /me/api-tokens[/<id>]
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import org_path


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class _Profile:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def get(self) -> Envelope:
        return request(self._config, method="GET", path=org_path("me"))

    def update(self, *, display_name: str | None = None, locale: str | None = None,
               timezone: str | None = None) -> Envelope:
        """PATCH /me — only the fields given are sent."""
        return request(self._config, method="PATCH", path=org_path("me"),
                       body=_clean({"displayName": display_name, "locale": locale, "timezone": timezone}))


class _Sessions:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self) -> Envelope:
        return request(self._config, method="GET", path=org_path("me/sessions"))

    def revoke(self, session_id: str) -> Envelope:
        """POST /auth/sessions/<session_id>/revoke."""
        return request(self._config, method="POST",
                       path=org_path(f"auth/sessions/{quote(session_id, safe='')}/revoke"))

    def revoke_all(self) -> Envelope:
        """POST /me/sessions/revoke-all."""
        return request(self._config, method="POST", path=org_path("me/sessions/revoke-all"))


class _ApiTokens:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self) -> Envelope:
        return request(self._config, method="GET", path=org_path("me/api-tokens"))

    def create(self, *, label: str, scope_manifest: dict[str, Any], ttl_seconds: int | None = None) -> Envelope:
        """POST /me/api-tokens. `data` carries the token record and its one-time `plaintext`.

        `scope_manifest` is the gateway's object: `operations` (list of "read" | "write" | "admin"), `projects`,
        `resourceClasses`, `collections`, `cidrs`. A `None` or absent entry leaves that axis unrestricted; pass
        `{}` for an unrestricted token. `ttl_seconds` is 60 to 31536000.
        """
        return request(self._config, method="POST", path=org_path("me/api-tokens"),
                       body=_clean({"label": label, "scopeManifest": scope_manifest, "ttlSeconds": ttl_seconds}))

    def delete(self, token_id: str) -> Envelope:
        return request(self._config, method="DELETE", path=org_path(f"me/api-tokens/{quote(token_id, safe='')}"))


class MeNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self.profile = _Profile(config)
        self.sessions = _Sessions(config)
        self.api_tokens = _ApiTokens(config)
