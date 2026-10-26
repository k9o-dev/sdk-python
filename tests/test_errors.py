"""Tests for KError + kerror_from_wire."""

import pytest

from k9o import KError, kerror_from_wire


def test_kerror_constructs_with_required_fields():
    e = KError(code="K9O_INVALID_FIELD_VALUE", message="bad")
    assert e.code == "K9O_INVALID_FIELD_VALUE"
    assert e.message == "bad"
    assert e.context == {}
    assert e.recommendation is None
    assert e.status is None
    assert e.request_id is None


def test_kerror_context_is_frozen():
    e = KError(code="X", message="m", context={"dim": "mau"})
    assert e.context["dim"] == "mau"
    with pytest.raises(TypeError):
        e.context["dim"] = "modified"


def test_kerror_is_exception():
    with pytest.raises(KError) as exc_info:
        raise KError(code="X", message="m")
    assert exc_info.value.code == "X"


def test_kerror_from_wire_full_payload():
    wire = {
        "code": "K9O_TIER_CAP_HIT",
        "message": "cap exceeded",
        "context": {"dimension": "mau", "limit": 1000},
        "recommendation": "upgrade to Ascent",
        "requestId": "req_abc",
    }
    e = kerror_from_wire(wire, 429)
    assert e.code == "K9O_TIER_CAP_HIT"
    assert e.status == 429
    assert e.context == {"dimension": "mau", "limit": 1000}
    assert e.recommendation == "upgrade to Ascent"
    assert e.request_id == "req_abc"


def test_kerror_from_wire_passes_unknown_codes_verbatim():
    e = kerror_from_wire({"code": "K9O_NOVEL_CODE", "message": "y"}, 422)
    assert e.code == "K9O_NOVEL_CODE"
    assert e.status == 422


def test_kerror_from_wire_tolerates_missing_optional_fields():
    e = kerror_from_wire({"code": "X", "message": "y"}, 500)
    assert e.context == {}
    assert e.recommendation is None
    assert e.request_id is None


def test_kerror_from_wire_handles_request_id_snake_case_alt():
    """Some upstreams may send snake_case `request_id` — accept either."""
    e = kerror_from_wire({"code": "X", "message": "y", "request_id": "alt"}, 500)
    assert e.request_id == "alt"
