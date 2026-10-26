"""
Project lifecycle namespace — `client.projects.*`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import org_path, validate_slug


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


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
    """`client.projects.*` — org-plane routes (`/projects`); the client needs an org context."""

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self) -> Envelope:
        """GET /projects — list projects accessible to the caller."""
        return request(self._config, method="GET", path=org_path("projects"))

    def create(
        self,
        *,
        display_name: str,
        slug: str | None = None,
        product_scope: str | None = None,
        region: str | None = None,
        default_project_region: str | None = None,
        custody_mode: str | None = None,
        processing_contexts: Sequence[str] | None = None,
        exec_seam_confined: bool | None = None,
        showroom_vertical: str | None = None,
        persona: str | None = None,
        showroom_locale: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Envelope:
        """POST /projects — create a project under the caller's active org.

        Body keys are the gateway's: `displayName` (required, 1 to 128 chars), optional `slug` (the gateway derives
        one from the display name when omitted), `productScope` ("core" | "kibo"), `region`,
        `defaultProjectRegion`, `custodyMode` ("PLATFORM_MANAGED" | "SKR" | "BYOK" | "HYOK"),
        `processingContexts`, `execSeamConfined`, `showroomVertical`, `persona`, `showroomLocale`,
        `idempotencyKey` (makes a retried create return the first result).
        """
        if slug is not None:
            validate_slug(slug, "project")
        body = _clean({
            "displayName": display_name,
            "slug": slug,
            "productScope": product_scope,
            "region": region,
            "defaultProjectRegion": default_project_region,
            "custodyMode": custody_mode,
            "processingContexts": None if processing_contexts is None else list(processing_contexts),
            "execSeamConfined": exec_seam_confined,
            "showroomVertical": showroom_vertical,
            "persona": persona,
            "showroomLocale": showroom_locale,
            "idempotencyKey": idempotency_key,
        })
        return request(self._config, method="POST", path=org_path("projects"), body=body)

    def get(self, slug: str) -> Envelope:
        """GET /projects/<slug> — get a project by slug."""
        validate_slug(slug, "project")
        return request(self._config, method="GET", path=org_path(f"projects/{quote(slug, safe='')}"))

    def update(
        self,
        slug: str,
        *,
        new_slug: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        region: str | None = None,
        product_scope: str | None = None,
        soft_delete_retention_days: int | None = None,
        processing_contexts: Sequence[str] | None = None,
    ) -> Envelope:
        """PATCH /projects/<slug> — update mutable fields. Only the fields given are sent.

        `new_slug` is sent as the body's `slug` (a rename); `slug` selects the project.
        """
        validate_slug(slug, "project")
        if new_slug is not None:
            validate_slug(new_slug, "project")
        patch = _clean({
            "slug": new_slug,
            "displayName": display_name,
            "description": description,
            "region": region,
            "productScope": product_scope,
            "softDeleteRetentionDays": soft_delete_retention_days,
            "processingContexts": None if processing_contexts is None else list(processing_contexts),
        })
        return request(self._config, method="PATCH", path=org_path(f"projects/{quote(slug, safe='')}"), body=patch)
