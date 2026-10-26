"""`client.query`, `client.search`, `select().text_search` / `vector_search`: wire shape, shared vectors, validation."""

import json
from urllib.parse import urlsplit, parse_qsl

import httpx
import pytest

from k9o import KError, create_client, translate_named_params

OK = {"data": [{"id": "u1"}], "meta": {"rawQuery": {"intent": "read", "rowCount": 1}}}


def _client(cap):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200)
        cap.setdefault("calls", []).append(request)
        return httpx.Response(200, json=OK)

    c = create_client(base_url="https://acme.api.k9o.io", project_slug="demo", api_key="k")
    c._config.transport = httpx.MockTransport(handler)
    return c


def _query(req):
    return dict(parse_qsl(urlsplit(str(req.url)).query))


VECTORS = [
    ("SELECT * FROM users WHERE data->>'role' = :role", {"role": "admin"},
     "SELECT * FROM users WHERE data->>'role' = $1", ["admin"]),
    ("SELECT :a, :b, :a", {"a": 1, "b": 2}, "SELECT $1, $2, $1", [1, 2]),
    ("SELECT ':not_a_param', \":also_not\", x::int FROM t WHERE y = :y", {"y": True},
     "SELECT ':not_a_param', \":also_not\", x::int FROM t WHERE y = $1", [True]),
    ("SELECT 'it''s :no' , :v -- :comment\nFROM t", {"v": None},
     "SELECT 'it''s :no' , $1 -- :comment\nFROM t", [None]),
    ("SELECT /* :c /* :d */ :e */ :f", {"f": 1}, "SELECT /* :c /* :d */ :e */ $1", [1]),
    ("SELECT $$ :x $$, $q$ :y $q$, :z", {"z": "s"}, "SELECT $$ :x $$, $q$ :y $q$, $1", ["s"]),
    ("SELECT arr[1:2], a:b, :n", {"n": 5}, "SELECT arr[1:2], a:b, $1", [5]),
]


@pytest.mark.parametrize("sql,named,out,params", VECTORS, ids=[f"vector{i + 1}" for i in range(len(VECTORS))])
def test_translate_shared_vectors(sql, named, out, params):
    assert translate_named_params(sql, named) == (out, params)


def test_vector8_missing_value():
    with pytest.raises(KError) as e:
        translate_named_params("SELECT :missing", {})
    assert e.value.code == "K9O_INVALID_FIELD_VALUE"
    assert ":missing" in e.value.message


def test_vector9_non_bindable_value():
    with pytest.raises(KError) as e:
        translate_named_params("SELECT :a", {"a": {}})
    assert e.value.code == "K9O_INVALID_FIELD_VALUE"


def test_extra_keys_ignored_and_escape_string():
    assert translate_named_params("SELECT E'a\\' :x', :y", {"y": 1, "z": 2}) == ("SELECT E'a\\' :x', $1", [1])


class TestQuery:
    def test_named_params_post_rewritten_sql(self):
        cap = {}
        r = _client(cap).query("SELECT * FROM users WHERE data->>'role' = :role", {"role": "admin"})
        req = cap["calls"][0]
        assert req.method == "POST"
        assert req.url.path == "/@demo/query"
        assert json.loads(req.content) == {"sql": "SELECT * FROM users WHERE data->>'role' = $1", "params": ["admin"]}
        assert r.data == [{"id": "u1"}]

    def test_vector10_list_params_unchanged(self):
        cap = {}
        _client(cap).query("SELECT $1", ["x"])
        assert json.loads(cap["calls"][0].content) == {"sql": "SELECT $1", "params": ["x"]}

    def test_vector11_no_params_key(self):
        cap = {}
        _client(cap).query("SELECT 1")
        assert json.loads(cap["calls"][0].content) == {"sql": "SELECT 1"}

    def test_bad_list_value_raises_before_request(self):
        cap = {}
        with pytest.raises(KError) as e:
            _client(cap).query("SELECT $1", [{}])
        assert e.value.code == "K9O_INVALID_FIELD_VALUE"
        assert "calls" not in cap

    def test_missing_name_raises_before_request(self):
        cap = {}
        with pytest.raises(KError):
            _client(cap).query("SELECT :nope", {"a": 1})
        assert "calls" not in cap


class TestTextAndVectorSearch:
    def test_text_search_defaults_omitted(self):
        cap = {}
        _client(cap).from_("articles").select().text_search("body", "climate resilience").limit(5).execute()
        q = _query(cap["calls"][0])
        assert q == {"textSearch": "body:climate resilience", "limit": "5"}

    def test_text_search_language_and_type(self):
        cap = {}
        _client(cap).from_("articles").select().text_search("body", "a b", language="french", type="websearch").execute()
        q = _query(cap["calls"][0])
        assert q["textSearchLanguage"] == "french"
        assert q["textSearchType"] == "websearch"

    def test_vector_search_wire(self):
        cap = {}
        _client(cap).from_("articles").select().vector_search("embedding", [0.1, 0.2], metric="dot", limit=10).execute()
        q = _query(cap["calls"][0])
        assert q == {"vectorSearch": "embedding:[0.1,0.2]", "vectorMetric": "dot", "vectorLimit": "10"}

    def test_vector_search_defaults_omitted(self):
        cap = {}
        _client(cap).from_("articles").select().vector_search("embedding", [1, 2]).execute()
        assert _query(cap["calls"][0]) == {"vectorSearch": "embedding:[1,2]"}

    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.text_search("bad col", "x"),
            lambda s: s.text_search("body", ""),
            lambda s: s.text_search("body", "x", language="fr-ench"),
            lambda s: s.text_search("body", "x", type="fuzzy"),
            lambda s: s.vector_search("embedding", []),
            lambda s: s.vector_search("embedding", ["a"]),
            lambda s: s.vector_search("embedding", [1], limit=1001),
            lambda s: s.vector_search("embedding", [1], limit=0),
            lambda s: s.vector_search("embedding", [1], metric="manhattan"),
        ],
    )
    def test_validation(self, call):
        s = _client({}).from_("articles").select()
        with pytest.raises(KError) as e:
            call(s)
        assert e.value.code == "K9O_INVALID_FIELD_VALUE"


class TestSearch:
    def test_full_text_paged(self):
        cap = {}
        r = _client(cap).search("articles", column="body", q="climate resilience", language="french", limit=5, cursor="c1")
        req = cap["calls"][0]
        assert req.method == "GET"
        assert req.url.path == "/@demo/data/articles"
        assert _query(req) == {"textSearch": "body:climate resilience", "textSearchLanguage": "french", "limit": "5", "cursor": "c1"}
        assert r.data == [{"id": "u1"}]

    def test_bad_column_raises_before_request(self):
        cap = {}
        with pytest.raises(KError) as e:
            _client(cap).search("articles", column="bad col", q="x")
        assert e.value.code == "K9O_INVALID_FIELD_VALUE"
        assert "calls" not in cap
