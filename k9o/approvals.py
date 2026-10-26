"""
Approvals namespaces: `client.approvals.*` (the pending-change queue) and `client.approval_policies.*` (the rules that
decide which writes are queued).

Wire mapping (project plane):
  - approvals.list(status=, limit=)                    GET    /@<slug>/pending-approvals
  - approvals.get(id)                                  GET    /@<slug>/pending-approvals/<id>
  - approvals.approve(id, reason=)                     POST   /@<slug>/pending-approvals/<id>/approve
  - approvals.reject(id, reason)                       POST   /@<slug>/pending-approvals/<id>/reject
  - approvals.bulk(action, criteria, reason=)          POST   /@<slug>/pending-approvals/bulk
  - approval_policies.list()                           GET    /@<slug>/approval-policies
  - approval_policies.create(collection, operation, action, predicate)
                                                       POST   /@<slug>/approval-policies
  - approval_policies.delete(id)                       DELETE /@<slug>/approval-policies/<id>

`approvals.list` is not paginated: it returns the newest `limit` changes (1 to 200, default 50). Project admins and
auditors see the whole queue; other members see only the changes they proposed.

`approve` can answer 200 with `status` still `pending_approval`: your approval is recorded and more approvers are
needed. `bulk` skips rows that fail without a report, so compare `affected_ids` with what you intended.
Arguments are checked before any request; a bad value raises KError `K9O_INVALID_FIELD_VALUE`.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .envelope import Envelope
from .errors import KError
from .http import HttpClientConfig, request
from .url_grammar import project_path

_COLLECTION_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
_OPERATIONS = ("insert", "update", "delete")
_POLICY_ACTIONS = ("auto_approve", "queue")


def _invalid(message: str, **context: Any) -> KError:
    return KError(code="K9O_INVALID_FIELD_VALUE", message=message, context=context)


def _require_project_slug(config: HttpClientConfig, what: str) -> str:
    if not config.project_slug:
        raise ValueError(f"{what} operations require project_slug bound on the client")
    return config.project_slug


def _require_id(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid(f"{what} id must be a non-empty string")
    return quote(value, safe="")


def _require_reason(reason: Any) -> str:
    if not isinstance(reason, str) or not reason.strip():
        raise _invalid("reason is required and must be a non-empty string")
    return reason


def _require_predicate(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid(f"{field} must be a predicate object")
    return value


def check_limit(limit: Any) -> None:
    """Shared by every list that takes `limit`: a whole number from 1 to 200."""
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 200):
        raise _invalid("limit must be a whole number from 1 to 200", limit=limit)


class ApprovalsNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def _path(self, tail: str = "") -> str:
        return project_path(_require_project_slug(self._config, "approvals"), "pending-approvals" + tail)

    def list(self, *, status: str | None = None, limit: int | None = None) -> Envelope:
        """List pending changes, newest first. Not paginated: only `limit` (1 to 200, default 50) caps the result."""
        check_limit(limit)
        query = {k: v for k, v in {"status": status, "limit": limit}.items() if v is not None}
        return request(self._config, method="GET", path=self._path(), query=query or None)

    def get(self, id: str) -> Envelope:
        """One pending change. Members who are not queue admins can read only their own."""
        return request(self._config, method="GET", path=self._path("/" + _require_id(id, "approval")))

    def approve(self, id: str, *, reason: str | None = None) -> Envelope:
        """Approve a pending change. Read `status` on the answer: `pending_approval` means more approvers are needed."""
        seg = _require_id(id, "approval")
        return request(self._config, method="POST", path=self._path(f"/{seg}/approve"),
                       body={} if reason is None else {"reason": reason})

    def reject(self, id: str, reason: str) -> Envelope:
        """Reject a pending change. `reason` is required and must not be empty."""
        seg = _require_id(id, "approval")
        return request(self._config, method="POST", path=self._path(f"/{seg}/reject"),
                       body={"reason": _require_reason(reason)})

    def bulk(self, action: str, criteria: dict[str, Any], reason: str | None = None) -> Envelope:
        """Approve or reject every pending change matching `criteria` (a predicate object).

        Rows that fail are skipped without a report: compare `affectedIds` with what you intended.
        `reason` is required when `action` is `reject`.
        """
        if action not in ("approve", "reject"):
            raise _invalid('action must be "approve" or "reject"', action=action)
        body: dict[str, Any] = {"action": action, "criteria": _require_predicate(criteria, "criteria")}
        if action == "reject":
            body["reason"] = _require_reason(reason)
        elif reason is not None:
            body["reason"] = reason
        return request(self._config, method="POST", path=self._path("/bulk"), body=body)


class ApprovalPoliciesNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def _path(self, tail: str = "") -> str:
        return project_path(_require_project_slug(self._config, "approval_policies"), "approval-policies" + tail)

    def list(self) -> Envelope:
        """All policies, oldest first. The first matching policy for a write decides."""
        return request(self._config, method="GET", path=self._path())

    def create(self, collection: str, operation: str, action: str, predicate: dict[str, Any]) -> Envelope:
        """Create a policy. Identical policies are not de-duplicated."""
        if not isinstance(collection, str) or not _COLLECTION_RE.match(collection):
            raise _invalid("collection must match ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$", collection=collection)
        if operation not in _OPERATIONS:
            raise _invalid('operation must be "insert", "update" or "delete"', operation=operation)
        if action not in _POLICY_ACTIONS:
            raise _invalid('action must be "auto_approve" or "queue"', action=action)
        body = {"collection": collection, "operation": operation, "action": action,
                "predicate": _require_predicate(predicate, "predicate")}
        return request(self._config, method="POST", path=self._path(), body=body)

    def delete(self, id: str) -> Envelope:
        """Delete a policy; the answer is `{"id": ...}`."""
        return request(self._config, method="DELETE", path=self._path("/" + _require_id(id, "policy")))
