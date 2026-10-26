# Changelog — k9o (Python SDK)

## 1.4.0 (unreleased)

### Added

- `query(sql, params)`: one read-only SQL statement; a list binds `$1, $2, ...`, a dict binds `:name` placeholders.
- `search(collection, column=..., q=...)`: full-text search over one column, plus `text_search` and `vector_search` on `select()`.
- `ai.generate`: text generation from a prompt (verb sugar over `compute.llms.invoke`; `model` defaults to the org's default LLM).
- `streams` namespace for user data streams: `create`, `list`, `get`, `delete`, `publish`, `replay` and `subscribe`.
  `subscribe` tails live events over SSE and reconnects from the last sequence when the server closes the connection.
- `approvals` namespace for the pending-change queue: `list`, `get`, `approve`, `reject` and `bulk`.
- `approval_policies` namespace: `list`, `create` and `delete`.
- `schema.collections.list`: the project's collections with row counts and last migration, paged by cursor.

### Changed

- The README description now covers streams and realtime, and the platform overview moved to an "About Kilimanjaro" appendix.
- Function deploy examples use the sandbox tier.

## 1.3.0 — 2026-10-26

Every method now matches the gateway.

### Changed

- `projects.create` takes `display_name` (and optional `slug`, `region`, `custody_mode`, ...);
  `projects.get` and `projects.update` use the projects routes.
- `functions.deploy` takes `name`, `runtime`, `tier` (`gateway` or `sandbox`), `artifact_key`, `version` and `description`.
  Inline code is gone.
- `functions.invoke` sends the payload as `{payload}`.
- `policies.create`, `update` and `validate` take a `policy` document (plus optional `rules`, `editor_mode`);
  `policies.list` takes only `status`.
- `audit.query` filters are `event_type`, `actor_id`, `after`, `before`, `limit` and `cursor`.
- Org roles, identity providers, default model and SMTP changed: `smtp.set` uses `password_ref` and `from_address`;
  `smtp.test` takes `to` and `subject`.
- `me.api_tokens.create` takes `label` and `scope_manifest` (and `ttl_seconds`); `me.sessions.revoke` and `revoke_all` use new routes.
- `compute.llms.invoke` settings are sent flat, and the result has `content` and `usage`.
- `studio.workflows.trigger` sends the context as `triggerContext`.
- `gate.sign_out` requires the refresh token.
- `kibo.vault.secrets.get` looks a secret up by exact name; `region` is optional on every vault method.
- The API host comes from the base URL: any `<org>.api.<apex>` host works and no apex is hardcoded.
  `https://api.k9o.io` is only the default.

### Removed

- `gate.verify_session`, `gate.hosted` and `realtime.replay`, and the poll transport of `realtime.subscribe`.
- `me.notifications`, `me.audit_log` and `me.data_export`.
- `org.groups.create`, `org.groups.delete`, `org.members.get` and `org.smtp.get`.

### Added

- `functions.upload_artifact(data, kind)` uploads a build and returns the `artifactKey` for `deploy`.
- `parse_api_host`, `ApiHost` and `DEFAULT_BASE_URL` are exported.
- A contract test checks every method against the gateway's API description.

## 1.2.0 — 2026-10-25

- The README now introduces the Kilimanjaro building blocks (Keep, Pulse, Gate, Kibo). No change to the public API.

## 1.1.1 — 2026-10-25

- Documentation links corrected: the documentation hub is https://docs.kilimanjaro.dev, with the website, platform API and console listed in a Links section. Package metadata points at the same places.

## 1.1.0 — 2026-10-25

- Documentation rewritten with runnable examples and expected output; internal cross-references removed from the published sources. No change to the public API.
- `k9o.__version__` now reports the installed package version (it previously reported `0.3.0`).
- Fixed: boolean filter values are sent as `true` / `false`. `eq("done", False)` previously sent `False`.
- Error text for `update()` / `delete()` without an `id` filter no longer mentions a version or a roadmap.

## 1.0.0 — 2026-10-23

First public release. See the README for the full API overview.
