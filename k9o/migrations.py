"""
Migration lifecycle namespace — `client.migrations.*`.

All routes are member-plane (`/@<projectSlug>/migrations/...`). Python
idiomatic: snake_case + returns Envelope + raises KError.

Migration shape — STRUCTURED
DECLARATIVE DDL, never raw SQL. Every schema change is a typed, key-tagged
operation, so schema drift is impossible at the SDK layer.
Raw SQL is the separate runtime `client.query()` surface, which cannot
create/alter schema.

TIER-2 TYPE MODEL:
  The migration ``Operation`` union is CONTROL-PLANE => typed per tier. Python
  is tier-2: the fixed control-plane shapes (Migration / Operation / ColumnSpec
  / IndexSpec / policy blocks) are modelled as ``TypedDict`` (structural —
  plain ``dict`` at runtime, checked by pyright/mypy). Types are ergonomics +
  serialization, NOT validation — the gateway is the fail-closed source of
  truth. Optional keys use ``NotRequired``; PATCH-y blocks use ``total=False``.

  The ``Operation`` union is KEY-TAGGED (exactly one key set), so each variant
  is its own single-key ``TypedDict`` and ``Operation`` is their ``Union`` —
  the structural analogue of the Go discriminated-struct / TS object union. The
  closed-union property (exactly the 6 frozen ops) is enforced at the wire +
  server validation for all langs; the per-variant TypedDicts give tier-2 its
  compile-time check. FROZEN at 6: no alter_column /
  rename_table / constraint ops at v2; ``rename_column`` is the pending 7th and
  is added in one union bump once its field names are finalised.

  ``encrypted`` is the union ``Literal[True] | EncryptedSpec``: ``True`` is the
  inline-stored shorthand, and the object form opts into ``store``
  ("inline" | "vault") and the D-mode ``searchable`` index. NOTE: ``searchable``
  is NESTED inside the object form — it is NOT a sibling of the column.

  ``type`` stays a ``str`` (the parser-owned column-type vocabulary;
  not a fabricated enum). DYNAMIC data-plane record bodies (``from(...).insert``
  /``update`` payloads) remain the open map ``dict[str, Any]`` — per-collection
  codegen is out of scope.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict, Union
from urllib.parse import quote

try:  # `NotRequired` is stdlib from 3.11; fall back to typing_extensions on 3.10.
    from typing import NotRequired
except ImportError:  # pragma: no cover
    from typing_extensions import NotRequired

from .envelope import Envelope
from .http import HttpClientConfig, request
from .url_grammar import project_path


# --------------------------------------------------------------------------- #
# Structured DDL types (control-plane; TypedDict tier-2).        #
# --------------------------------------------------------------------------- #

ReferentialAction = Literal["CASCADE", "RESTRICT", "SET NULL", "NO ACTION"]


class ColumnReferences(TypedDict):
    """Foreign-key reference on a column — compiles to a REFERENCES clause."""

    collection: str
    on: str
    on_delete: NotRequired[ReferentialAction]
    on_update: NotRequired[ReferentialAction]


class EncryptedSpec(TypedDict):
    """
    Object form of a column's at-rest field encryption. ``store``
    selects "inline" | "vault"; ``searchable`` opts into the D-mode searchable-
    encryption index. NOTE: ``searchable`` is NESTED here — not a sibling of the
    column.
    """

    store: Literal["inline", "vault"]
    searchable: NotRequired[bool]


# `encrypted` is the wire union `true | { store, searchable? }`: bare `True`
# (inline-stored shorthand) OR the object form. Serializes verbatim — `dict`
# bodies pass through the JSON encoder unchanged.
Encrypted = Union[Literal[True], EncryptedSpec]


class ColumnSpec(TypedDict):
    """
    A column definition. ``type`` is the parser-owned column-type vocabulary
    (parser-owned; kept as ``str`` rather than a fabricated enum).
    """

    name: str
    type: str
    primary_key: NotRequired[bool]
    not_null: NotRequired[bool]
    unique: NotRequired[bool]
    default: NotRequired[str]
    references: NotRequired[ColumnReferences]
    encrypted: NotRequired[Encrypted]
    blind_indexed: NotRequired[bool]


class IndexSpec(TypedDict):
    """An index definition. ``name`` defaults to ``<table>_<cols>_idx``."""

    columns: list[str]
    name: NotRequired[str]
    unique: NotRequired[bool]


# --- Operation: KEY-TAGGED union (exactly one key set). One TypedDict per op. #


class CreateTableOp(TypedDict):
    """Payload of a ``create_table`` operation."""

    name: str
    columns: list[ColumnSpec]
    indexes: NotRequired[list[IndexSpec]]


class AddColumnOp(TypedDict):
    """Payload of an ``add_column`` operation."""

    table: str
    column: ColumnSpec


class DropColumnOp(TypedDict):
    """Payload of a ``drop_column`` operation."""

    table: str
    column: str


class AlterTableOp(TypedDict):
    """Payload of an ``alter_table`` operation — the BATCHED column mutation: one
    op carries optional ``add_columns`` + ``drop_columns`` (not separate add/drop
    ops). ``add_columns`` entries are full ``ColumnSpec`` (incl encrypted/
    blind_indexed); ``drop_columns`` is column names. Live in the gateway runner."""

    name: str
    add_columns: NotRequired[list[ColumnSpec]]
    drop_columns: NotRequired[list[str]]


class CreateIndexOp(TypedDict):
    """Payload of a ``create_index`` operation."""

    table: str
    index: IndexSpec


class DropIndexOp(TypedDict):
    """Payload of a ``drop_index`` operation."""

    name: str


class CreateTableOperation(TypedDict):
    create_table: CreateTableOp


class DropTableOperation(TypedDict):
    drop_table: str


class AddColumnOperation(TypedDict):
    add_column: AddColumnOp


class DropColumnOperation(TypedDict):
    drop_column: DropColumnOp


class AlterTableOperation(TypedDict):
    alter_table: AlterTableOp


class CreateIndexOperation(TypedDict):
    create_index: CreateIndexOp


class DropIndexOperation(TypedDict):
    drop_index: DropIndexOp


# A single declarative DDL operation. The v2 set is these 7. `alter_table` is the
# BATCHED column mutation (live in the gateway runner).
# `rename_column` remains a pending future op — added in one union bump when it
# lands.
Operation = Union[
    CreateTableOperation,
    DropTableOperation,
    AddColumnOperation,
    DropColumnOperation,
    AlterTableOperation,
    CreateIndexOperation,
    DropIndexOperation,
]


# --- Policy section. ----------------------------------------- #


class ActionRule(TypedDict, total=False):
    """Declarative authz/relationship rule (compiles to RLS USING + WITH CHECK)."""

    rule: Any


# `as` is a Python keyword, so the class form can't name it; the functional
# TypedDict form keeps the wire key EXACTLY `as` (matches Go json:"as" / TS).
RelationshipSpec = TypedDict(
    "RelationshipSpec",
    {
        "collection": str,
        "on": str,
        "as": str,
        "type": NotRequired[Literal["inner", "left"]],
    },
)


class CollectionActions(TypedDict, total=False):
    select: ActionRule
    insert: ActionRule
    update: ActionRule
    delete: ActionRule


class CollectionPolicy(TypedDict, total=False):
    references: list[RelationshipSpec]
    actions: CollectionActions


class StorageBucketActions(TypedDict, total=False):
    read: ActionRule
    upload: ActionRule
    delete: ActionRule
    list: ActionRule


class StorageBucketPolicy(TypedDict, total=False):
    public: bool
    actions: StorageBucketActions


class MigrationStorage(TypedDict, total=False):
    buckets: dict[str, StorageBucketPolicy]


class MigrationPolicy(TypedDict, total=False):
    collections: dict[str, CollectionPolicy]
    storage: MigrationStorage


class Migration(TypedDict):
    """
    A versioned, checksummed unit of structured DDL. ``up`` applies
    the change; ``down`` reverses it. Both are operation arrays.
    """

    version: int
    slug: str
    up: list[Operation]
    down: list[Operation]
    policy: NotRequired[MigrationPolicy]


class AppliedMigration(TypedDict):
    """Applied-migration record returned by ``list`` + ``get``."""

    version: int
    slug: str
    checksum: str
    appliedAt: str


class PendingMigration(TypedDict):
    """Pending migration record returned by ``list_pending``."""

    pendingId: str
    version: int
    slug: str
    checksum: str
    submittedAt: str
    submittedBy: str


# --------------------------------------------------------------------------- #
# Namespace.                                                                   #
# --------------------------------------------------------------------------- #


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise ValueError("migrations operations require project_slug bound on the client")
    return config.project_slug


class MigrationsNamespace:
    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def apply(self, migrations: list[Migration]) -> Envelope:
        """Apply migrations immediately (PROJECT_ADMIN minimum)."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST",
                       path=project_path(slug, "migrations/apply"), body={"migrations": migrations})

    def list(self) -> Envelope:
        """List applied migrations on the project."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, "migrations"))

    def get(self, version: int | str) -> Envelope:
        """Get a single applied migration by version."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET",
                       path=project_path(slug, f"migrations/{quote(str(version), safe='')}"))

    def queue(self, migrations: list[Migration]) -> Envelope:
        """Queue migrations for maker-checker approval"""
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST",
                       path=project_path(slug, "migrations/queue"), body={"migrations": migrations})

    def list_pending(self) -> Envelope:
        """List pending (queued, not yet approved) migrations."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="GET", path=project_path(slug, "migrations/pending"))

    def apply_pending(self, pending_id: str) -> Envelope:
        """Approve + apply a pending migration."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST",
                       path=project_path(slug, f"migrations/pending/{quote(pending_id, safe='')}/apply"))

    def reject_pending(self, pending_id: str, reason: str | None = None) -> Envelope:
        """Reject a pending migration (transitions to rejected; does not apply)."""
        slug = _require_project_slug(self._config)
        body = {"reason": reason} if reason is not None else None
        return request(self._config, method="POST",
                       path=project_path(slug, f"migrations/pending/{quote(pending_id, safe='')}/reject"), body=body)

    def delete_pending(self, pending_id: str) -> Envelope:
        """Delete a pending migration from the queue."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="DELETE",
                       path=project_path(slug, f"migrations/pending/{quote(pending_id, safe='')}"))
