"""client.approvals, client.approval_policies, client.schema.collections: wire shape and client-side validation."""

from __future__ import annotations

import json
from urllib.parse import parse_qsl

import httpx
import pytest

from k9o import KError, create_client

BASE = "https://acme.api.k9o.io"
CRITERIA = {"eq": ["change.table", "orders"]}
PREDICATE = {"gt": ["change.row.amount", 1000]}


def _client(handler=None, **kw):
    seen: list[httpx.Request] = []

    def default(req):
        seen.append(req)
        return httpx.Response(200, json={"data": {}, "meta": {}})

    def recording(req):
        seen.append(req)
        return handler(req)

    c = create_client(base_url=BASE, project_slug=kw.pop("project_slug", "portal"), api_key="k", **kw)
    c.config.transport = httpx.MockTransport(recording if handler else default)
    return c, seen


def _sent(call):
    c, seen = _client()
    call(c)
    reqs = [r for r in seen if r.method != "HEAD"]
    assert len(reqs) == 1
    return reqs[0]


def _body(req):
    return json.loads(req.content) if req.content else None


def _query(req):
    return dict(parse_qsl(req.url.query.decode()))


CASES = [
    (lambda c: c.approvals.list(), "GET", "/@portal/pending-approvals", {}, None),
    (lambda c: c.approvals.list(status="pending_approval", limit=20), "GET", "/@portal/pending-approvals",
     {"status": "pending_approval", "limit": "20"}, None),
    (lambda c: c.approvals.get("apr_1"), "GET", "/@portal/pending-approvals/apr_1", {}, None),
    (lambda c: c.approvals.approve("apr_1"), "POST", "/@portal/pending-approvals/apr_1/approve", {}, {}),
    (lambda c: c.approvals.approve("apr_1", reason="ok"), "POST", "/@portal/pending-approvals/apr_1/approve", {},
     {"reason": "ok"}),
    (lambda c: c.approvals.reject("apr_1", "duplicate"), "POST", "/@portal/pending-approvals/apr_1/reject", {},
     {"reason": "duplicate"}),
    (lambda c: c.approvals.bulk("approve", CRITERIA), "POST", "/@portal/pending-approvals/bulk", {},
     {"action": "approve", "criteria": CRITERIA}),
    (lambda c: c.approvals.bulk("approve", CRITERIA, reason="fine"), "POST", "/@portal/pending-approvals/bulk", {},
     {"action": "approve", "criteria": CRITERIA, "reason": "fine"}),
    (lambda c: c.approvals.bulk("reject", CRITERIA, reason="stale"), "POST", "/@portal/pending-approvals/bulk", {},
     {"action": "reject", "criteria": CRITERIA, "reason": "stale"}),
    (lambda c: c.approval_policies.list(), "GET", "/@portal/approval-policies", {}, None),
    (lambda c: c.approval_policies.create("orders", "update", "queue", PREDICATE), "POST",
     "/@portal/approval-policies", {},
     {"collection": "orders", "operation": "update", "action": "queue", "predicate": PREDICATE}),
    (lambda c: c.approval_policies.delete("apo_1"), "DELETE", "/@portal/approval-policies/apo_1", {}, None),
    (lambda c: c.schema.collections.list(), "GET", "/@portal/schema/collections", {}, None),
    (lambda c: c.schema.collections.list(limit=2, cursor="dGFza3M"), "GET", "/@portal/schema/collections",
     {"limit": "2", "cursor": "dGFza3M"}, None),
]


@pytest.mark.parametrize("call,method,path,query,body", CASES)
def test_wire_shape(call, method, path, query, body):
    req = _sent(call)
    assert req.method == method
    assert req.url.path == path
    assert _query(req) == query
    assert _body(req) == body


def test_ids_are_path_encoded():
    assert _sent(lambda c: c.approvals.get("a/b")).url.raw_path.decode() == "/@portal/pending-approvals/a%2Fb"


def test_response_envelope_is_returned():
    def handler(req):
        return httpx.Response(200, json={"data": {"id": "apr_1", "status": "pending_approval"},
                                         "meta": {"cost": {}}})

    c, _ = _client(handler)
    res = c.approvals.approve("apr_1")
    assert res.data["status"] == "pending_approval"


def test_schema_page_exposes_cursor():
    def handler(req):
        return httpx.Response(200, json={"data": [{"name": "orders", "rowCount": 1}],
                                         "meta": {"cursor": {"next": "b3JkZXJz", "totalCount": None}}})

    c, _ = _client(handler)
    res = c.schema.collections.list(limit=1)
    assert res.data[0]["name"] == "orders"
    assert res.meta.cursor.next == "b3JkZXJz"


def _invalid(call):
    c, seen = _client()
    with pytest.raises(KError) as exc:
        call(c)
    assert exc.value.code == "K9O_INVALID_FIELD_VALUE"
    assert [r for r in seen if r.method != "HEAD"] == []


BAD_LIMITS = [0, 201, -1, 1.5, "10", True]


@pytest.mark.parametrize("limit", BAD_LIMITS)
def test_approvals_list_rejects_bad_limit(limit):
    _invalid(lambda c: c.approvals.list(limit=limit))


@pytest.mark.parametrize("limit", BAD_LIMITS)
def test_schema_list_rejects_bad_limit(limit):
    _invalid(lambda c: c.schema.collections.list(limit=limit))


@pytest.mark.parametrize("limit", [1, 200])
def test_limit_bounds_accepted(limit):
    assert _query(_sent(lambda c: c.approvals.list(limit=limit)))["limit"] == str(limit)


@pytest.mark.parametrize("reason", [None, "", "   ", 5])
def test_reject_needs_reason(reason):
    _invalid(lambda c: c.approvals.reject("apr_1", reason))


@pytest.mark.parametrize("bad", ["", None, 5])
def test_ids_must_be_non_empty_strings(bad):
    _invalid(lambda c: c.approvals.get(bad))
    _invalid(lambda c: c.approvals.approve(bad))
    _invalid(lambda c: c.approvals.reject(bad, "x"))
    _invalid(lambda c: c.approval_policies.delete(bad))


@pytest.mark.parametrize("action", ["", "delete", None, "APPROVE"])
def test_bulk_rejects_bad_action(action):
    _invalid(lambda c: c.approvals.bulk(action, CRITERIA, reason="x"))


@pytest.mark.parametrize("criteria", [None, [], [CRITERIA], "eq", 5])
def test_bulk_criteria_must_be_an_object(criteria):
    _invalid(lambda c: c.approvals.bulk("approve", criteria))


@pytest.mark.parametrize("reason", [None, "", "  "])
def test_bulk_reject_needs_reason(reason):
    _invalid(lambda c: c.approvals.bulk("reject", CRITERIA, reason=reason))


@pytest.mark.parametrize("collection", ["", "1orders", "or-ders", "a b", "x" * 64, None, 5])
def test_policy_rejects_bad_collection(collection):
    _invalid(lambda c: c.approval_policies.create(collection, "update", "queue", PREDICATE))


@pytest.mark.parametrize("collection", ["_orders", "Orders1", "x" * 63])
def test_policy_accepts_valid_collection(collection):
    assert _body(_sent(lambda c: c.approval_policies.create(collection, "insert", "queue", PREDICATE)))["collection"] \
        == collection


@pytest.mark.parametrize("operation", ["", "upsert", None, "UPDATE"])
def test_policy_rejects_bad_operation(operation):
    _invalid(lambda c: c.approval_policies.create("orders", operation, "queue", PREDICATE))


@pytest.mark.parametrize("action", ["", "approve", None])
def test_policy_rejects_bad_action(action):
    _invalid(lambda c: c.approval_policies.create("orders", "update", action, PREDICATE))


@pytest.mark.parametrize("predicate", [None, [], [PREDICATE], "gt", 5, True])
def test_policy_predicate_must_be_an_object(predicate):
    _invalid(lambda c: c.approval_policies.create("orders", "update", "queue", predicate))


def test_requires_project_slug():
    c, _ = _client(project_slug=None)
    for call in (lambda: c.approvals.list(), lambda: c.approval_policies.list(),
                 lambda: c.schema.collections.list()):
        with pytest.raises(ValueError, match="project_slug"):
            call()
