"""
`client.query(sql, params)` and `client.search(collection, column=..., q=...)`.

Wire mapping (project-plane):
  - query  -> POST /@<slug>/query   body {sql, params?}   -> Envelope(data=[row, ...])
  - search -> GET  /@<slug>/data/<collection>?textSearch=<column>:<q>...   (the select builder's `text_search`)

`params` is a list (positional, bound to `$1, $2, ...`; the SQL is sent as written) or a dict of named values
(`:name` placeholders are rewritten to `$n` here and the values become the positional list). Values are bound by
the database, never interpolated into the SQL text.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

from .data import FromBuilder
from .envelope import Envelope
from .errors import KError
from .http import HttpClientConfig, request, request_async
from .url_grammar import project_path

_IDENT_START = re.compile(r"[A-Za-z_]")
_IDENT_CHAR = re.compile(r"[A-Za-z0-9_]")
_DOLLAR_TAG = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def _invalid(message: str, **context: Any) -> KError:
    return KError(code="K9O_INVALID_FIELD_VALUE", message=message, context=context)


def _check_value(value: Any, where: str) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)) and math.isfinite(value):
        return value
    raise _invalid(f"{where} must be a string, number, boolean or None; serialise anything else (for example as JSON text) first")


def translate_named_params(sql: str, named: Mapping[str, Any]) -> tuple[str, list[Any]]:
    """Rewrite `:name` placeholders to `$n`.

    Skips quoted text, comments, dollar-quoted strings and `::` casts. Returns the new SQL and the positional values.
    """
    order: list[str] = []
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if c == "'" or (c in "Ee" and nxt == "'" and not (i > 0 and _IDENT_CHAR.match(sql[i - 1]))):
            escapes = c != "'"
            j = i + 2 if escapes else i + 1
            while j < n:
                if escapes and sql[j] == "\\":
                    j += 2
                    continue
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : min(j + 1, n)])
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < n:
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : min(j + 1, n)])
            i = j + 1
        elif c == "-" and nxt == "-":
            j = sql.find("\n", i)
            if j == -1:
                j = n
            out.append(sql[i:j])
            i = j
        elif c == "/" and nxt == "*":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if sql.startswith("/*", j):
                    depth += 1
                    j += 2
                elif sql.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            out.append(sql[i:j])
            i = j
        elif c == "$":
            m = _DOLLAR_TAG.match(sql, i)
            if m is not None:
                close = sql.find(m.group(0), i + len(m.group(0)))
                end = n if close == -1 else close + len(m.group(0))
                out.append(sql[i:end])
                i = end
            else:
                out.append(c)
                i += 1
        elif c == ":" and nxt == ":":
            out.append("::")
            i += 2
        elif c == ":" and nxt and _IDENT_START.match(nxt) and not (i > 0 and _IDENT_CHAR.match(sql[i - 1])):
            j = i + 2
            while j < n and _IDENT_CHAR.match(sql[j]):
                j += 1
            name = sql[i + 1 : j]
            if name not in order:
                if name not in named:
                    raise _invalid(f"no value for :{name}", name=name)
                order.append(name)
            out.append(f"${order.index(name) + 1}")
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out), [_check_value(named[name], f"the value for :{name}") for name in order]


def _slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("query requires project_slug bound on the client")
    return config.project_slug


def _prepare(config: HttpClientConfig, sql: str, params: Sequence[Any] | Mapping[str, Any] | None) -> tuple[str, dict]:
    slug = _slug(config)
    text = sql
    values: list[Any] = []
    if isinstance(params, Mapping):
        text, values = translate_named_params(sql, params)
    elif params is not None:
        values = [_check_value(v, f"params[{i}]") for i, v in enumerate(params)]
    body: dict[str, Any] = {"sql": text}
    if values:
        body["params"] = values
    return project_path(slug, "query"), body


class QueryMixin:
    """`query` and `search` on the client root."""

    _config: HttpClientConfig

    def query(self, sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None) -> Envelope:
        """POST /@<slug>/query — run one read-only SQL statement; `data` is the list of rows.

        A list binds positionally to `$1, $2, ...`; a dict binds `:name` placeholders.
        """
        path, body = _prepare(self._config, sql, params)
        return request(self._config, method="POST", path=path, body=body)

    async def query_async(self, sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None) -> Envelope:
        path, body = _prepare(self._config, sql, params)
        return await request_async(self._config, method="POST", path=path, body=body)

    def _search_builder(
        self,
        collection: str,
        column: str,
        q: str,
        language: str | None,
        type: str | None,
        limit: int | None,
        cursor: str | None,
    ):
        kwargs: dict[str, Any] = {}
        if language is not None:
            kwargs["language"] = language
        if type is not None:
            kwargs["type"] = type
        builder = FromBuilder(self._config, collection).select().text_search(column, q, **kwargs)
        if limit is not None:
            builder.limit(limit)
        if cursor is not None:
            builder.cursor(cursor)
        return builder

    def search(
        self,
        collection: str,
        *,
        column: str,
        q: str,
        language: str | None = None,
        type: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Envelope:
        """Full-text search over one text column of a collection, best matches first.

        Sugar over `from_(collection).select().text_search(column, q, ...)`; `limit` and `cursor` page the result.
        """
        return self._search_builder(collection, column, q, language, type, limit, cursor).execute()

    async def search_async(
        self,
        collection: str,
        *,
        column: str,
        q: str,
        language: str | None = None,
        type: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Envelope:
        return await self._search_builder(collection, column, q, language, type, limit, cursor).execute_async()
