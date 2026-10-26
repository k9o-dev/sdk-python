"""
Storage namespace — `client.storage.*` buckets and objects.

Per-project logical buckets and the objects in them, against
`/@<project_slug>/storage/buckets...`. Bucket names are logical: the platform
resolves them to a physical store.

Wire mapping (project-plane):
  - create_bucket(name, ...)        POST   /@<slug>/storage/buckets
  - list_buckets()                  GET    /@<slug>/storage/buckets
  - get_bucket(name)                GET    /@<slug>/storage/buckets/<name>
  - update_bucket(name, ...)        PATCH  /@<slug>/storage/buckets/<name>
  - delete_bucket(name, empty=)     DELETE /@<slug>/storage/buckets/<name>[?empty=true]
  - from_(bucket).upload(...)       POST   .../buckets/<b>/objects        (multipart/form-data)
  - from_(bucket).create_signed_url POST   .../buckets/<b>/objects/sign   (expires_in required)
  - from_(bucket).list(prefix=)     GET    .../buckets/<b>/objects[?prefix=]
  - from_(bucket).remove(path)      DELETE .../buckets/<b>/objects?path=

Every method has an `_async` twin. Not offered by design: a signed PUT (the
gateway has no route for it), copy, and signed-URL transforms. Object bytes are
sent as given and never placed in an error the SDK constructs. Bucket names and
object paths are URL-encoded and never rewritten (`..` or a leading `/` reach
the server, which decides).
"""

from __future__ import annotations

import json
from typing import Any, BinaryIO, Mapping, Sequence, Union
from urllib.parse import quote

from .envelope import Envelope
from .errors import KError
from .http import HttpClientConfig, request, request_async
from .url_grammar import project_path

MAX_EXPIRES_IN = 604_800

#: Sentinel: "argument not given" (distinct from None, which clears a field on update).
UNSET: Any = type("_Unset", (), {"__repr__": lambda self: "UNSET", "__bool__": lambda self: False})()

UploadData = Union[str, bytes, bytearray, memoryview, BinaryIO]


def _require_project_slug(config: HttpClientConfig) -> str:
    if not config.project_slug:
        raise KError(
            code="K9O_MISSING_PROJECT_CONTEXT",
            message="client.storage buckets and objects require a bound project_slug (per-project resource)",
            context={},
            recommendation="Pass project_slug when constructing the client.",
        )
    return config.project_slug


def _buckets_path(config: HttpClientConfig, suffix: str = "") -> str:
    return project_path(_require_project_slug(config), f"storage/buckets{suffix}")


def _bucket_path(config: HttpClientConfig, name: str, suffix: str = "") -> str:
    if not name:
        raise KError(
            code="K9O_INVALID_FIELD_VALUE",
            message="bucket name must not be empty",
            context={"field": "bucket", "reason": "empty"},
        )
    if name in (".", ".."):
        # Survive percent-encoding and are collapsed as dot segments by URL layers before the
        # request leaves, so the bucket would address a different route. No bucket can be named so.
        raise KError(
            code="K9O_INVALID_FIELD_VALUE",
            message="bucket name must not be '.' or '..'",
            context={"field": "bucket", "reason": "dot_segment"},
        )
    return _buckets_path(config, f"/{quote(name, safe='')}{suffix}")


def _require_object_path(path: str) -> None:
    if not path:
        raise KError(
            code="K9O_INVALID_FIELD_VALUE",
            message="object path must not be empty",
            context={"field": "path", "reason": "empty"},
        )


def _require_expires_in(expires_in: Any) -> int:
    # bool is an int subclass; True is not a lifetime.
    if (
        not isinstance(expires_in, int)
        or isinstance(expires_in, bool)
        or expires_in < 1
        or expires_in > MAX_EXPIRES_IN
    ):
        raise KError(
            code="K9O_INVALID_FIELD_VALUE",
            message=f"expires_in is required and must be an integer from 1 to {MAX_EXPIRES_IN} seconds",
            context={"field": "expiresIn", "reason": "out_of_range"},
            recommendation="Pass an explicit expires_in; signed URLs have no default lifetime.",
        )
    return expires_in


def _given(**fields: Any) -> dict[str, Any]:
    """Drop UNSET entries; keep None (it means 'clear' / 'any')."""
    return {k: v for k, v in fields.items() if v is not UNSET}


def _create_body(name, public, file_size_limit, allowed_mime_types, versioning, delete_after_days, byos_binding_id):
    if allowed_mime_types is not UNSET and allowed_mime_types is not None:
        allowed_mime_types = list(allowed_mime_types)
    return {
        "name": name,
        **_given(
            public=public,
            fileSizeLimit=file_size_limit,
            allowedMimeTypes=allowed_mime_types,
            versioning=versioning,
            deleteAfterDays=delete_after_days,
            byosBindingId=byos_binding_id,
        ),
    }


def _upload_multipart(
    path: str,
    data: UploadData,
    content_type: str | None,
    upsert: bool,
    metadata: Mapping[str, str] | None,
) -> dict[str, Any]:
    _require_object_path(path)
    if isinstance(data, str):
        data = data.encode("utf-8")
    elif isinstance(data, (bytearray, memoryview)):
        data = bytes(data)
    filename = path.rsplit("/", 1)[-1] or "file"
    form: dict[str, str] = {"path": path}
    if content_type is not None:
        form["contentType"] = content_type
    form["upsert"] = "true" if upsert is True else "false"
    if metadata is not None:
        form["metadata"] = json.dumps(dict(metadata))
    file_part = (filename, data) if content_type is None else (filename, data, content_type)
    return {"files": {"file": file_part}, "data": form}


class BucketHandle:
    """A handle on one bucket: `client.storage.from_("avatars")`."""

    def __init__(self, config: HttpClientConfig, bucket: str) -> None:
        self._config = config
        self._bucket = bucket

    def _objects(self, suffix: str = "") -> str:
        return _bucket_path(self._config, self._bucket, f"/objects{suffix}")

    # -- upload ---------------------------------------------------------
    def upload(
        self,
        path: str,
        data: UploadData,
        *,
        content_type: str | None = None,
        upsert: bool = False,
        metadata: Mapping[str, str] | None = None,
    ) -> Envelope:
        """POST .../objects (multipart). `upsert=False` refuses to overwrite (409 K9O_ALREADY_EXISTS)."""
        mp = _upload_multipart(path, data, content_type, upsert, metadata)
        return request(self._config, method="POST", path=self._objects(), multipart=mp)

    async def upload_async(
        self,
        path: str,
        data: UploadData,
        *,
        content_type: str | None = None,
        upsert: bool = False,
        metadata: Mapping[str, str] | None = None,
    ) -> Envelope:
        mp = _upload_multipart(path, data, content_type, upsert, metadata)
        return await request_async(self._config, method="POST", path=self._objects(), multipart=mp)

    # -- signed URL -----------------------------------------------------
    def _sign_body(self, path: str, expires_in: Any, download: bool | None) -> dict[str, Any]:
        _require_object_path(path)
        body: dict[str, Any] = {"path": path, "expiresIn": _require_expires_in(expires_in)}
        if download is not None:
            body["download"] = download
        return body

    def create_signed_url(self, path: str, *, expires_in: int, download: bool | None = None) -> Envelope:
        """POST .../objects/sign. `expires_in` (seconds, 1..604800) is required; no default."""
        body = self._sign_body(path, expires_in, download)
        return request(self._config, method="POST", path=self._objects("/sign"), body=body)

    async def create_signed_url_async(
        self, path: str, *, expires_in: int, download: bool | None = None
    ) -> Envelope:
        body = self._sign_body(path, expires_in, download)
        return await request_async(self._config, method="POST", path=self._objects("/sign"), body=body)

    # -- list / remove --------------------------------------------------
    def list(self, *, prefix: str | None = None) -> Envelope:
        """GET .../objects[?prefix=]."""
        return request(
            self._config, method="GET", path=self._objects(),
            query={"prefix": prefix} if prefix is not None else None,
        )

    async def list_async(self, *, prefix: str | None = None) -> Envelope:
        return await request_async(
            self._config, method="GET", path=self._objects(),
            query={"prefix": prefix} if prefix is not None else None,
        )

    def remove(self, path: str) -> Envelope:
        """DELETE .../objects?path=."""
        _require_object_path(path)
        return request(self._config, method="DELETE", path=self._objects(), query={"path": path})

    async def remove_async(self, path: str) -> Envelope:
        _require_object_path(path)
        return await request_async(self._config, method="DELETE", path=self._objects(), query={"path": path})


class StorageNamespace:
    """`client.storage.*`."""

    def __init__(self, config: HttpClientConfig) -> None:
        self._config = config

    def from_(self, bucket: str) -> BucketHandle:
        """A handle on one bucket for object operations (`from` is a Python keyword)."""
        return BucketHandle(self._config, bucket)

    # -- buckets --------------------------------------------------------
    def list_buckets(self) -> Envelope:
        return request(self._config, method="GET", path=_buckets_path(self._config))

    async def list_buckets_async(self) -> Envelope:
        return await request_async(self._config, method="GET", path=_buckets_path(self._config))

    def get_bucket(self, name: str) -> Envelope:
        return request(self._config, method="GET", path=_bucket_path(self._config, name))

    async def get_bucket_async(self, name: str) -> Envelope:
        return await request_async(self._config, method="GET", path=_bucket_path(self._config, name))

    def create_bucket(
        self,
        name: str,
        *,
        public: bool = UNSET,
        file_size_limit: int = UNSET,
        allowed_mime_types: Sequence[str] | None = UNSET,
        versioning: bool = UNSET,
        delete_after_days: int = UNSET,
        byos_binding_id: str = UNSET,
    ) -> Envelope:
        """POST .../buckets. Name: 3..63 lowercase letters, digits, hyphens (else K9O_INVALID_BUCKET_NAME)."""
        body = _create_body(name, public, file_size_limit, allowed_mime_types, versioning,
                            delete_after_days, byos_binding_id)
        return request(self._config, method="POST", path=_buckets_path(self._config), body=body)

    async def create_bucket_async(
        self,
        name: str,
        *,
        public: bool = UNSET,
        file_size_limit: int = UNSET,
        allowed_mime_types: Sequence[str] | None = UNSET,
        versioning: bool = UNSET,
        delete_after_days: int = UNSET,
        byos_binding_id: str = UNSET,
    ) -> Envelope:
        body = _create_body(name, public, file_size_limit, allowed_mime_types, versioning,
                            delete_after_days, byos_binding_id)
        return await request_async(self._config, method="POST", path=_buckets_path(self._config), body=body)

    def _update_body(self, public, file_size_limit, allowed_mime_types, versioning, delete_after_days,
                     byos_binding_id) -> dict[str, Any]:
        if allowed_mime_types is not UNSET and allowed_mime_types is not None:
            allowed_mime_types = list(allowed_mime_types)
        return _given(
            public=public,
            fileSizeLimit=file_size_limit,
            allowedMimeTypes=allowed_mime_types,
            versioning=versioning,
            deleteAfterDays=delete_after_days,
            byosBindingId=byos_binding_id,
        )

    def update_bucket(
        self,
        name: str,
        *,
        public: bool = UNSET,
        file_size_limit: int | None = UNSET,
        allowed_mime_types: Sequence[str] | None = UNSET,
        versioning: bool = UNSET,
        delete_after_days: int | None = UNSET,
        byos_binding_id: str | None = UNSET,
    ) -> Envelope:
        """PATCH .../buckets/<name>. Only given fields are sent; `None` clears a limit / allows any type /
        unlinks the storage location."""
        body = self._update_body(public, file_size_limit, allowed_mime_types, versioning,
                                 delete_after_days, byos_binding_id)
        return request(self._config, method="PATCH", path=_bucket_path(self._config, name), body=body)

    async def update_bucket_async(
        self,
        name: str,
        *,
        public: bool = UNSET,
        file_size_limit: int | None = UNSET,
        allowed_mime_types: Sequence[str] | None = UNSET,
        versioning: bool = UNSET,
        delete_after_days: int | None = UNSET,
        byos_binding_id: str | None = UNSET,
    ) -> Envelope:
        body = self._update_body(public, file_size_limit, allowed_mime_types, versioning,
                                 delete_after_days, byos_binding_id)
        return await request_async(self._config, method="PATCH", path=_bucket_path(self._config, name), body=body)

    def delete_bucket(self, name: str, *, empty: bool = False) -> Envelope:
        """DELETE .../buckets/<name>. A non-empty bucket is refused (409 bucket_not_empty) unless
        `empty=True`, which sends `?empty=true` and purges its objects first."""
        return request(self._config, method="DELETE", path=_bucket_path(self._config, name),
                       query={"empty": "true"} if empty is True else None)

    async def delete_bucket_async(self, name: str, *, empty: bool = False) -> Envelope:
        return await request_async(self._config, method="DELETE", path=_bucket_path(self._config, name),
                                   query={"empty": "true"} if empty is True else None)
