"""``k9o.kibo`` — Zero-Knowledge BYOK/HYOK vault SDK (client-side, Python).

Two surfaces:
  - ``encrypt`` / ``decrypt`` — thin wrappers over the audited
    bound core (piece C, ``kibo-kms-rest-ffi`` via uniffi native bindings).
  - (F.5 ZK-DEK store/fetch composes via the gateway HTTP client, like the TS
    ``@k9o/kibo`` ``vault.zkDeks`` surface.)

Zero crypto in Python: every wrap/unwrap + posture-floor enforcement lives in
the bound core. The native lib + generated uniffi binding under ``_ffi/`` are
build artifacts (generated per platform; gitignored).
"""

from .crypto import encrypt, decrypt
from ._ffi.kibo_kms_rest_ffi import (  # type: ignore[import-not-found]
    EncryptInput,
    DecryptInput,
    EncryptOutput,
    DecryptOutput,
    FfiCredential,
    FfiKeyRef,
    FfiProviderConfig,
    FfiKvPair,
    FfiPosturePolicy,
    FfiAllowedOracleModes,
    FfiPosture,
    FfiStrategy,
    FfiOracleMode,
    FfiAttestationTier,
    FfiMinPosture,
    KmsProvider,
)

__all__ = [
    "encrypt",
    "decrypt",
    "EncryptInput",
    "DecryptInput",
    "EncryptOutput",
    "DecryptOutput",
    "FfiCredential",
    "FfiKeyRef",
    "FfiProviderConfig",
    "FfiKvPair",
    "FfiPosturePolicy",
    "FfiAllowedOracleModes",
    "FfiPosture",
    "FfiStrategy",
    "FfiOracleMode",
    "FfiAttestationTier",
    "FfiMinPosture",
    "KmsProvider",
]
