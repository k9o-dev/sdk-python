"""Wiring test for k9o.kibo encrypt/decrypt against the REAL bound core (native
uniffi binding). Exercises the wasm-equivalent native path WITHOUT a live KMS,
via the posture-floor path (rejected pre-KMS). Full round-trip needs real KMS
creds (staging conformance ZK step)."""

import asyncio

import pytest

from k9o.errors import KError
from k9o.kibo import (
    encrypt,
    EncryptInput,
    FfiCredential,
    FfiKeyRef,
    FfiProviderConfig,
    FfiPosture,
    FfiAttestationTier,
    FfiPosturePolicy,
    FfiMinPosture,
    KmsProvider,
)


def _floor_violation_input() -> EncryptInput:
    # byok requested, but the project floor requires hyok -> byok < hyok.
    return EncryptInput(
        provider=KmsProvider.AWS_KMS,
        posture=FfiPosture.BYOK,
        strategy=None,
        oracle_mode=None,
        kms_cred=FfiCredential(secret="dummy-token", expires_at_unix_secs=9_999_999_999),
        key_ref=FfiKeyRef(version=1, external_ref="arn:aws:kms:us-east-1:000000000000:key/abc-123"),
        provider_config=FfiProviderConfig(aws_region="us-east-1", vault_address=None),
        attestation_tier=FfiAttestationTier.SOFTWARE,
        encryption_context=[],
        plaintext=b"hi",
        posture_policy=FfiPosturePolicy(min_custody_posture=FfiMinPosture.HYOK, allowed_oracle_modes=None),
    )


def test_posture_floor_violation_maps_to_kerror() -> None:
    async def run() -> None:
        with pytest.raises(KError) as ei:
            await encrypt(_floor_violation_input())
        k = ei.value
        assert k.code == "K9O_CRYPTO_POSTURE_FLOOR_VIOLATION"
        assert k.context.get("dimension") == "custody_posture"

    asyncio.run(run())
