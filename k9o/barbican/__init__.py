"""``k9o.barbican`` — free, embeddable L2 Keep guardrail (Python).

Unicode-normalize -> Aho-Corasick deny over a signed ruleset -> buffer-and-
scan output stream-filter. A thin wrapper over the audited ``k9o-keep-core``
engine, compiled to a native lib via uniffi (mirrors the ``k9o.kibo`` crypto
wrapper's FFI shape). ZERO security logic here: every normalization pass,
deny match, verdict, and output redaction is the core's; this layer only
forwards typed calls to the generated binding and maps its error -> ``KError``.

CLAIM BOUNDARY (security-claims-non-negotiable): Barbican is advisory /
defense-in-depth (Edge Filtration). "Un-bypassable" attaches ONLY to the
Enforced Boundary (Warden as the sole sandbox egress) -- never this SDK.

The native lib + generated uniffi binding under ``_ffi/`` are build artifacts
(generated per platform; gitignored) -- same convention as ``k9o.kibo``.
"""

from .barbican import Barbican, OutputFilter

__all__ = ["Barbican", "OutputFilter"]
