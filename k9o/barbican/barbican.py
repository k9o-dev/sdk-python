"""Thin wrapper over the bound ``k9o-keep-core`` engine (native, via uniffi).

Sync throughout -- the core has no async fn (unlike ``k9o.kibo``'s crypto,
which calls a network KMS), and the rest of the ``k9o`` Python SDK is sync
(``requests``/``httpx``-style), so there is no async-for-future-proofing need
here the way there is in the TS SDK (JS network calls force async; Python
doesn't have that constraint -- a future hosted-tier escalation can stay sync).
"""

from __future__ import annotations

import time
from typing import Any

from ..errors import KError
from ._ffi import k9o_keep_core_ffi_uniffi as _ffi


def _map_error(e: Exception, stage: str = "ruleset") -> KError:
    """Map the bound core's ``KeepError`` -> ``KError``. ``KeepError.RulesetInvalid``
    is the only variant today (a refused ruleset, manifest or key manifest); the
    core's closed reason token (``unknown_kid`` / ``signature_invalid`` /
    ``signature_non_canonical`` / ``version_stale`` / ``malformed`` / ... or an
    unknown-severity message) rides in ``context.reason``, and ``context.stage``
    says whether it came from the ruleset or the key manifest.
    """
    reason = getattr(e, "reason", None)
    if reason is not None:
        return KError(
            code="K9O_BARBICAN_RULESET_INVALID",
            message=str(e),
            context={"reason": reason, "stage": stage},
        )
    return KError(code="K9O_BARBICAN_WASM_ERROR", message=str(e))


class OutputFilter:
    """A streaming output redactor. Buffer-and-scan-before-flush: never emits a
    byte the core has not cleared (no RST-after-leak)."""

    def __init__(self, handle: Any) -> None:
        self._handle = handle

    def push(self, chunk: str) -> str:
        """Feed a chunk; returns the cleared (redacted) prefix safe to emit now."""
        return self._handle.push(chunk)

    def finish(self) -> str:
        """Flush the residual buffer (also scanned) at end of stream."""
        return self._handle.finish()

    def report(self) -> Any:
        """Leak report (counts only -- never the leaked values): an object with
        ``emails``, ``secrets``, ``markers``, ``total``."""
        return self._handle.report()


class Barbican:
    """The free, embeddable L2 guardrail. See the package docstring for the
    claim boundary."""

    def __init__(
        self,
        *,
        fail_open: bool = False,
        leet: bool = True,
        decode_depth: int = 0,
    ) -> None:
        """``decode_depth`` of 0 uses the core default (3) -- a bounded base64/
        leetspeak de-obfuscation depth (decode-bomb guard)."""
        self._core = _ffi.KeepCore(
            _ffi.KeepConfig(fail_open=fail_open, leet=leet, decode_depth=decode_depth)
        )

    def load_ruleset(self, ruleset_version: int, rules: list[dict[str, str]]) -> int:
        """Load a static ruleset bundled with your package (Mode-A path: provenance
        is vouched for by your package, so signature verification is skipped --
        the core still enforces anti-rollback, never loading a version <= the
        current one). ``rules`` = ``[{"id", "pattern", "severity"}]``
        (severity one of low|medium|high|critical). Returns the accepted version.
        """
        blob = _ffi.KeepRulesetBlob(
            ruleset_version=ruleset_version,
            rules=[
                _ffi.KeepRule(id=r["id"], pattern=r["pattern"], severity=r["severity"])
                for r in rules
            ],
        )
        try:
            return self._core.load_ruleset_unsigned(blob)
        except _ffi.KeepError as e:  # type: ignore[attr-defined]
            raise _map_error(e) from e

    def load_key_manifest(self, jws: str, now_secs: int | None = None) -> int:
        """Load a Barbican key manifest (compact JWS, ``typ k9o.barbican.keys.v1``).
        The core checks it against the root key compiled into it and, only if it
        verifies, REPLACES the trusted ruleset-signing keys with the ones it lists.
        A refusal (wrong signer, rollback, a key changing its public key, a
        malformed entry) raises ``K9O_BARBICAN_RULESET_INVALID`` with
        ``context.stage == "key_manifest"`` and leaves the trusted keys unchanged.
        Returns the manifest ``sequence``."""
        try:
            return self._core.load_key_manifest(
                jws, int(time.time()) if now_secs is None else now_secs
            )
        except _ffi.KeepError as e:  # type: ignore[attr-defined]
            raise _map_error(e, "key_manifest") from e

    def verify_manifest(self, jws: str) -> Any:
        """Verify a ruleset manifest (compact JWS) under a trusted key and return
        its authenticated fields (``ruleset_version``, ``signing_key_kid``,
        ``artifact_hash``, ``artifact_url``, ``valid_until``)."""
        try:
            return self._core.verify_manifest(jws)
        except _ffi.KeepError as e:  # type: ignore[attr-defined]
            raise _map_error(e) from e

    def load_ruleset_signed(
        self,
        ruleset_version: int,
        rules: list[dict[str, str]],
        signing_key_kid: str,
        signature: bytes,
        created_at: int = 0,
    ) -> int:
        """Load a signed ruleset. The core verifies the Ed25519 signature ITSELF,
        over its own canonical bytes, under a key from the loaded key manifest:
        there is no key or verifier to pass. Any failure (no key manifest loaded,
        unknown key, bad or non-canonical signature, stale version, malformed
        rules) raises ``K9O_BARBICAN_RULESET_INVALID`` with ``context.reason`` and
        leaves the current ruleset running. Returns the accepted version."""
        try:
            return self._core.load_ruleset_signed(self._signed_blob(ruleset_version, rules, signing_key_kid, signature, created_at))
        except _ffi.KeepError as e:  # type: ignore[attr-defined]
            raise _map_error(e) from e

    def ruleset_digest(
        self,
        ruleset_version: int,
        rules: list[dict[str, str]],
        signing_key_kid: str,
        signature: bytes,
        created_at: int = 0,
    ) -> str:
        """Lowercase hex SHA-256 of a ruleset's canonical signing bytes -- the value
        a manifest's ``artifact_hash`` names. A digest only; it decides no trust."""
        try:
            return self._core.ruleset_digest(self._signed_blob(ruleset_version, rules, signing_key_kid, signature, created_at))
        except _ffi.KeepError as e:  # type: ignore[attr-defined]
            raise _map_error(e) from e

    @staticmethod
    def _signed_blob(ruleset_version, rules, signing_key_kid, signature, created_at) -> Any:
        return _ffi.KeepSignedRulesetBlob(
            ruleset_version=ruleset_version,
            rules=[
                _ffi.KeepRule(id=r["id"], pattern=r["pattern"], severity=r["severity"])
                for r in rules
            ],
            signing_key_kid=signing_key_kid,
            signature=bytes(signature),
            created_at=created_at,
        )

    @property
    def key_manifest_sequence(self) -> int:
        """The ``sequence`` of the key manifest in force (0 before one is loaded)."""
        return self._core.key_manifest_sequence()

    @property
    def signed_floor(self) -> int:
        """The highest VERIFIED ruleset version loaded (0 = none): the anti-rollback floor for signed
        updates. A refresh compares a published version against this, not the version in force."""
        return self._core.signed_floor()

    @property
    def active_ruleset_is_signed(self) -> bool:
        """Whether the ruleset in force came from a verified load. False when none is loaded, or when
        ``load_ruleset`` (unsigned, host-vouched) replaced a verified one."""
        return self._core.active_ruleset_is_signed()

    def trusted_kids(self) -> list[str]:
        """The signing ``kid`` s the loaded key manifest currently trusts, sorted."""
        return self._core.trusted_kids()

    def deprecated_kids(self) -> list[str]:
        """The trusted ``kid`` s the key manifest flags ``deprecated``, sorted."""
        return self._core.deprecated_kids()

    @staticmethod
    def uses_test_trust_root() -> bool:
        """``False`` on every shipped build. ``True`` means this binding trusts the
        PUBLISHED TEST root and must never be used outside tests."""
        return _ffi.uses_test_trust_root()

    def inspect(self, text: str, *, waypoint_class: str | None = None) -> Any:
        """Inspect an input (normalize -> deny -> local verdict). Obfuscation is
        peeled BEFORE matching, so static deny-lists aren't defeated by trivial
        tricks. ``waypoint_class`` is the manifest's meter hint -- it NEVER gates
        the decision. Returns the verdict object (``decision``, ``reason``,
        ``matched``, ``schema_valid``, ``waypoint_class_hint``, ``fail_mode``,
        ``ruleset_version``, ``core_version``)."""
        return self._core.inspect_input(text, waypoint_class)

    def classify(self, text: str) -> str:
        """Local L3 stand-in classification (``"clear"|"suspicious"|"malicious"``).
        No receipt -- a classification is not an enforcement decision."""
        return self._core.classify_local(text)

    def create_output_filter(self) -> OutputFilter:
        """Open an output stream-filter bound to the active ruleset's exfil
        markers."""
        return OutputFilter(self._core.output_filter())

    @property
    def core_version(self) -> str:
        """The bound core's semver (audit anchor; rides every verdict too)."""
        return self._core.core_version()
