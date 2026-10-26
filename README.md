# k9o

Client for Kilimanjaro. Read and write your data, store files, manage policies and migrations,
deploy and invoke agents or functions, and publish to and subscribe to streams and realtime events.

## Contents

- [Links](#links)
- [Install](#install)
- [Quick start](#quick-start)
- [Authentication and project context](#authentication-and-project-context)
- [Running queries](#running-queries)
- [Query with SQL](#query-with-sql)
- [Search](#search)
- [Streams](#streams)
- [Approvals](#approvals)
- [Approval policies](#approval-policies)
- [Schema collections](#schema-collections)
- [Handling errors](#handling-errors)
- [Appendix](#appendix)
  - [About Kilimanjaro](#about-kilimanjaro)
- [License](#license)

## Links

- Website: <https://kilimanjaro.dev>
- Documentation / Developer Hub: <https://docs.kilimanjaro.dev>
- Platform API: <https://api.k9o.io>
- Platform Console: <https://console.k9o.io>

## Install

```bash
pip install k9o==1.4.0
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
print(f"Output: {created.data['title']}")
```

```text
Output: Write the README
```

### List tasks

`from_` has a trailing underscore because `from` is a Python keyword.

```python
response = k9o.from_("tasks").select().eq("done", False).limit(10).execute()
for task in response.data:
    print(f"Output: {task['title']} {task['done']}")
```

```text
Output: Write the README False
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
| `org_slug` | Organization. The SDK builds `https://<org_slug>.<host>` from the platform host. |
| `project_slug` | Project. Required by every project-scoped namespace. |

See [client options](#client-options) for every option.

### Choose a host

The API host always comes from the base URL. Pick one of two forms.

- Default public host: pass the org slug, project slug and key.
- Any other platform, internal or air-gapped host: pass its `base_url` as well.

```python
k9o = create_client(
    base_url="https://api.corp.internal",
    org_slug="acme",
    project_slug="task-app",
    api_key=os.environ["K9O_API_KEY"],
)
```

This client talks to `https://acme.api.corp.internal`. See [regional hosts](#regional-hosts) for the rules.


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
print(f"Output: {request_id} {total}")
```

```text
Output: req_01H... 1
```

## Query with SQL

`k9o.query(sql, params)` runs one read-only SQL statement and returns the rows in `data`.
It is read-only (a write is refused with `K9O_RAW_SQL_READ_ONLY`; change data through `from_`), takes one statement per call,
applies row-level security, accepts at most 100000 characters of SQL and 1000 parameters, and needs the project editor role.
A reference to `dataset.<name>` reads an analytics dataset.

Pass a list to bind `$1`, `$2`, and so on, or a dict to bind `:name` placeholders. Values are bound by the database and can be a string, number, boolean or `None`; serialise anything else (for example as JSON text) first.

```python
rows = k9o.query("SELECT data->>'title' AS title FROM posts WHERE data->>'status' = :status", {"status": "published"})
print(f"Output: {rows.data[0]['title']}")

same = k9o.query("SELECT count(*) AS n FROM posts WHERE data->>'status' = $1", ["published"])
print(f"Output: {same.data[0]['n']}")
```

```text
Output: Hello
Output: 12
```

A `:name` with no key in the dict raises `KError` with code `K9O_INVALID_FIELD_VALUE` before any request is sent.

## Search

`k9o.search(collection, column=..., q=...)` runs a full-text search over one text column, best matches first.
`language` defaults to `english`; `type` is `plain` (default), `phrase` or `websearch`. `limit` and `cursor` page the result.

```python
found = k9o.search("articles", column="body", q="climate resilience", limit=5)
print(f"Output: {len(found.data)} {found.data[0]['title']}")
```

```text
Output: 5 Adapting to heat
```

The same search is available on a query as `text_search(column, query, language="english", type="plain")`.
`vector_search(column, embedding, metric="cosine", limit=None)` finds the closest rows to an embedding, closest first;
`metric` is `cosine`, `euclidean` or `dot`, and `limit` is 1 to 1000.

```python
vector = k9o.ai.embed("heat waves").data["embeddings"][0]
near = k9o.from_("articles").select().vector_search("embedding", vector, limit=3).execute()
print(f"Output: {len(near.data)}")
```

```text
Output: 3
```

## Streams

Publish events to a stream and tail them live. Publishing needs the project admin role; subscribing and replaying need admin or auditor.
`subscribe` reconnects from the last sequence when the server closes the connection, so no event is repeated or skipped.

```python
import asyncio

stream = k9o.streams.create("Orders feed", 1073741824)
slug = stream.data["slug"]
print(f"Output: {slug}")
k9o.streams.publish(slug, {"order": 1001}, subject="eu.new")

async def tail():
    async for event in k9o.streams.subscribe(slug):
        print(f"Output: {event['sequence']} {event['data']['order']}")
        break

asyncio.run(tail())
```

```text
Output: orders-feed
Output: 1 1001
```

`replay` reads a bounded range of past events.
Failures raise `KError`: `K9O_STREAM_UNAVAILABLE` while streams are not available, and `K9O_STREAM_INVALID` for a bad subject.

## Approvals

Writes that need approval wait in a queue for a second person. `k9o.approvals` reads that queue and decides its changes.
Project admins and auditors see every change; other members see only the ones they proposed.

```python
queue = k9o.approvals.list(status="pending_approval", limit=20)
change = queue.data[0]

print(f"Output: {change['id']} {change['operation']} {change['collection']}")

decided = k9o.approvals.approve(change["id"], reason="checked the amount")

print(f"Output: {decided.data['status']}")
```

```text
Output: apr_01j9x3 update orders
Output: redeemed
```

- A change is `pending_approval`, `approved`, `rejected`, `expired` or `redeemed` (applied). An `expired` change can still read `pending_approval` until someone decides it.
- `approve` can answer 200 with `status` still `pending_approval`. That means your approval is recorded and more approvers are needed; the change is not applied yet.
- `reject(id, reason)` needs a non-empty `reason`; the SDK checks it before sending.
- `list` is not paginated: it returns the newest `limit` changes (1 to 200, default 50). `get(id)` reads one.
- Deciding needs the queue-admin role (project admin or auditor).

Decide many at once with `bulk`. `criteria` is a predicate over each pending change (see [Approval policies](#approval-policies)):

```python
run = k9o.approvals.bulk(
    "reject",
    {"eq": ["change.table", "orders"]},
    reason="stale",
)

print(f"Output: {run.data['affectedCount']} {','.join(run.data['affectedIds'])}")
```

```text
Output: 2 apr_01j9x3,apr_01j9x4
```

- A row that fails (a conflict, an apply error) is skipped silently and left out of `affectedIds`. Compare `affectedIds` with the set you intended.
- `reject` needs a `reason`; `criteria` must be a predicate object. `attestationId` identifies the batch, even when nothing matched.
- It considers the newest 10000 pending changes. Bulk approve is not guaranteed to apply every matched row.

## Approval policies

A policy decides what happens to writes on one collection that match a predicate: `queue` them for approval, or `auto_approve` them.
For a write the first matching policy, oldest first, decides. Policies are evaluated for writes sent with the `requireApproval=true` query parameter.

```python
policy = k9o.approval_policies.create(
    "orders",
    "update",
    "queue",
    {"gt": ["change.row.amount", 1000]},
)

print(f"Output: {policy.data['id']} {policy.data['action']}")

removed = k9o.approval_policies.delete(policy.data["id"])

print(f"Output: {removed.data['id']}")
```

```text
Output: apo_01j9x5 queue
Output: apo_01j9x5
```

- `operation` is `insert`, `update` or `delete`; `action` is `auto_approve` or `queue`.
- `collection` matches `^[a-zA-Z_][a-zA-Z0-9_]{0,62}$` and `predicate` is a non-null object. The SDK checks both before sending.
- A predicate has one operator key: `and`, `or`, `not`, `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `in_cidr`, `not_in_cidr` or `contains`.
  `and` and `or` take a list of predicates, `not` takes one, and a comparison takes `[left, right]`.
- Operands start with `maker.` or `change.` (for example `change.row.amount`, `change.table`, `change.operation`, `maker.id`).
- `list()` returns all policies. Identical policies are not de-duplicated. Creating and deleting need project admin or author.

## Schema collections

`k9o.schema.collections.list` lists the project's collections by name, with their size and last migration.

```python
page = k9o.schema.collections.list(limit=2)

for collection in page.data:
    print(f"Output: {collection['name']} {collection['rowCount']} rows, {collection['columnCount']} columns")
print(f"Output: next {page.meta.cursor.next}")
```

```text
Output: orders 120 rows, 8 columns
Output: tasks 14 rows, 4 columns
Output: next dGFza3M
```

- Pass `meta.cursor.next` as `cursor` for the next page; it is `None` on the last page. `limit` is 1 to 200 (default 50).
- A row is `name`, `rowCount`, `rowCountIsExact`, `columnCount`, `indexCount`, `lastMigrationSlug` and `lastMigrationAppliedAt`.
- `rowCount` is a live count that skips soft-deleted rows and ignores row-level security. Without an `org_id` claim on the token, `meta.warnings` says so.
- Project admins, auditors, editors, members and viewers can read it.

## Handling errors

Failures raise `KError`, a subclass of `Exception`. Branch on `code`.

```python
from k9o import KError

try:
    k9o.from_("missing").select().execute()
except KError as error:
    print(f"Output: {error.code} {error.status} {error.request_id}")
    print(f"Output: {error.message}")
```

```text
Output: K9O_NOT_FOUND 404 req_01H...
Output: Collection not found
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
| `org_slug` | Organization. Prefixed to a platform host (`api.<apex>`) to form the org host. |
| `project_slug` | Project. Required by every project-scoped namespace. |
| `base_url` | Scheme and host only. Defaults to the public host `https://api.k9o.io`. |
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
| `text_search(column, query, language="english", type="plain")` | Full-text search over one column. |
| `vector_search(column, embedding, metric="cosine", limit=None)` | Nearest rows to an embedding, closest first. |

`select().execute_async()` is the async form of `execute()`.

#### Projects

`k9o.projects` manages projects in the active organization.

| Method | What it does |
|---|---|
| `k9o.projects.list` | List projects you can access. |
| `k9o.projects.create` | Create a project from `display_name` (optional `slug`, `region`, `custody_mode`, more). |
| `k9o.projects.get` | Read a project by slug. |
| `k9o.projects.update` | Change a project by slug: `new_slug`, `display_name`, `description`, `region`, more. |

```python
project = k9o.projects.create(display_name="Task app", slug="task-app")
print(f"Output: {project.data['slug']}")
```

```text
Output: task-app
```

#### Gate (end-user sign-in)

`k9o.gate` signs in the active project's end users and needs `project_slug`.

| Method | What it does |
|---|---|
| `k9o.gate.sign_up` | Create an end user from email and password. |
| `k9o.gate.sign_in` | Sign in with email and password. |
| `k9o.gate.sign_out` | Revoke a session. Requires `refresh_token`. |
| `k9o.gate.whoami` | Return the signed-in identity. |
| `k9o.gate.refresh_token` | Exchange a refresh token for a new access token. |

```python
session = k9o.gate.sign_in(email="ada@example.com", password="correct-horse")
user = session.data["user"]
print(f"Output: {user['email']}")
```

```text
Output: ada@example.com
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
| `k9o.functions.upload_artifact` | Upload the build (`bytes`, `kind` of `wasm` or `tar`). Returns `artifactKey`. |
| `k9o.functions.deploy` | Deploy from `name`, `runtime`, `tier`, `artifact_key`, `version`, optional `description`. |
| `k9o.functions.list` | List functions. Filters: `status`, `tier`, `source`, `limit`, `cursor`. |
| `k9o.functions.get` | Read one function by name. |
| `k9o.functions.delete` | Remove a function. |
| `k9o.functions.invoke` | Run a function. The `payload` argument is sent as `{payload}`. |

`tier` is `sandbox` (an OCI image archive, `kind="tar"`, up to 256 MiB). The `gateway` tier is for functions owned by platform operators and is not available to most projects. Sandbox functions run in a [Firelock](https://github.com/firelock-sandbox/firelock) microVM sandbox.

```python
with open("hello.tar", "rb") as f:
    artifact = k9o.functions.upload_artifact(f.read(), "tar")

k9o.functions.deploy(
    name="hello",
    runtime="bun",
    tier="sandbox",
    artifact_key=artifact.data["artifactKey"],
    version="1.0.0",
)
result = k9o.functions.invoke("hello", {"name": "Ada"})
print(f"Output: {result.data['greeting']}")
```

```text
Output: Hello, Ada
```

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
| `k9o.policies.list` | List bundles. Only filter: `status`. |
| `k9o.policies.create` | Create a bundle from a `policy` document (optional `rules`, `editor_mode`). |
| `k9o.policies.validate` | Check a `policy` document (and optional `rules`) without saving. |
| `k9o.policies.get` | Read one bundle. |
| `k9o.policies.update` | Replace a bundle's `policy` (optional `rules`, `editor_mode`). |
| `k9o.policies.delete` | Remove a bundle. |
| `k9o.policies.publish` | Make a bundle current. Optional `acknowledge_self_lockout`. |

#### Audit

`k9o.audit` reads the project's audit events.

| Method | What it does |
|---|---|
| `k9o.audit.query` | Filter by `event_type`, `actor_id`, `after`, `before`, `limit`, `cursor`. |
| `k9o.audit.tail` | Return events from the last `since_minutes`. |

`after` and `before` are ISO 8601 timestamps.

#### AI embeddings

`k9o.ai` creates text embeddings.

| Method | What it does |
|---|---|
| `k9o.ai.embed(input, model=None)` | Embed one string or a list of strings. |
| `k9o.ai.generate(prompt, model=None, max_tokens=None, temperature=None, usage_type=None)` | Generate text from a prompt. |

##### Generate text

`model` is optional: without it the org's default model is used. Models from outside providers answer 501 until built.
The result `data` is the same as `compute.llms.invoke`.

```python
result = k9o.ai.generate("Say hi in three words", max_tokens=20)
print(f"Output: {result.data['content']}")
```

```text
Output: Hi there, friend!
```

#### Language models

`k9o.compute.llms` lists and calls hosted models.

| Method | What it does |
|---|---|
| `k9o.compute.llms.list` | List available models. |
| `k9o.compute.llms.read` | Read one model. |
| `k9o.compute.llms.invoke` | Send a prompt and get the reply. |
| `k9o.compute.llms.invoke_stream` | Stream the reply chunk by chunk (async iterator). |

Pass settings in `params`: `maxTokens`, `temperature`, `usageType`. The result `data` has `content` and `usage`.

```python
reply = k9o.compute.llms.invoke("model-id", prompt="Say hi", params={"maxTokens": 20})
print(f"Output: {reply.data['content']} {reply.data['usage']['totalTokens']}")
```

```text
Output: Hi there! 14
```

#### Realtime

`k9o.realtime` delivers live events for a topic.

| Method | What it does |
|---|---|
| `k9o.realtime.subscribe` | Stream live events over SSE (async iterator). |

`realtime_topic` builds topic names, for example `realtime_topic.collection("tasks")`.

#### Streams

`k9o.streams` publishes to and subscribes to the project's user streams. It needs `project_slug`.

| Method | What it does |
|---|---|
| `k9o.streams.create(display_name, max_bytes, retention_seconds=None)` | Create a stream. The slug comes from the name. |
| `k9o.streams.list()` | List the project's streams. |
| `k9o.streams.get(slug)` | Read one stream. |
| `k9o.streams.delete(slug)` | Retire a stream. |
| `k9o.streams.publish(slug, data, subject=None)` | Append an event. `subject` is a dot-separated routing suffix. |
| `k9o.streams.replay(slug, from_sequence=None, until_sequence=None, limit=None)` | Read past events: `events`, `nextCursor`, `hasMore`. |
| `k9o.streams.subscribe(slug, from_sequence=None)` | Tail live events over SSE (async iterator). Reconnects from the last sequence. |

#### Approvals

`k9o.approvals` reads and decides the queue of changes waiting for approval. It needs `project_slug`.

| Method | What it does |
|---|---|
| `k9o.approvals.list(status=None, limit=None)` | Newest pending changes first. Not paginated; `limit` is 1 to 200. |
| `k9o.approvals.get(id)` | Read one change. |
| `k9o.approvals.approve(id, reason=None)` | Approve. `status` can stay `pending_approval` while more approvers are needed. |
| `k9o.approvals.reject(id, reason)` | Reject. `reason` is required. |
| `k9o.approvals.bulk(action, criteria, reason=None)` | Approve or reject every change matching a predicate. `reason` is required to reject. Failed rows are skipped. |

#### Approval policies

`k9o.approval_policies` holds the rules that decide which writes are queued. It needs `project_slug`.

| Method | What it does |
|---|---|
| `k9o.approval_policies.list()` | All policies, oldest first. |
| `k9o.approval_policies.create(collection, operation, action, predicate)` | Create a policy. `action` is `auto_approve` or `queue`. |
| `k9o.approval_policies.delete(id)` | Delete a policy. |

#### Schema

| Method | What it does |
|---|---|
| `k9o.schema.collections.list(limit=None, cursor=None)` | List the project's collections by name, with `meta.cursor.next` paging. |

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
| `k9o.studio.workflows.trigger` | Start a run, with an optional `trigger_context` dict. |
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
| `k9o.me.profile.update` | Change `display_name`, `locale` or `timezone` (only those given). |
| `k9o.me.sessions.list` | List active sessions. |
| `k9o.me.sessions.revoke` | End one session. |
| `k9o.me.sessions.revoke_all` | End all sessions. |
| `k9o.me.api_tokens.list` | List API tokens. |
| `k9o.me.api_tokens.create` | Create a token from `label` and `scope_manifest` (optional `ttl_seconds`). |
| `k9o.me.api_tokens.delete` | Delete an API token. |

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
| `k9o.org.members.list` | List members. Filters: `user_id`, `role`, `acceptance_status`, `status`, `state`. |
| `k9o.org.members.invite` | Invite a member by email and role. |
| `k9o.org.members.remove` | Remove a member. |
| `k9o.org.groups.list` | List groups, optionally for one `user_id`. |
| `k9o.org.groups.get` | Read one group. |
| `k9o.org.audit_log.query` | Search organization audit events by `type` and `limit`. |
| `k9o.org.audit_log.tail` | Return events from the last `since_minutes`. |
| `k9o.org.gate.roles.list` | List role grants. |
| `k9o.org.gate.roles.grant` | Grant a role to a user (`user_id`, `role`, optional `decision_reason`). |
| `k9o.org.gate.roles.get` | Read one grant. |
| `k9o.org.gate.roles.revoke` | Revoke a grant. |
| `k9o.org.gate.idp_providers.list` | List identity providers. |
| `k9o.org.gate.idp_providers.create` | Add a provider: `idp_provider`, `display_name`, `client_id`, `client_secret_ref`, `tier_gating`. |
| `k9o.org.gate.idp_providers.get` | Read one provider. |
| `k9o.org.gate.idp_providers.configure` | Change a provider. |
| `k9o.org.gate.idp_providers.delete` | Remove a provider. |
| `k9o.org.smtp.set` | Save the mail server: `host`, `port`, `username`, `password_ref`, `from_address`. |
| `k9o.org.smtp.test` | Send a test email to `to`, with an optional `subject`. |
| `k9o.org.smtp.unset` | Remove the mail server settings. |
| `k9o.org.default_llm.get` | Read the default model. |
| `k9o.org.default_llm.set` | Set the default model with `model_id`. |

#### Vault secrets

`k9o.kibo.vault.secrets` stores and reveals secrets in the project's vault.

| Method | What it does |
|---|---|
| `k9o.kibo.vault.secrets.list` | List secrets by prefix. |
| `k9o.kibo.vault.secrets.get` | Read a secret's details by exact name. `region` is optional. |
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
| `meta.cost` | Usage cost details as a dict. |
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

- A platform host is `api.<apex>` or `api-staging.<apex>`, on any apex.
- With `org_slug`, the SDK builds the org host `<org_slug>.<host>`.
- A region-free org host gets one credential-free `HEAD` request to learn its region.
- Later requests go to the regional host, which must share the org, family and apex.
- Any other base URL (internal, air-gapped, localhost) is used exactly as given.
- `https://api.k9o.io` is only the default when `base_url` is omitted.

### Related packages

| Package | What it is |
|---|---|
| `@k9o/core` | TypeScript SDK |
| `@k9o/cli` | Command-line tool |

### About Kilimanjaro

Kilimanjaro is a modular developer platform for building secure enterprise applications.
You define AI agents, functions and data pipelines on the platform.
The SDKs let you deploy and invoke them, read and write your data, publish to and subscribe to streams,
sign users in, and encrypt with keys you hold.

It provides four building blocks:

- **Keep**: AI security and governance. Guardrails and policy for the agents you run.
- **Pulse**: data intelligence and real-time stream processing. Streams, analytics and live feeds.
- **Gate**: customer identity and access management. Sign-in and sessions, and automatic data scoping so a signed-in user reaches only their own data.
- **Kibo**: cryptographic keys and secrets management. Client-side encryption with keys you hold, and a secrets vault.

## License

Apache-2.0 © Formelo Inc. See `LICENSE` and `NOTICE`.
