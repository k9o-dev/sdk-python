"""
Data-plane DSL, Python idiomatic shape:

    response = k9o.from_("posts").select()
    for row in response.data:
        print(row)

`from` is a Python keyword so the method is `from_("collection")`. Returns a chainable filter builder that resolves
to the Envelope on `.execute()` (sync) or `await .execute_async()`.

For ergonomic parity with the JS shape (where the builder is awaited
directly), Python's builder supports `__iter__` returning the data
list when used as an iterable AND `.execute()` to get the full
Envelope. Most consumers use `.execute()` explicitly for clarity.
"""

from __future__ import annotations

from typing import Any, Sequence
from urllib.parse import quote

from .envelope import Envelope
from .errors import KError
from .http import HttpClientConfig, request, request_async
from .url_grammar import project_path


_FILTER_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "in", "notIn", "like", "ilike", "is"}


class _QueryBuilder:
    """Shared filter/page state across verb builders."""

    def __init__(self) -> None:
        self._filters: list[tuple[str, str, Any]] = []
        self._limit: int | None = None
        self._cursor: str | None = None
        self._count: str | None = None

    def eq(self, column: str, value: Any) -> "_QueryBuilder":
        self._filters.append((column, "eq", value))
        return self

    def neq(self, column: str, value: Any) -> "_QueryBuilder":
        self._filters.append((column, "neq", value))
        return self

    def gt(self, column: str, value: Any) -> "_QueryBuilder":
        self._filters.append((column, "gt", value))
        return self

    def gte(self, column: str, value: Any) -> "_QueryBuilder":
        self._filters.append((column, "gte", value))
        return self

    def lt(self, column: str, value: Any) -> "_QueryBuilder":
        self._filters.append((column, "lt", value))
        return self

    def lte(self, column: str, value: Any) -> "_QueryBuilder":
        self._filters.append((column, "lte", value))
        return self

    def in_(self, column: str, values: Sequence[Any]) -> "_QueryBuilder":
        self._filters.append((column, "in", list(values)))
        return self

    def not_in(self, column: str, values: Sequence[Any]) -> "_QueryBuilder":
        self._filters.append((column, "notIn", list(values)))
        return self

    def like(self, column: str, pattern: str) -> "_QueryBuilder":
        self._filters.append((column, "like", pattern))
        return self

    def ilike(self, column: str, pattern: str) -> "_QueryBuilder":
        self._filters.append((column, "ilike", pattern))
        return self

    def is_(self, column: str, value: str) -> "_QueryBuilder":
        # value must be "null" | "true" | "false"
        self._filters.append((column, "is", value))
        return self

    def filter(self, column: str, op: str, value: Any) -> "_QueryBuilder":
        if op not in _FILTER_OPS:
            raise KError(
                code="K9O_INVALID_FIELD_VALUE",
                message=f'unknown filter op "{op}"; valid: {sorted(_FILTER_OPS)}',
                context={"op": op},
            )
        self._filters.append((column, op, value))
        return self

    def limit(self, n: int) -> "_QueryBuilder":
        self._limit = n
        return self

    def cursor(self, opaque: str) -> "_QueryBuilder":
        self._cursor = opaque
        return self

    def count(self, mode: str) -> "_QueryBuilder":
        # mode: "none" | "exact" | "estimated"
        self._count = mode
        return self

    def _to_query(self) -> dict[str, Any]:
        q: dict[str, Any] = {}
        for col, op, val in self._filters:
            if isinstance(val, list):
                q[col] = f"{op}.({','.join(_wire(v) for v in val)})"
            else:
                q[col] = f"{op}.{_wire(val)}"
        if self._limit is not None:
            q["limit"] = self._limit
        if self._cursor is not None:
            q["cursor"] = self._cursor
        if self._count is not None:
            q["count"] = self._count
        return q


def _wire(value: Any) -> str:
    """Filter value as the gateway reads it: booleans are lower-case `true` / `false` (Python's `str(True)` is `True`)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _collection_path(config: HttpClientConfig, collection: str) -> str:
    if not config.project_slug:
        raise KError(
            code="K9O_MISSING_PROJECT_CONTEXT",
            message="data-plane operations require project_slug to be bound on the client",
            context={"collection": collection},
            recommendation="Pass project_slug= in create_client(); or use a project-scoped sub-client.",
        )
    import re

    if not re.match(r"^[a-z][a-z0-9_-]{0,62}$", collection):
        raise KError(
            code="K9O_INVALID_FIELD_VALUE",
            message=f'collection name "{collection}" does not match required format',
            context={"collection": collection},
            recommendation="Lowercase letters/digits/underscores/hyphens; start with letter; 1-63 chars.",
        )
    return project_path(config.project_slug, f"data/{collection}")


class SelectBuilder(_QueryBuilder):
    """SELECT query builder. Call `.execute()` to issue the request."""

    def __init__(self, config: HttpClientConfig, collection: str) -> None:
        super().__init__()
        self._config = config
        self._collection = collection

    def execute(self) -> Envelope:
        return request(
            self._config,
            method="GET",
            path=_collection_path(self._config, self._collection),
            query=self._to_query(),
        )

    async def execute_async(self) -> Envelope:
        return await request_async(
            self._config,
            method="GET",
            path=_collection_path(self._config, self._collection),
            query=self._to_query(),
        )


class UpdateBuilder(_QueryBuilder):
    def __init__(self, config: HttpClientConfig, collection: str, patch: dict[str, Any]) -> None:
        super().__init__()
        self._config = config
        self._collection = collection
        self._patch = patch

    def _resolve_id(self) -> str:
        for col, op, val in self._filters:
            if col == "id" and op == "eq":
                return str(val)
        raise KError(
            code="K9O_INVALID_FIELD_VALUE",
            message="update() requires .eq('id', ...) filter; changing many rows in one call is not supported",
            context={"collection": self._collection},
            recommendation="Chain .eq('id', 'rec_…') before .execute(); to change several rows, call update once per id.",
        )

    def execute(self) -> Envelope:
        id_val = self._resolve_id()
        return request(
            self._config,
            method="PATCH",
            path=f"{_collection_path(self._config, self._collection)}/{quote(str(id_val), safe='')}",
            body=self._patch,
        )


class DeleteBuilder(_QueryBuilder):
    def __init__(self, config: HttpClientConfig, collection: str) -> None:
        super().__init__()
        self._config = config
        self._collection = collection

    def _resolve_id(self) -> str:
        for col, op, val in self._filters:
            if col == "id" and op == "eq":
                return str(val)
        raise KError(
            code="K9O_INVALID_FIELD_VALUE",
            message="delete() requires .eq('id', ...) filter; deleting many rows in one call is not supported",
            context={"collection": self._collection},
        )

    def execute(self) -> Envelope:
        id_val = self._resolve_id()
        return request(
            self._config,
            method="DELETE",
            path=f"{_collection_path(self._config, self._collection)}/{quote(str(id_val), safe='')}",
        )


class FromBuilder:
    """Terminal-verb builder returned by `k9o.from_(collection)`."""

    def __init__(self, config: HttpClientConfig, collection: str) -> None:
        self._config = config
        self._collection = collection

    def select(self) -> SelectBuilder:
        return SelectBuilder(self._config, self._collection)

    def insert(self, record: dict[str, Any]) -> Envelope:
        """Insert a single record; returns Envelope with inserted record + meta."""
        return request(
            self._config,
            method="POST",
            path=_collection_path(self._config, self._collection),
            body=record,
        )

    def update(self, patch: dict[str, Any]) -> UpdateBuilder:
        return UpdateBuilder(self._config, self._collection, patch)

    def delete(self) -> DeleteBuilder:
        return DeleteBuilder(self._config, self._collection)
