"""
Project lifecycle namespace — `client.projects.*`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import org_path, project_path, validate_slug


@dataclass
class Project:
    """Project record (Python snake_case at boundary)."""

    id: str
    slug: str
    name: str
    custody_mode: Literal["managed", "byok", "hyok"]
    created_at: str
    updated_at: str | None
    org_id: str


def _project_from_wire(d: dict) -> Project:
    return Project(
        id=d["id"],
        slug=d["slug"],
        name=d["name"],
        custody_mode=d.get("custodyMode", "managed"),
        created_at=d["createdAt"],
        updated_at=d.get("updatedAt"),
        org_id=d.get("orgId", ""),
    )


class ProjectsNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self) -> Envelope:
        """List projects accessible to the caller."""
        return request(self._config, method="GET", path=org_path("projects"))

    def create(self, *, slug: str, name: str, custody_mode: str | None = None) -> Envelope:
        """Create a new project under the caller's active org."""
        validate_slug(slug, "project")
        body: dict = {"slug": slug, "name": name}
        if custody_mode is not None:
            body["custodyMode"] = custody_mode
        return request(self._config, method="POST", path=org_path("projects"), body=body)

    def get(self, slug: str) -> Envelope:
        """Get a project by slug."""
        validate_slug(slug, "project")
        return request(self._config, method="GET", path=project_path(slug, "project"))

    def update(self, slug: str, *, name: str | None = None) -> Envelope:
        """Update mutable fields of a project."""
        validate_slug(slug, "project")
        patch: dict = {}
        if name is not None:
            patch["name"] = name
        return request(self._config, method="PATCH", path=project_path(slug, "project"), body=patch)
