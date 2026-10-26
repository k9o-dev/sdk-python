"""
`create_client(...)` factory + `K9oClient`.

Canonical usage:

    from k9o import create_client, KError

    k9o = create_client(
        base_url="https://acme.api.k9o.io",
        api_key=os.environ["K9O_API_KEY"],
        org_slug="acme",
        project_slug="member-portal",
    )

    try:
        response = k9o.from_("posts").select().limit(10).execute()
        for row in response.data:
            print(row)
        if response.meta.cursor:
            print("next cursor:", response.meta.cursor.next)
    except KError as e:
        print(f"[{e.code}] {e.message}: {e.recommendation}")
        raise
"""

from __future__ import annotations

from .ai import AiNamespace
from .audit import AuditNamespace
from .compute import ComputeNamespace
from .data import FromBuilder
from .functions import FunctionsNamespace
from .gate import GateNamespace
from .http import HttpClientConfig, RetryConfig
from .kibo_vault import KiboNamespace
from .me import MeNamespace
from .migrations import MigrationsNamespace
from .org import OrgNamespace
from .orgs import OrgsNamespace
from .policies import PoliciesNamespace
from .projects import ProjectsNamespace
from .realtime import RealtimeNamespace
from .storage import StorageNamespace
from .studio import StudioNamespace
from .url_grammar import resolve_base_url


class K9oClient:
    """The client returned by `create_client(...)`.

    Namespaces hang off the instance — composed from per-resource
    factories sharing the bound HTTP config.

    Attributes:
      projects  — `client.projects.list()` / `.create(display_name=...)` / `.get(slug)` / `.update(slug, ...)`
      gate      — `client.gate.sign_in(...)` / `.sign_up(...)` / `.whoami()` / etc. (requires project_slug)
      kibo      — `client.kibo.vault.secrets.{list,get,create,reveal_challenge,reveal,update,rotate,move,delete}`
                  (ZK vault-secrets surface; requires project_slug)
      storage   — `client.storage.{create_bucket,get_bucket,list_buckets,update_bucket,delete_bucket}` and
                  `client.storage.from_(bucket).{upload,create_signed_url,list,remove}` (each with an `_async`
                  twin; requires project_slug)

    Methods:
      from_(collection) — data-plane DSL; returns a FromBuilder
    """

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config
        self.projects = ProjectsNamespace(config)
        self.gate = GateNamespace(config)
        self.migrations = MigrationsNamespace(config)
        self.functions = FunctionsNamespace(config)
        self.policies = PoliciesNamespace(config)
        self.audit = AuditNamespace(config)
        self.orgs = OrgsNamespace(config)
        self.me = MeNamespace(config)
        self.studio = StudioNamespace(config)
        self.compute = ComputeNamespace(config)
        self.ai = AiNamespace(config)
        self.realtime = RealtimeNamespace(config)
        self.org = OrgNamespace(config)
        self.kibo = KiboNamespace(config)
        self.storage = StorageNamespace(config)

    @property
    def config(self) -> HttpClientConfig:
        """Bound config (read-only access for advanced use)."""
        return self._config

    def from_(self, collection: str) -> FromBuilder:
        """Data-plane DSL entry point. `from` is a Python keyword so we use `from_`."""
        return FromBuilder(self._config, collection)


def create_client(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    org_slug: str | None = None,
    project_slug: str | None = None,
    default_headers: dict[str, str] | None = None,
    retry_config: RetryConfig | None = None,
) -> K9oClient:
    """Construct a K9oClient bound to the supplied gateway baseUrl + auth + context.

    base_url is OPTIONAL: when omitted it defaults to the public cloud
    ('https://api.k9o.io', a convenience only). The host is never matched
    against a list of known domains: when it is a platform host
    ('api.<apex>' or 'api-staging.<apex>', any apex) and org_slug is set, the
    SDK composes the org host '<orgSlug>.<host>'. Any other host (an org
    host, an internal or air-gapped host, localhost) is used unchanged.
    Validates base_url at construct time — path-bearing URLs raise
    KError(K9O_INVALID_BASE_URL).

    Args:
      base_url: optional scheme + host (e.g. 'https://acme.api.corp.internal'
        or 'https://api.corp.internal'); defaults to the public cloud
      api_key: bearer token for default auth (per-call override is supported)
      org_slug: active org context; sent as 'x-k9o-org-slug' header
      project_slug: active project context; sent as 'x-k9o-project-slug' header
      default_headers: headers merged into every request
      retry_config: retry/backoff policy; None ⇒ defaults
        (3 retries, exponential) on idempotent methods + transient failures
    """
    resolved = resolve_base_url(base_url, org_slug)
    config = HttpClientConfig(
        base_url=resolved,
        api_key=api_key,
        org_slug=org_slug,
        project_slug=project_slug,
        default_headers=dict(default_headers or {}),
        retry_config=retry_config,
    )
    return K9oClient(config)
