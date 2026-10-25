# k9o

The Kilimanjaro platform SDK for Python.

Kilimanjaro is an AI-native platform on a Governed Database. Its products are Keep (AI Security and Governance), Pulse (Data Intelligence), Gate (Customer Identity and Access Management) and Kibo (Keys and Secrets Management).

## Contents

- [Links](#links)
- [Install](#install)
- [Quick start](#quick-start)
- [Authentication and project context](#authentication-and-project-context)
- [Running queries](#running-queries)
- [Handling errors](#handling-errors)
- [Appendix](#appendix)
- [License](#license)

## Links

- Website: <https://kilimanjaro.dev>
- Documentation / Developer Hub: <https://docs.kilimanjaro.dev>
- Platform API: <https://api.k9o.io>
- Platform Console: <https://console.k9o.io>

## Install

```bash
pip install k9o
```

Requires Python 3.10 or newer. See [requirements](#requirements) for details.

## Quick start

The examples use a `tasks` collection with `title` and `done` fields.

### Create the client

```python
import os
from k9o import create_client

k9o = create_client(
    org_slug="acme",
    project_slug="task-app",
    api_key=os.environ["K9O_API_KEY"],
)
```

### Add a task

```python
new_task = {"title": "Write the README", "done": False}
created = k9o.from_("tasks").insert(new_task)
print("created:", created.data["title"])
```

```text
created: Write the README
```

### List tasks

`from_` has a trailing underscore because `from` is a Python keyword.

```python
response = k9o.from_("tasks").select().eq("done", False).limit(10).execute()
for task in response.data:
    print(task["title"], task["done"])
```

```text
Write the README False
```

### Update and delete a task

Both calls need an `eq("id", ...)` filter.

```python
task_id = created.data["id"]

patch = {"done": True}
k9o.from_("tasks").update(patch).eq("id", task_id).execute()

k9o.from_("tasks").delete().eq("id", task_id).execute()
```

## Authentication and project context

The client needs a key and, for project calls, an org and project.

| Option | What it does |
|---|---|
| `api_key` | Bearer token sent with every request. |
| `org_slug` | Organization. On the default host the SDK uses `https://<org_slug>.api.k9o.io`. |
| `project_slug` | Project. Required by every project-scoped namespace. |

See [client options](#client-options) for every option.

### Choose a host

Pick one of two forms.

- Default platform host: pass the org slug, project slug and key.
- Custom or self-hosted host: pass `base_url`, project slug and key, and no org slug.

```python
k9o = create_client(
    base_url="https://k9o.internal.example.com",
    project_slug="task-app",
    api_key=os.environ["K9O_API_KEY"],
)
```

The base URL rules are listed under [regional hosts](#regional-hosts).

## Running queries

Chain filters on `select`, then call `execute`. The result carries rows in `data` and details in `meta`.

| Call | What it does |
|---|---|
| `eq(column, value)` | Keep rows where the column equals the value. |
| `limit(n)` | Return at most `n` rows. |
| `cursor(token)` | Continue from `meta.cursor.next`. |

See [filters](#filters) and [paging](#paging) for all calls, and [response metadata](#response-metadata) for every `meta` field.

A sub-object the server did not send is `None`.

```python
request_id = response.meta.context.request_id
total = response.meta.cursor.total_count
print(request_id, total)
```

```text
req_01H... 1
```

## Handling errors

Failures raise `KError`, a subclass of `Exception`. Branch on `code`.

```python
from k9o import KError

try:
    k9o.from_("missing").select().execute()
except KError as error:
    print(error.code, error.status, error.request_id)
    print(error.message)
```

```text
K9O_NOT_FOUND 404 req_01H...
Collection not found
```

- See [error attributes](#error-attributes) for every field.
- See [error codes](#error-codes) for the codes the SDK raises.
- See [retries](#retries) for automatic retry rules.

## Appendix

### Requirements

| Requirement | Version |
|---|---|
| `Python` | 3.10 or newer |
| `httpx` | 0.27 or newer (installed automatically) |

### Client options

| Option | What it does |
|---|---|
| `api_key` | Bearer token sent with every request. |
| `org_slug` | Organization. On the default host the SDK uses `https://<org_slug>.api.k9o.io`. |
| `project_slug` | Project. Required by every project-scoped namespace. |
| `base_url` | Scheme and host only. Defaults to `https://api.k9o.io`. |
| `default_headers` | Extra headers added to every request. |
| `retry_config` | A `RetryConfig` that tunes retries (see Retries). |

`org_slug` and `project_slug` are also sent as the `x-k9o-org-slug` and `x-k9o-project-slug` headers.

### Methods by namespace

Every method is called on the client, for example `k9o.projects.list`. Return values are `Envelope` objects.

#### Data

`k9o.from_(collection)` reads and writes rows in one collection of the active project.

| Method | What it does |
|---|---|
| `select()` | Start a query. Finish with `execute`. |
| `insert(record)` | Add one row and return it. |
| `update(patch)` | Change one row. Needs `eq("id", ...)`. |
| `delete()` | Remove one row. Needs `eq("id", ...)`. |

##### Filters

Chain filters before `execute`. Values are matched against one column.

| Method | What it does |
|---|---|
| `eq(column, value)` | Equal to value. |
| `neq(column, value)` | Not equal to value. |
| `gt(column, value)` | Greater than value. |
| `gte(column, value)` | Greater than or equal. |
| `lt(column, value)` | Less than value. |
| `lte(column, value)` | Less than or equal. |
| `in_(column, values)` | Equal to any value in the list. |
| `not_in(column, values)` | Equal to none of the values. |
| `like(column, pattern)` | Case-sensitive pattern match. |
| `ilike(column, pattern)` | Case-insensitive pattern match. |
| `is_(column, value)` | Match `null`, `true` or `false`. |
| `filter(column, op, value)` | Generic form with an explicit operator name. |

##### Paging

| Method | What it does |
|---|---|
| `limit(n)` | Maximum rows to return. |
| `cursor(token)` | Continue from `meta.cursor.next`. |
| `count(mode)` | Row count mode: `none`, `exact` or `estimated`. |

`select().execute_async()` is the async form of `execute()`.

#### Projects

`k9o.projects` manages projects in the active organization.

| Method | What it does |
|---|---|
| `k9o.projects.list` | List projects you can access. |
| `k9o.projects.create` | Create a project from `slug` and `name`. |
| `k9o.projects.get` | Read a project by slug. |
| `k9o.projects.update` | Change a project's `name`. |

#### Gate (end-user sign-in)

`k9o.gate` signs in the active project's end users and needs `project_slug`.

| Method | What it does |
|---|---|
| `k9o.gate.sign_up` | Create an end user from email and password. |
| `k9o.gate.sign_in` | Sign in with email and password. |
| `k9o.gate.sign_out` | Revoke the session's refresh token. |
| `k9o.gate.whoami` | Return the signed-in identity. |
| `k9o.gate.refresh_token` | Exchange a refresh token for a new access token. |
| `k9o.gate.verify_session` | Check that the current session is valid. |
| `k9o.gate.hosted` | Return the hosted sign-in `signInUrl` and `rpId`. |

```python
session = k9o.gate.sign_in(email="ada@example.com", password="correct-horse")
user = session.data["user"]
print(user["email"])
```

```text
ada@example.com
```

#### Storage

`k9o.storage` manages buckets and the objects inside them.

##### Buckets

| Method | What it does |
|---|---|
| `k9o.storage.create_bucket` | Create a bucket by name. |
| `k9o.storage.get_bucket` | Read one bucket. |
| `k9o.storage.list_buckets` | List buckets. |
| `k9o.storage.update_bucket` | Change bucket settings. |
| `k9o.storage.delete_bucket` | Delete a bucket. Pass `empty` to purge its objects first. |

##### Objects

`k9o.storage.from_(bucket)` returns a handle for one bucket.

| Method | What it does |
|---|---|
| `k9o.storage.from_(bucket).upload` | Store bytes at a path. Existing paths are kept unless `upsert` is true. |
| `k9o.storage.from_(bucket).create_signed_url` | Create a time-limited download link. |
| `k9o.storage.from_(bucket).list` | List objects, optionally under a `prefix`. |
| `k9o.storage.from_(bucket).remove` | Delete the object at a path. |

`expires_in` is required, in seconds from 1 to 604800.

```python
avatars = k9o.storage.from_("avatars")
avatars.upload("ada.png", b"...image bytes...", content_type="image/png")
signed = avatars.create_signed_url("ada.png", expires_in=300)
```

Every storage method has an `_async` twin, such as `upload_async`.

#### Functions

`k9o.functions` deploys and runs server-side functions.

| Method | What it does |
|---|---|
| `k9o.functions.deploy` | Deploy a function from `name`, `runtime` and `code`. |
| `k9o.functions.list` | List functions. |
| `k9o.functions.get` | Read one function by name. |
| `k9o.functions.delete` | Remove a function. |
| `k9o.functions.invoke` | Run a function with a payload. |

#### Migrations

`k9o.migrations` changes the project's schema.

| Method | What it does |
|---|---|
| `k9o.migrations.apply` | Apply migrations now. |
| `k9o.migrations.list` | List applied migrations. |
| `k9o.migrations.get` | Read one migration by version. |
| `k9o.migrations.queue` | Queue migrations for approval. |
| `k9o.migrations.list_pending` | List queued migrations. |
| `k9o.migrations.apply_pending` | Apply one queued migration. |
| `k9o.migrations.reject_pending` | Reject one queued migration. |
| `k9o.migrations.delete_pending` | Delete one queued migration. |

#### Policies

`k9o.policies` manages access policy bundles.

| Method | What it does |
|---|---|
| `k9o.policies.current` | Read the published bundle. |
| `k9o.policies.list` | List bundles. |
| `k9o.policies.create` | Create a bundle from `name` and `rules`. |
| `k9o.policies.validate` | Check rules without saving. |
| `k9o.policies.get` | Read one bundle. |
| `k9o.policies.update` | Change a bundle. |
| `k9o.policies.delete` | Remove a bundle. |
| `k9o.policies.publish` | Make a bundle current. |

#### Audit

`k9o.audit` reads the project's audit events.

| Method | What it does |
|---|---|
| `k9o.audit.query` | Search events by time range, type and more. |
| `k9o.audit.tail` | Return the most recent events. |

#### AI embeddings

`k9o.ai` creates text embeddings.

| Method | What it does |
|---|---|
| `k9o.ai.embed(input, model=None)` | Embed one string or a list of strings. |

#### Language models

`k9o.compute.llms` lists and calls hosted models.

| Method | What it does |
|---|---|
| `k9o.compute.llms.list` | List available models. |
| `k9o.compute.llms.read` | Read one model. |
| `k9o.compute.llms.invoke` | Send a prompt and get the reply. |
| `k9o.compute.llms.invoke_stream` | Stream the reply token by token (async iterator). |

#### Realtime

`k9o.realtime` delivers live events for a topic.

| Method | What it does |
|---|---|
| `k9o.realtime.subscribe` | Stream live events (async iterator). |
| `k9o.realtime.replay` | Read past events from a sequence number. |

`realtime_topic` builds topic names, for example `realtime_topic.collection("tasks")`.

#### Studio

`k9o.studio` manages workflows and dashboards.

##### Workflows

| Method | What it does |
|---|---|
| `k9o.studio.workflows.list` | List workflows. |
| `k9o.studio.workflows.create` | Create a workflow. |
| `k9o.studio.workflows.read` | Read one workflow. |
| `k9o.studio.workflows.update` | Change a workflow. |
| `k9o.studio.workflows.delete` | Delete a workflow. |
| `k9o.studio.workflows.trigger` | Start a run. |
| `k9o.studio.workflows.runs.list` | List a workflow's runs. |
| `k9o.studio.workflows.runs.read` | Read one run. |
| `k9o.studio.workflows.runs.cancel` | Cancel a run. |

##### Dashboards

| Method | What it does |
|---|---|
| `k9o.studio.dashboards.list` | List dashboards. |
| `k9o.studio.dashboards.create` | Create a dashboard. |
| `k9o.studio.dashboards.read` | Read one dashboard. |
| `k9o.studio.dashboards.update` | Change a dashboard. |
| `k9o.studio.dashboards.delete` | Delete a dashboard. |
| `k9o.studio.dashboards.pin` | Pin to the workspace. |
| `k9o.studio.dashboards.unpin` | Remove from the workspace. |

#### Current user

`k9o.me` covers the signed-in account.

| Method | What it does |
|---|---|
| `k9o.me.profile.get` | Read the profile. |
| `k9o.me.profile.update` | Change the display name. |
| `k9o.me.sessions.list` | List active sessions. |
| `k9o.me.sessions.revoke` | End one session. |
| `k9o.me.sessions.revoke_all` | End all sessions. |
| `k9o.me.api_tokens.list` | List API tokens. |
| `k9o.me.api_tokens.create` | Create an API token. |
| `k9o.me.api_tokens.delete` | Delete an API token. |
| `k9o.me.notifications.list` | List notifications. |
| `k9o.me.notifications.mark_read` | Mark one as read. |
| `k9o.me.notifications.mark_all_read` | Mark all as read. |
| `k9o.me.audit_log.query` | Search your own audit events. |
| `k9o.me.data_export.request` | Request a data export. |
| `k9o.me.data_export.status` | Check an export job. |

#### Organization

`k9o.orgs` lists organizations and `k9o.org` administers the active one.

##### Organizations

| Method | What it does |
|---|---|
| `k9o.orgs.list` | List your organizations. |
| `k9o.orgs.get` | Read one by slug. |
| `k9o.orgs.current` | Read the active organization. |
| `k9o.orgs.restore` | Restore a deleted organization. |

##### Administration

| Method | What it does |
|---|---|
| `k9o.org.get` | Read the active organization. |
| `k9o.org.members.list` | List members. |
| `k9o.org.members.invite` | Invite a member by email and role. |
| `k9o.org.members.get` | Read one member. |
| `k9o.org.members.remove` | Remove a member. |
| `k9o.org.groups.list` | List groups. |
| `k9o.org.groups.create` | Create a group. |
| `k9o.org.groups.get` | Read one group. |
| `k9o.org.groups.delete` | Delete a group. |
| `k9o.org.audit_log.query` | Search organization audit events. |
| `k9o.org.audit_log.tail` | Return the most recent events. |
| `k9o.org.gate.roles.list` | List role grants. |
| `k9o.org.gate.roles.grant` | Grant a role to a user. |
| `k9o.org.gate.roles.get` | Read one grant. |
| `k9o.org.gate.roles.revoke` | Revoke a grant. |
| `k9o.org.gate.idp_providers.list` | List identity providers. |
| `k9o.org.gate.idp_providers.create` | Add an identity provider. |
| `k9o.org.gate.idp_providers.get` | Read one provider. |
| `k9o.org.gate.idp_providers.configure` | Change a provider. |
| `k9o.org.gate.idp_providers.delete` | Remove a provider. |
| `k9o.org.smtp.get` | Read the mail server settings. |
| `k9o.org.smtp.set` | Save the mail server settings. |
| `k9o.org.smtp.test` | Send a test email. |
| `k9o.org.smtp.unset` | Remove the mail server settings. |
| `k9o.org.default_llm.get` | Read the default model. |
| `k9o.org.default_llm.set` | Set the default model. |

#### Vault secrets

`k9o.kibo.vault.secrets` stores and reveals secrets in the project's vault.

| Method | What it does |
|---|---|
| `k9o.kibo.vault.secrets.list` | List secrets by prefix. |
| `k9o.kibo.vault.secrets.get` | Read a secret's details. |
| `k9o.kibo.vault.secrets.create` | Store a new secret. |
| `k9o.kibo.vault.secrets.reveal_challenge` | Get a one-time challenge for revealing. |
| `k9o.kibo.vault.secrets.reveal` | Reveal the value using the challenge. |
| `k9o.kibo.vault.secrets.update` | Replace the value. |
| `k9o.kibo.vault.secrets.rotate` | Rotate the secret. |
| `k9o.kibo.vault.secrets.move` | Move to a new path. |
| `k9o.kibo.vault.secrets.delete` | Delete the secret. |

### Response metadata

| Field | What it holds |
|---|---|
| `meta.cursor` | Pagination: `next` and `total_count`. |
| `meta.context` | Request tracing: `request_id`. |
| `meta.timing` | Server time: `total_ms`. |
| `meta.warnings` | List of non-fatal warnings, each with `code` and `message`. |
| `meta.idempotency` | `replayed` flag for repeated requests. |
| `meta.subscription` | `is_initial` flag for streamed events. |
| `meta.cost` | Usage cost details as a hash. |
| `meta.raw` | The original wire payload. |

### Error attributes

| Attribute | Meaning |
|---|---|
| `code` | Error code such as `K9O_NOT_FOUND`. |
| `message` | Human-readable explanation. |
| `recommendation` | Suggested next step, or `None`. |
| `status` | HTTP status, or `None` if no request was made. |
| `request_id` | Server trace id. Quote it when contacting support. |
| `context` | Read-only details for the error. |

The server may send codes not listed here, so keep a fallback branch.

### Error codes

| Code | When |
|---|---|
| `K9O_INVALID_BASE_URL` | `base_url` has a path, query or bad scheme. |
| `K9O_MISSING_PROJECT_CONTEXT` | A project call was made without `project_slug`. |
| `K9O_INVALID_FIELD_VALUE` | An argument failed validation before sending. |
| `K9O_INVALID_BUCKET_NAME` | Bucket name is not 3 to 63 lowercase letters, digits or hyphens. |
| `K9O_UPSTREAM_UNAVAILABLE` | Network failure reaching the gateway. |
| `K9O_INTERNAL_ERROR` | The response could not be read. |

### Retries

- GET, HEAD, OPTIONS and DELETE are retried on network errors.
- They are also retried on 429, 502, 503 and 504.
- The default is 3 retries with exponential backoff.
- Other methods are never retried.

Tune retries with `RetryConfig`:

| Option | What it does |
|---|---|
| `max_retries` | Retries after the first attempt. Default 3. |
| `backoff` | `exponential`, `linear` or `none`. |
| `initial_delay_ms` | First delay. Default 100. |
| `max_delay_ms` | Delay cap. Default 5000. |

```python
from k9o import RetryConfig

retry = RetryConfig(max_retries=5, backoff="linear")
k9o = create_client(
    org_slug="acme",
    project_slug="task-app",
    api_key=os.environ["K9O_API_KEY"],
    retry_config=retry,
)
```

### Regional hosts

- Organization hosts such as `https://acme.api.k9o.io` are region-free.
- The SDK sends one credential-free `HEAD` request to learn the region.
- Later requests go to the regional host.
- Any other base URL is used exactly as given.

### Related packages

| Package | What it is |
|---|---|
| `@k9o/core` | TypeScript SDK |
| `@k9o/cli` | Command-line tool |

## License

Apache-2.0 © Formelo Inc. See `LICENSE` and `NOTICE`.
