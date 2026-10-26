"""ZK encrypt/decrypt — thin wrapper over the bound crypto core
(``kibo-kms-rest-ffi``, piece C) compiled to a native lib via uniffi.

ZERO crypto here: every wrap/unwrap, envelope framing, posture-floor
enforcement, and KMS round-trip lives in the audited Rust core. This layer
only forwards the typed input to the generated binding and maps the core's
``ZkFfiUniffiError`` -> the SDK's ``KError`` (snake_case + raise-KError idiom,
Python SDK shape). The F.5 ``zk_deks`` store/fetch surface (envelope
persistence) is separate + decoupled.
"""

from __future__ import annotations

from ..errors import KError
from ._ffi import kibo_kms_rest_ffi as _ffi


def _to_kerror(e: Exception) -> KError:
    """Map the bound core's uniffi error -> KError, pass-through on code.

    Variants (``ZkFfiUniffiError``): ``Platform{code, detail}``,
    ``UpstreamKms{detail}`` (the customer's own KMS failed -- outside the SDK namespace
    boundary, not a ``K9O_*`` code), ``PostureViolation{code, detail,
    dimension, requested, declared}``.
    """
    code = getattr(e, "code", None)
    message = getattr(e, "detail", None) or str(e)
    dimension = getattr(e, "dimension", None)
    if dimension is not None:
        return KError(
            code=code or "K9O_CRYPTO_POSTURE_FLOOR_VIOLATION",
            message=message,
            context={
                "dimension": dimension,
                "requested": getattr(e, "requested", None),
                "declared": getattr(e, "declared", None),
            },
        )
    if code is not None:
        return KError(code=code, message=message)
    # No platform code => the customer's own KMS errored (upstream/vendor).
    return KError(code="UPSTREAM_KMS_ERROR", message=message)


async def encrypt(input: "_ffi.EncryptInput") -> "_ffi.EncryptOutput":
    """Encrypt ``input.plaintext`` via the customer KMS, client-side. Returns the
    opaque ZKFE envelope (store via ``zk_deks`` F.5 or keep it -- it is
    meaningless to the platform)."""
    try:
        return await _ffi.zk_encrypt(input)
    except _ffi.ZkFfiUniffiError as e:  # type: ignore[attr-defined]
        raise _to_kerror(e) from e


async def decrypt(input: "_ffi.DecryptInput") -> "_ffi.DecryptOutput":
    """Decrypt a ZKFE ``input.envelope``. ``strategy``, ``attestation_tier``,
    and ``encryption_context`` MUST match the encrypt-time values (AAD-bound,
    never recovered from the envelope)."""
    try:
        return await _ffi.zk_decrypt(input)
    except _ffi.ZkFfiUniffiError as e:  # type: ignore[attr-defined]
        raise _to_kerror(e) from e
