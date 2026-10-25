"""Tests for URL grammar validation + path builders."""

import pytest

from k9o import (
    KError,
    org_path,
    platform_path,
    project_path,
    resolve_base_url,
    validate_base_url,
    validate_slug,
)


class TestValidateBaseUrl:
    def test_accepts_https_host_only(self):
        assert validate_base_url("https://api.k9o.io") == "https://api.k9o.io"

    def test_accepts_subdomain(self):
        assert validate_base_url("https://acme.api.k9o.io") == "https://acme.api.k9o.io"

    def test_accepts_localhost_with_port(self):
        assert validate_base_url("http://localhost:8080") == "http://localhost:8080"

    def test_normalises_trailing_slash(self):
        assert validate_base_url("https://api.k9o.io/") == "https://api.k9o.io"

    def test_rejects_path_segment(self):
        with pytest.raises(KError) as exc:
            validate_base_url("https://api.k9o.io/v2")
        assert exc.value.code == "K9O_INVALID_BASE_URL"

    def test_rejects_websocket_scheme(self):
        with pytest.raises(KError) as exc:
            validate_base_url("wss://api.k9o.io")
        assert exc.value.code == "K9O_INVALID_BASE_URL"

    def test_rejects_missing_scheme(self):
        with pytest.raises(KError) as exc:
            validate_base_url("api.k9o.io")
        assert exc.value.code == "K9O_INVALID_BASE_URL"

    def test_rejects_query_string(self):
        with pytest.raises(KError) as exc:
            validate_base_url("https://api.k9o.io?x=1")
        assert exc.value.code == "K9O_INVALID_BASE_URL"


class TestResolveBaseUrl:
    def test_default_apex_when_omitted_no_org(self):
        assert resolve_base_url(None) == "https://api.k9o.io"

    def test_omitted_base_url_with_org_derives_subdomain(self):
        assert resolve_base_url(None, "acme") == "https://acme.api.k9o.io"

    def test_explicit_apex_with_org_derives_subdomain(self):
        assert resolve_base_url("https://api.k9o.io", "acme") == "https://acme.api.k9o.io"

    def test_apex_with_trailing_slash_and_org_derives_subdomain(self):
        assert resolve_base_url("https://api.k9o.io/", "acme") == "https://acme.api.k9o.io"

    def test_explicit_subdomain_passthrough_unchanged(self):
        assert resolve_base_url("https://acme.api.k9o.io", "acme") == "https://acme.api.k9o.io"

    def test_explicit_subdomain_ignores_mismatched_org(self):
        # host is not the bare apex, so org_slug is NOT applied — passthrough.
        assert resolve_base_url("https://acme.api.k9o.io", "other") == "https://acme.api.k9o.io"

    def test_self_hosted_host_passthrough_unchanged(self):
        assert resolve_base_url("https://platform.acme.internal", "acme") == "https://platform.acme.internal"

    def test_dev_host_passthrough_unchanged(self):
        assert resolve_base_url("http://localhost:8080", "acme") == "http://localhost:8080"

    def test_apex_without_org_returns_apex(self):
        assert resolve_base_url("https://api.k9o.io") == "https://api.k9o.io"

    def test_invalid_base_url_still_rejected(self):
        with pytest.raises(KError) as exc:
            resolve_base_url("https://api.k9o.io/v2", "acme")
        assert exc.value.code == "K9O_INVALID_BASE_URL"

    def test_invalid_org_slug_rejected_on_apex(self):
        with pytest.raises(KError) as exc:
            resolve_base_url("https://api.k9o.io", "Acme")
        assert exc.value.code == "K9O_INVALID_FIELD_VALUE"

    def test_staging_apex_with_org_derives_subdomain(self):
        assert resolve_base_url("https://api-staging.k9o.io", "acme") == "https://acme.api-staging.k9o.io"

    def test_staging_explicit_subdomain_passthrough_unchanged(self):
        assert resolve_base_url("https://acme.api-staging.k9o.io", "acme") == "https://acme.api-staging.k9o.io"

    def test_staging_apex_without_org_returns_apex(self):
        assert resolve_base_url("https://api-staging.k9o.io") == "https://api-staging.k9o.io"

    def test_invalid_org_slug_rejected_on_staging_apex(self):
        with pytest.raises(KError) as exc:
            resolve_base_url("https://api-staging.k9o.io", "Acme")
        assert exc.value.code == "K9O_INVALID_FIELD_VALUE"


class TestValidateSlug:
    def test_accepts_canonical_slugs(self):
        validate_slug("acme", "org")
        validate_slug("member-portal", "project")
        validate_slug("a1", "org")

    def test_rejects_uppercase(self):
        with pytest.raises(KError) as exc:
            validate_slug("Acme", "org")
        assert exc.value.code == "K9O_INVALID_FIELD_VALUE"

    def test_rejects_leading_digit(self):
        with pytest.raises(KError):
            validate_slug("1acme", "org")

    def test_rejects_trailing_hyphen(self):
        with pytest.raises(KError):
            validate_slug("acme-", "org")

    def test_rejects_single_char(self):
        with pytest.raises(KError):
            validate_slug("a", "org")


class TestPathBuilders:
    def test_project_path(self):
        assert project_path("member-portal", "collections/posts/documents") == "/@member-portal/collections/posts/documents"

    def test_project_path_strips_leading_slash(self):
        assert project_path("acme", "/project") == "/@acme/project"

    def test_org_path(self):
        assert org_path("projects") == "/projects"

    def test_platform_path(self):
        assert platform_path("discovery/projects") == "/discovery/projects"
