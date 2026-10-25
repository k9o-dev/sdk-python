# Changelog — k9o (Python SDK)

## 1.1.0 — 2026-10-25

- Documentation rewritten with runnable examples and expected output; internal cross-references removed from the published sources. No change to the public API.
- `k9o.__version__` now reports the installed package version (it previously reported `0.3.0`).
- Fixed: boolean filter values are sent as `true` / `false`. `eq("done", False)` previously sent `False`.
- Error text for `update()` / `delete()` without an `id` filter no longer mentions a version or a roadmap.

## 1.0.0 — 2026-10-23

First public release. See the README for the full API overview.
