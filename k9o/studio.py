"""
Studio namespace — `client.studio.*` — workflows and dashboards.

Python idiomatic shape: snake_case method names; returns Envelope on 2xx; raises KError on non-2xx. Methods take
the resource ids positionally + filters/bodies as keyword args. project_slug is bound on the client config.
Create/update bodies are dicts carrying the gateway's wire keys (camelCase, except a workflow action's
`action_type`).

6 K9O_WORKFLOW_* error codes + 2 K9O_DASHBOARD_* codes surface through the existing kerror_from_wire mapping
(open code-space; narrow on `e.code`).

Wire mapping (project-plane): workflows `/@<slug>/workflows[/<id>]`, runs `/@<slug>/workflows/<id>/runs[/<runId>]`,
dashboards `/@<slug>/dashboards[/<id>]` (+ `/pin`, `/unpin`). `workflows.trigger` is
`POST /@<slug>/workflows/<id>/runs` with body `{triggerContext}`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import project_path

# Closed enums, documented as module constants.
WORKFLOW_TRIGGER_TYPES = (
    "view_row_event",
    "form_submission",
    "scheduled",
    "manual",
    "webhook",
)
WORKFLOW_ACTION_TYPES = (
    "write_collection",
    "read_collection",
    "invoke_function",
    "invoke_extension",
    "llm_inference",
    "send_notification",
    "http_request",
    "approval_step",
    "branch",
)
WIDGET_TYPES = (
    "kpi_card",
    "bar_chart",
    "line_chart",
    "pie_chart",
    "data_table",
    "filter_dropdown",
    "filter_date_range",
    "text_panel",
    "workflow_status",
    "form_launcher",
)

WORKFLOW_ERROR_CODES = {
    "NOT_FOUND": "K9O_WORKFLOW_NOT_FOUND",
    "TRIGGER_INVALID": "K9O_WORKFLOW_TRIGGER_INVALID",
    "ACTION_INVALID": "K9O_WORKFLOW_ACTION_INVALID",
    "RUN_NOT_FOUND": "K9O_WORKFLOW_RUN_NOT_FOUND",
    "RUN_NOT_CANCELLABLE": "K9O_WORKFLOW_RUN_NOT_CANCELLABLE",
    "WEBHOOK_SIGNATURE_INVALID": "K9O_WORKFLOW_WEBHOOK_SIGNATURE_INVALID",
}
DASHBOARD_ERROR_CODES = {
    "NOT_FOUND": "K9O_DASHBOARD_NOT_FOUND",
    "WIDGET_INVALID": "K9O_DASHBOARD_WIDGET_INVALID",
}


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("studio operations require project_slug bound on the client")
    return config.project_slug


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """Drop None values so optional filters/fields are omitted."""
    return {k: v for k, v in d.items() if v is not None}


class WorkflowRunsNamespace:
    """`client.studio.workflows.runs.*`."""

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self, workflow_id: str, *, limit: int | None = None, cursor: str | None = None) -> Envelope:
        """GET .../workflows/<id>/runs — newest first; the route pages with `limit` and `cursor` only."""
        slug = _require_project_slug(self._config)
        return request(
            self._config,
            method="GET",
            path=project_path(slug, f"workflows/{quote(workflow_id, safe='')}/runs"),
            query=_clean({"limit": limit, "cursor": cursor}),
        )

    def read(self, workflow_id: str, run_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(
            self._config,
            method="GET",
            path=project_path(slug, f"workflows/{quote(workflow_id, safe='')}/runs/{quote(run_id, safe='')}"),
        )

    def cancel(self, workflow_id: str, run_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(
            self._config,
            method="POST",
            path=project_path(slug, f"workflows/{quote(workflow_id, safe='')}/runs/{quote(run_id, safe='')}/cancel"),
        )


class WorkflowsNamespace:
    """`client.studio.workflows.*`."""

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config
        self.runs = WorkflowRunsNamespace(config)

    def list(self, *, status: str | None = None, limit: int | None = None, cursor: str | None = None) -> Envelope:
        """GET .../workflows; the route filters by `status` and pages with `limit` and `cursor`."""
        slug = _require_project_slug(self._config)
        return request(
            self._config,
            method="GET",
            path=project_path(slug, "workflows"),
            query=_clean({"status": status, "limit": limit, "cursor": cursor}),
        )

    def create(self, workflow: dict[str, Any]) -> Envelope:
        """POST .../workflows. Keys are the gateway's: `name`, `triggerType`, `triggerConfig`, `actions`
        (required), `description`, `status`, `rbacBinding`. Each action is `{index, action_type, config}`."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST", path=project_path(slug, "workflows"), body=workflow)

    def read(self, workflow_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, f"workflows/{quote(workflow_id, safe='')}"))

    def update(self, workflow_id: str, updates: dict[str, Any]) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="PATCH", path=project_path(slug, f"workflows/{quote(workflow_id, safe='')}"), body=updates)

    def delete(self, workflow_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="DELETE", path=project_path(slug, f"workflows/{quote(workflow_id, safe='')}"))

    def trigger(self, workflow_id: str, trigger_context: dict[str, Any] | None = None) -> Envelope:
        """Manual-trigger a run (trigger_type='manual' only). The context is sent as `{triggerContext}`."""
        slug = _require_project_slug(self._config)
        return request(
            self._config,
            method="POST",
            path=project_path(slug, f"workflows/{quote(workflow_id, safe='')}/runs"),
            body={"triggerContext": trigger_context if trigger_context is not None else {}},
        )


class DashboardsNamespace:
    """`client.studio.dashboards.*`."""

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self, *, status: str | None = None, pinned_only: bool | None = None, limit: int | None = None, cursor: str | None = None) -> Envelope:
        """GET .../dashboards; `pinned_only=True` sends the gateway's `pinnedOnly=true`."""
        slug = _require_project_slug(self._config)
        return request(
            self._config,
            method="GET",
            path=project_path(slug, "dashboards"),
            query=_clean({"status": status, "pinnedOnly": None if pinned_only is None else str(pinned_only).lower(),
                          "limit": limit, "cursor": cursor}),
        )

    def create(self, dashboard: dict[str, Any]) -> Envelope:
        """POST .../dashboards. Keys are the gateway's: `name` (required), `description`, `status`, `layoutGrid`,
        `widgets`, `filterConfig`, `rbacBinding`. Each widget uses the gateway's snake_case keys
        (`widget_type`, `data_source: {mode, ...}`, `title`, `config`)."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST", path=project_path(slug, "dashboards"), body=dashboard)

    def read(self, dashboard_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, f"dashboards/{quote(dashboard_id, safe='')}"))

    def update(self, dashboard_id: str, updates: dict[str, Any]) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="PATCH", path=project_path(slug, f"dashboards/{quote(dashboard_id, safe='')}"), body=updates)

    def delete(self, dashboard_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="DELETE", path=project_path(slug, f"dashboards/{quote(dashboard_id, safe='')}"))

    def pin(self, dashboard_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST", path=project_path(slug, f"dashboards/{quote(dashboard_id, safe='')}/pin"))

    def unpin(self, dashboard_id: str) -> Envelope:
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST", path=project_path(slug, f"dashboards/{quote(dashboard_id, safe='')}/unpin"))


class StudioNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self.workflows = WorkflowsNamespace(config)
        self.dashboards = DashboardsNamespace(config)
