"""
`client.kibo.vault.secrets.*` — the Kibo vault-secrets surface,
Python parity port of the TS reference `packages/kibo/src/vault.ts` (the
`secrets` object) + `packages/kibo/src/client-factory.ts` (the `client.kibo`
composition shim).

Named `kibo_vault.py` (flat, top-level — NOT inside the `k9o/kibo/` subpackage)
deliberately: `k9o/kibo/` exists only to host the native-FFI `encrypt`/`decrypt`
binding (`k9o/kibo/crypto.py` + the CI-injected `_ffi/` build artifact), and
`k9o/kibo/__init__.py` fails to import in any environment where that artifact
hasn't been built (see `k9o/kibo/crypto.py`) — true today of a raw source
checkout. `vault.secrets` is a plain authenticated REST round-trip with ZERO
crypto SDK-side (exactly like the TS reference's own framing), so it has no
FFI dependency and must not be forced through that fragile import chain just
to reach the `client.kibo.vault.secrets` attribute path. Living here keeps
`import k9o` (and this module) working regardless of whether the native
binding has been built, matching the flat-file convention every other
namespace in this package already uses (`projects.py`, `gate.py`, `audit.py`,
etc. are all flat; only `kibo/` and `barbican/` are subpackages, both solely
because they carry native binaries).

Full family: list / get / create / reveal_challenge / reveal / update /
rotate / move / delete. `region` is optional on every method: the gateway sets
the residency region of every vault call itself and discards a caller-supplied
one; when given, it is still sent (older gateways required it).

Response shapes for `update`/`rotate`/`move` are typed to what the gateway
ACTUALLY returns (live-verified), not the OpenAPI's documented
(and inaccurate for these three) `SecretSummary` — see the per-method
docstrings below.

Like every other namespace in this SDK (`projects.py`, `gate.py`, `policies.py`,
etc.), methods return the raw `Envelope` with wire-shaped (camelCase) dict
`.data` rather than a translated dataclass — `Project`/`_project_from_wire`
in `projects.py` is the one place a per-resource dataclass was attempted and
it is unused dead code, so it is not a convention worth propagating here.
The `SecretSummary` field list (id/name/ownerId/visibility/version/kid/
createdAt/createdBy/updatedAt/updatedBy/rotatedAt/retiredAt/metadata) is
documented in prose on `get`/`create`/`list` below instead.
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from .envelope import Envelope
from .errors import KError
from .http import HttpClientConfig, request
from .url_grammar import project_path


def _require_project_slug(config: HttpClientConfig) -> str:
    """Both `vault.zk_deks` (not yet ported to Python) and `vault.secrets`
    require a project context (member-plane) — mirrors TS
    `requireProjectSlug` in `vault.ts` exactly, including the error code."""
    if not config.project_slug:
        raise KError(
            code="K9O_MISSING_PROJECT_CONTEXT",
            message="client.kibo.vault requires a bound project_slug (member-plane resource)",
            context={},
            recommendation="Pass project_slug= in create_client().",
        )
    return config.project_slug


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


_MAX_GET_PAGES = 20


def _region_query(region: str | None) -> dict[str, str]:
    return {} if region is None else {"region": region}


def _secret_path(project_slug: str, name: str) -> str:
    # `name` is hierarchical (e.g. "db/pw") — the literal "/" must survive as
    # text, not become an extra path segment, so encode it too (safe=""),
    # mirroring TS's `encodeURIComponent(name)`.
    return project_path(project_slug, f"vault/secrets/{quote(name, safe='')}")


def _encode_secret_value(plaintext: str) -> str:
    """UTF-8 base64 encode. The vault-secrets wire `value` field is base64 in
    BOTH directions (live-verified) — this contradicts the OpenAPI's
    plain-language description ("the plaintext to seal") which reads like it
    should be raw. Live-tested: sending a raw (non-base64) `value` on
    create/update is REJECTED as unparseable (`K9O_INVALID_FIELD_VALUE`,
    "Request body could not be parsed."). The caller-facing API here always
    deals in plaintext; base64 is purely a wire-transport detail handled in
    this module, exactly symmetric with `_decode_secret_value` below."""
    return base64.b64encode(plaintext.encode("utf-8")).decode("ascii")


def _decode_secret_value(wire_value: str) -> str:
    """Inverse of `_encode_secret_value` — decodes a revealed wire `value`
    back to plaintext (live-verified: the reveal response's `value` also
    comes back as base64)."""
    return base64.b64decode(wire_value).decode("utf-8")


class SecretsNamespace:
    """`client.kibo.vault.secrets.*` — typed secrets surface (`/@<project_slug>/vault/secrets`).

    `region`: the gateway sets the residency region of every vault call itself and discards a caller-supplied
    `region` query parameter, so it is optional on every method. When given, it is still sent (older gateways
    required it).
    """

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def list(self, *, prefix: str | None = None, cursor: str | None = None, limit: int | None = None) -> Envelope:
        """List secrets (metadata only — never lists ciphertext).
        `GET /@<project_slug>/vault/secrets`.

        `.data` is `{secrets: SecretSummary[], nextCursor: str | None}`.
        """
        slug = _require_project_slug(self._config)
        return request(
            self._config, method="GET", path=project_path(slug, "vault/secrets"),
            query=_clean({"prefix": prefix, "cursor": cursor, "limit": limit}),
        )

    def get(self, name: str, *, region: str | None = None) -> Envelope:
        """Read one secret's metadata (never its value — use `reveal_challenge` + `reveal` for that).

        The vault answers `GET /@<project_slug>/vault/secrets/<name>` only as a reveal: without an
        `X-K9O-Reveal-Challenge` header it refuses with 401 `K9O_REVEAL_CHALLENGE_REQUIRED`. There is no plain
        metadata read on that route, so `get` reads the metadata from the list route: it lists with the exact name
        as prefix and picks the exact match. Raises `KError(K9O_NOT_FOUND, status=404)` when no secret has that
        name. `region` is accepted for symmetry and not sent.

        `.data` is the `SecretSummary`: id, name, ownerId, visibility, version, kid, createdAt, createdBy,
        updatedAt, updatedBy, rotatedAt, retiredAt, metadata.
        """
        cursor: str | None = None
        for _ in range(_MAX_GET_PAGES):
            env = self.list(prefix=name, cursor=cursor, limit=100)
            data = env.data or {}
            for secret in data.get("secrets", []):
                if secret.get("name") == name:
                    return Envelope(data=secret, meta=env.meta)
            cursor = data.get("nextCursor")
            if not cursor:
                break
        raise KError(
            code="K9O_NOT_FOUND",
            message=f"No secret named '{name}' in this project.",
            context={"name": name},
            status=404,
        )

    def create(
        self,
        name: str,
        *,
        value: str,
        region: str | None = None,
        visibility: dict[str, Any] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Envelope:
        """Create a secret under the caller's own auth.
        `POST /@<project_slug>/vault/secrets/<name>` -> the `sec_<base62>` `SecretSummary`.

        `value` is plaintext — base64-encoded onto the wire here (see `_encode_secret_value`).
        """
        slug = _require_project_slug(self._config)
        body = _clean({"value": _encode_secret_value(value), "visibility": visibility, "metadata": metadata})
        return request(self._config, method="POST", path=_secret_path(slug, name),
                       query=_region_query(region), body=body)

    def reveal_challenge(self, name: str, *, region: str | None = None, reason: str | None = None) -> Envelope:
        """Mint a single-use reveal challenge — present it as
        `X-K9O-Reveal-Challenge` on the immediately-following `reveal()`
        call. `POST .../<name>?op=reveal-challenge`.
        `.data` is `{challenge: str, expiresAt: str}`. The optional `reason` is accepted by the gateway and not
        forwarded.
        """
        slug = _require_project_slug(self._config)
        return request(
            self._config, method="POST", path=_secret_path(slug, name),
            query={"op": "reveal-challenge", **_region_query(region)},
            body=_clean({"reason": reason}) or None,
        )

    def reveal(self, name: str, *, challenge: str, region: str | None = None) -> Envelope:
        """Reveal a secret's plaintext value using a single-use challenge
        from `reveal_challenge()`. `GET .../<name>` with
        `X-K9O-Reveal-Challenge`. Decodes the wire's base64 `value` back to
        plaintext (symmetric with `create`'s encode).

        `.data` is `{id, name, version, value (plaintext), revealedAt,
        attestationTier: {urn, operator, verified}}`.
        """
        slug = _require_project_slug(self._config)
        envelope = request(
            self._config, method="GET", path=_secret_path(slug, name),
            query=_region_query(region) or None, headers={"X-K9O-Reveal-Challenge": challenge},
        )
        data = dict(envelope.data)
        data["value"] = _decode_secret_value(data["value"])
        return Envelope(data=data, meta=envelope.meta)

    def update(self, name: str, *, value: str, region: str | None = None,
               metadata: dict[str, str] | None = None) -> Envelope:
        """Update a secret's value (bumps version) — owner-only. `PUT .../<name>`.

        Returns only `{id, name, version}` — not the full `SecretSummary`. Call `get()` after if the rest is
        needed. `value` is plaintext — base64-encoded onto the wire here, same as `create`.
        """
        slug = _require_project_slug(self._config)
        body = _clean({"value": _encode_secret_value(value), "metadata": metadata})
        return request(self._config, method="PUT", path=_secret_path(slug, name),
                       query=_region_query(region) or None, body=body)

    def rotate(self, name: str, *, region: str | None = None) -> Envelope:
        """Rotate a secret's wrapping key (re-wraps under a fresh `kid`;
        content unchanged) — owner-only. `POST .../<name>?op=rotate`.

        `.data` is `{id, name, version, rotatedAt, ledgerSequenceNumber}`.
        """
        slug = _require_project_slug(self._config)
        return request(self._config, method="POST", path=_secret_path(slug, name),
                       query={"op": "rotate", **_region_query(region)})

    def move(self, name: str, *, new_path: str, region: str | None = None) -> Envelope:
        """Move (rename) a secret's hierarchical path — owner-only.
        `POST .../<name>?op=move` with body `{newPath}`.

        `.data` is `{id, name, event}` (`event` is a plain string, e.g. `"SECRET_PATH_CHANGED"`).
        """
        slug = _require_project_slug(self._config)
        return request(
            self._config, method="POST", path=_secret_path(slug, name),
            query={"op": "move", **_region_query(region)}, body={"newPath": new_path},
        )

    def delete(self, name: str, *, region: str | None = None) -> Envelope:
        """Retire a secret — owner-only. `DELETE .../<name>`
        -> `204 No Content` (`.data` is `None`)."""
        slug = _require_project_slug(self._config)
        return request(self._config, method="DELETE", path=_secret_path(slug, name),
                       query=_region_query(region) or None)


class VaultNamespace:
    """`client.kibo.vault.*` — Python port of TS `makeVaultNamespace`
    (`packages/kibo/src/vault.ts`).

    Only `secrets` is implemented here: the F.5 `zk_deks` opaque store/fetch
    surface (`vault.zkDeks.{store,fetch}` in TS) has no Python HTTP-layer
    port yet — out of scope for this change (only `vault-secrets` parity was
    commissioned). Extend this class with a `zk_deks` attribute the same way
    if/when that surface is ported.
    """

    def __init__(self, config: HttpClientConfig) -> None:
        self.secrets = SecretsNamespace(config)


class KiboNamespace:
    """`client.kibo.*` — composes the Kibo (ZK vault) HTTP surfaces onto
    `K9oClient`, mirroring `@k9o/kibo`'s `createKiboClient(config)`
    composition into `@k9o/core` as `client.kibo`
    (`packages/kibo/src/client-factory.ts`).

    The native-FFI `encrypt`/`decrypt` functions (`k9o.kibo.encrypt` /
    `k9o.kibo.decrypt`) stay standalone module-level functions with no
    client-config dependency, matching the TS package's own shape (there,
    `encrypt`/`decrypt` are plain exports from `@k9o/kibo`, not part of
    `KiboClient`/`client.kibo` either — see `client-factory.ts`'s
    `KiboClient = { vault: ... }` type, no `encrypt`/`decrypt` field).
    """

    def __init__(self, config: HttpClientConfig) -> None:
        self.vault = VaultNamespace(config)
