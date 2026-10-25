"""
Gate (Identity-Aware Kernel) namespace — `client.gate.*`.

Python idiomatic shape: snake_case methods (sign_up / sign_in / sign_out /
whoami / refresh_token / verify_session / hosted) + raise K9o::KError on error.
"""

from __future__ import annotations

from typing import Any

from .envelope import Envelope
from .errors import KError
from .http import HttpClientConfig, request, request_async
from .url_grammar import project_path


class GateNamespace:
    """`client.gate.*` — Gate IAK auth surface.

    Requires `project_slug` bound on the client (project-scoped auth).
    """

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def _require_project(self) -> str:
        if not self._config.project_slug:
            raise KError(
                code="K9O_MISSING_PROJECT_CONTEXT",
                message="client.gate operations require project_slug bound on the client",
                context={},
                recommendation="Pass project_slug= in create_client().",
            )
        return self._config.project_slug

    def sign_up(self, *, email: str, password: str, display_name: str | None = None) -> Envelope:
        """Create a new end-user identity for the configured project."""
        slug = self._require_project()
        body: dict[str, Any] = {"email": email, "password": password}
        if display_name is not None:
            body["displayName"] = display_name
        return request(self._config, method="POST", path=project_path(slug, "gate/signup"), body=body)

    def sign_in(self, *, email: str, password: str) -> Envelope:
        """Sign in an existing end-user with email + password."""
        slug = self._require_project()
        return request(
            self._config,
            method="POST",
            path=project_path(slug, "gate/signin"),
            body={"email": email, "password": password},
        )

    def sign_out(self, *, refresh_token: str | None = None) -> Envelope:
        """Sign out the current session (revoke refresh token)."""
        slug = self._require_project()
        body: dict[str, Any] = {}
        if refresh_token is not None:
            body["refreshToken"] = refresh_token
        return request(self._config, method="POST", path=project_path(slug, "gate/signout"), body=body)

    def whoami(self) -> Envelope:
        """Print the active end-user identity."""
        slug = self._require_project()
        return request(self._config, method="GET", path=project_path(slug, "gate/whoami"))

    def refresh_token(self, *, refresh_token: str) -> Envelope:
        """Rotate the access token using the refresh token."""
        slug = self._require_project()
        return request(
            self._config,
            method="POST",
            path=project_path(slug, "gate/refresh"),
            body={"refreshToken": refresh_token},
        )

    def verify_session(self) -> Envelope:
        """Verify the current session is valid (does not throw on invalid; returns valid=false)."""
        slug = self._require_project()
        return request(self._config, method="GET", path=project_path(slug, "gate/verify"))

    def hosted(self) -> Envelope:
        """Hosted sign-in page URL + WebAuthn rp id: `data.signInUrl`, `data.rpId`.

        Unauthenticated and cacheable; no Authorization header or cookie is sent
        even when an api_key is configured. An unknown org, a deleted project and
        a non-Gate project all raise the same 404 K9O_PROJECT_NOT_FOUND.
        """
        slug = self._require_project()
        return request(
            self._config, method="GET", path=project_path(slug, "gate/hosted"), authenticated=False
        )

    async def hosted_async(self) -> Envelope:
        """Async variant of `hosted()`."""
        slug = self._require_project()
        return await request_async(
            self._config, method="GET", path=project_path(slug, "gate/hosted"), authenticated=False
        )
