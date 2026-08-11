"""A stand-in for Microsoft Graph's drive API.

Graph is unreachable from the build environment, so the store is exercised
against this instead. It is deliberately not a stub that says yes: it
reproduces the behaviours that actually shape the client, because those are
what would otherwise only be discovered in production —

- eTags that change on every write, and ``If-Match`` returning **412** when
  the caller's precondition is stale,
- ``@odata.nextLink`` paging, so a library larger than one page is walked,
- ``/delta`` handing back an ``@odata.deltaLink`` and then reporting only
  what changed since it,
- **429** with ``Retry-After`` on demand, so throttling is a tested path,
- ``conflictBehavior=fail`` returning **409** rather than overwriting.

It speaks the urllib interface the client uses, so no network is involved.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from dataclasses import dataclass, field


@dataclass
class FakeItem:
    id: str
    name: str
    folder_path: str  # relative to the drive root, "" at the root
    content: bytes
    etag: str = "etag-1"
    version: int = 1
    deleted: bool = False

    @property
    def key(self) -> str:
        """Same value the store calls a key -- keeps tests reading naturally."""
        return self.id

    def to_json(self) -> dict:
        payload = {
            "id": self.id,
            "name": self.name,
            "size": len(self.content),
            "eTag": self.etag,
            "file": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "parentReference": {
                "path": f"/drive/root:/{self.folder_path}" if self.folder_path else "/drive/root:"
            },
        }
        if self.deleted:
            payload["deleted"] = {"state": "deleted"}
        return payload


class _Response(io.BytesIO):
    """Minimal stand-in for what urlopen returns."""

    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None) -> None:
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        self.close()


@dataclass
class FakeGraph:
    """Holds items and answers requests. ``requests`` records every call so a
    test can assert on retry counts and concurrency."""

    drive_id: str = "drive-1"
    items: dict = field(default_factory=dict)
    requests: list = field(default_factory=list)
    page_size: int = 100
    # Queue of statuses to inject before the real answer, e.g. [429, 429].
    inject_failures: list = field(default_factory=list)
    delta_tokens: dict = field(default_factory=dict)
    _next_id: int = 1

    # -- fixture helpers ------------------------------------------------

    def add(self, name: str, content: bytes, folder: str = "") -> FakeItem:
        item = FakeItem(id=f"item-{self._next_id}", name=name, folder_path=folder, content=content)
        self._next_id += 1
        self.items[item.id] = item
        return item

    def touch(self, key: str, content: bytes | None = None) -> None:
        """Simulate somebody else saving the file (in Word, say)."""
        item = self.items[key]
        item.version += 1
        item.etag = f"etag-{item.version}"
        if content is not None:
            item.content = content

    # -- the urlopen-compatible entry point -----------------------------

    def opener(self, request, timeout=None):  # noqa: ANN001, ARG002
        url = request.full_url
        method = request.method or "GET"
        self.requests.append((method, url))

        if self.inject_failures:
            status = self.inject_failures.pop(0)
            headers = {"Retry-After": "0"} if status == 429 else {}
            raise urllib.error.HTTPError(url, status, "injected", headers, io.BytesIO(b"{}"))

        path = url.split("graph.microsoft.com/v1.0", 1)[-1] if "graph.microsoft.com" in url else url
        handler = self._route(method, path, request)
        if handler is None:
            raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b"{}"))
        return handler

    def _route(self, method: str, path: str, request):  # noqa: ANN001
        base, _, query = path.partition("?")
        params = urllib.parse.parse_qs(query)

        if base.endswith("/delta") or "/delta" in base:
            return self._delta(params)

        # /drives/{id}/items/{key}/content
        if "/items/" in base and base.endswith("/content"):
            key = base.split("/items/", 1)[1].rsplit("/content", 1)[0]
            if method == "GET":
                return self._get_content(key)
            if method == "PUT":
                return self._put_content(key, request)

        if "/items/" in base and base.endswith("/createUploadSession"):
            key = base.split("/items/", 1)[1].rsplit("/createUploadSession", 1)[0]
            return self._create_upload_session(key, request)

        # /drives/{id}/root:/path:/content  -- create by path
        if "/root:/" in base and base.endswith(":/content") and method == "PUT":
            encoded = base.split("/root:/", 1)[1].rsplit(":/content", 1)[0]
            return self._create_by_path(urllib.parse.unquote(encoded), request, params)

        # /drives/{id}/items/{key}  -- metadata or delete
        if "/items/" in base:
            key = base.split("/items/", 1)[1]
            if method == "DELETE":
                self.items.pop(key, None)
                return _Response(b"", status=204)
            item = self.items.get(key)
            if item is None:
                return None
            return _Response(json.dumps(item.to_json()).encode())

        return None

    # -- handlers -------------------------------------------------------

    def _live_items(self) -> list[FakeItem]:
        return [i for i in self.items.values() if not i.deleted]

    def _delta(self, params: dict):
        token = (params.get("token") or [""])[0]
        skip = int((params.get("$skiptoken") or ["0"])[0])

        if token:
            changed = self.delta_tokens.get(token, [])
            body = {
                "value": [self.items[k].to_json() for k in changed if k in self.items],
                "@odata.deltaLink": self._new_delta_link(),
            }
            return _Response(json.dumps(body).encode())

        everything = self._live_items()
        page = everything[skip : skip + self.page_size]
        body: dict = {"value": [i.to_json() for i in page]}
        if skip + self.page_size < len(everything):
            body["@odata.nextLink"] = (
                f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root/delta"
                f"?$skiptoken={skip + self.page_size}"
            )
        else:
            body["@odata.deltaLink"] = self._new_delta_link()
        return _Response(json.dumps(body).encode())

    def _new_delta_link(self) -> str:
        token = f"tok-{len(self.delta_tokens) + 1}"
        self.delta_tokens[token] = []
        return (
            f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root/delta?token={token}"
        )

    def record_change(self, key: str) -> None:
        """Mark an item as changed for every outstanding delta token."""
        for changed in self.delta_tokens.values():
            if key not in changed:
                changed.append(key)

    def _get_content(self, key: str):
        item = self.items.get(key)
        if item is None:
            return None
        return _Response(item.content)

    def _put_content(self, key: str, request):  # noqa: ANN001
        item = self.items.get(key)
        if item is None:
            return None
        precondition = request.get_header("If-match")
        if precondition and precondition != item.etag:
            raise urllib.error.HTTPError(
                request.full_url, 412, "precondition failed", {}, io.BytesIO(b"{}")
            )
        item.content = request.data
        item.version += 1
        item.etag = f"etag-{item.version}"
        self.record_change(key)
        return _Response(json.dumps(item.to_json()).encode())

    def _create_upload_session(self, key: str, request):  # noqa: ANN001
        item = self.items.get(key)
        if item is None:
            return None
        precondition = request.get_header("If-match")
        if precondition and precondition != item.etag:
            raise urllib.error.HTTPError(
                request.full_url, 412, "precondition failed", {}, io.BytesIO(b"{}")
            )
        body = {"uploadUrl": f"https://upload.example/session/{key}"}
        return _Response(json.dumps(body).encode())

    def _create_by_path(self, path: str, request, params: dict):  # noqa: ANN001
        folder, _, name = path.rpartition("/")
        behaviour = (params.get("@microsoft.graph.conflictBehavior") or ["replace"])[0]
        for item in self._live_items():
            if item.name == name and item.folder_path == folder:
                if behaviour == "fail":
                    raise urllib.error.HTTPError(
                        request.full_url, 409, "nameAlreadyExists", {}, io.BytesIO(b"{}")
                    )
                item.content = request.data
                return _Response(json.dumps(item.to_json()).encode())
        created = self.add(name, request.data, folder)
        self.record_change(created.id)
        return _Response(json.dumps(created.to_json()).encode())


def upload_session_opener(fake: FakeGraph):
    """Handles the chunk PUTs to the (non-Graph) upload URL, delegating
    everything else to the fake."""
    import urllib.parse as _parse

    def opener(request, timeout=None):  # noqa: ANN001, ARG001
        url = request.full_url
        if url.startswith("https://upload.example/session/"):
            key = _parse.urlparse(url).path.rsplit("/", 1)[-1]
            item = fake.items[key]
            content_range = request.get_header("Content-range", "")
            start = int(content_range.split()[1].split("-")[0]) if content_range else 0
            if start == 0:
                item.content = b""
            item.content += request.data
            item.version += 1
            item.etag = f"etag-{item.version}"
            fake.requests.append(("PUT", url))
            return _Response(json.dumps(item.to_json()).encode())
        return fake.opener(request, timeout)

    return opener
