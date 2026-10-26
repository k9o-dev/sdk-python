"""
Gate (Identity-Aware Kernel) namespace — `client.gate.*`.

Python idiomatic shape: snake_case methods (sign_up / sign_in / sign_out /
whoami / refresh_token) + raise KError on error.
"""

from __future__ import annotations

from typing import Any

from .envelope import Envelope
from .errors import KError
from .http import HttpClientConfig, request
from .url_grammar import project_path


class GateNamespace:
    """`client.gate.*` — Gate auth surface.

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

    def sign_out(self, *, refresh_token: str) -> Envelope:
        """Sign out the session by revoking its refresh token (the gateway requires `refreshToken`; a sign-out
        without one is a 400)."""
        slug = self._require_project()
        return request(self._config, method="POST", path=project_path(slug, "gate/signout"),
                       body={"refreshToken": refresh_token})

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
