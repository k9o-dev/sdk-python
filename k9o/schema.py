"""
Schema namespace: `client.schema.*`.

Wire mapping (project plane):
  - collections.list(limit=, cursor=)   GET /@<slug>/schema/collections

The list is cursor-paginated and ordered by collection name: pass `meta.cursor.next` of one page as `cursor` of the
next, until it is None.
"""

from __future__ import annotations

from .approvals import check_limit
from .envelope import Envelope
from .errors import KError
from .http import HttpClientConfig, request
from .url_grammar import project_path


class SchemaCollectionsNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self, *, limit: int | None = None, cursor: str | None = None) -> Envelope:
        """List the project's collections by name, one page at a time. `limit` is 1 to 200 (default 50)."""
        if not self._config.project_slug:
            raise ValueError("schema operations require project_slug bound on the client")
        check_limit(limit)
        if cursor is not None and not isinstance(cursor, str):
            raise KError(code="K9O_INVALID_FIELD_VALUE", message="cursor must be a string", context={"cursor": cursor})
        query = {k: v for k, v in {"limit": limit, "cursor": cursor}.items() if v is not None}
        return request(self._config, method="GET", path=project_path(self._config.project_slug, "schema/collections"),
                       query=query or None)


class SchemaNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self.collections = SchemaCollectionsNamespace(config)
