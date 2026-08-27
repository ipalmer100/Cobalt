"""A SharePoint document library as a spec store, over Microsoft Graph.

Implements the same ``SpecStore`` contract as ``LocalStore``, so the parser,
writer, views and exception queue are unchanged -- they only ever saw bytes.
What differs is everything storage actually has to get right against a
remote, shared, rate-limited API:

**Identity survives renames.** A drive item's id is stable when the file is
renamed or moved between folders; its path is not. Keys are therefore item
ids, and the path is carried alongside purely for display.

**Writes are conditional.** Every item has an eTag, and an upload carrying
``If-Match`` is rejected with 412 when the stored eTag has moved on. That is
the only reliable way to notice that someone edited the same spec in Word
while it sat open in the grid, and it's why ``write`` raises ConflictError
rather than clobbering. The filesystem has no equivalent.

**Change detection is a delta query, not a file watcher.** There is no
inotify for SharePoint. ``/delta`` returns what changed since an opaque
token, which is both how the initial index is taken and how subsequent
polls stay cheap. (Graph webhooks would push instead of poll, but they need
a publicly reachable endpoint; polling works from anywhere and is the right
starting point.)

**Throttling is normal, not exceptional.** Graph answers 429 with a
``Retry-After`` under sustained load -- indexing thousands of specs is
exactly that -- so every request honours it rather than treating it as a
failure. 5xx gets the same treatment with backoff.

Auth is deliberately behind a one-method interface (``TokenProvider``) so
the app-only client-credentials flow this starts with can be swapped for
per-user delegated tokens later without touching anything here.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Protocol

from .storage import (
    ConflictError,
    StoreError,
    StoredItem,
    concurrent_read_many,
    is_hidden_or_lock_filename,
    is_spec_filename,
)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"

# Graph's own guidance is that a client should keep concurrency modest and
# back off rather than fan out hard; this is the download concurrency for
# indexing, where latency (not bandwidth) is the limit.
_DEFAULT_FETCH_CONCURRENCY = 8
_MAX_ATTEMPTS = 5
_MAX_BACKOFF_SECONDS = 30.0

# Uploading over this size must use a chunked upload session rather than a
# simple PUT. Graph's documented simple-upload ceiling is 250 MB, but the
# practical limit for reliability is far lower; specs run ~50 KB-3 MB, so
# this only guards against something unexpected.
_SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024


class TokenProvider(Protocol):
    """Supplies a bearer token. The seam between app-only and delegated auth."""

    def token(self) -> str: ...


class StaticToken:
    """A fixed token -- for tests, and for short-lived scripted runs."""

    def __init__(self, value: str) -> None:
        self._value = value

    def token(self) -> str:
        return self._value


class ClientCredentialsToken:
    """App-only auth: the app authenticates as itself, not as a person.

    Simplest thing that works, and what a test library should start with.
    Note the consequence for the audit trail: Graph sees one identity for
    everybody, so "who changed this" is only as trustworthy as whatever
    login the app puts in front of itself. Swapping this class for a
    delegated-token provider is what fixes that.
    """

    def __init__(self, tenant_id: str, client_id: str, client_secret: str, opener=None) -> None:  # noqa: ANN001
        self._url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        self._body = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            }
        ).encode()
        self._opener = opener or urllib.request.urlopen
        self._cached = ""
        self._expires_at = 0.0

    def token(self) -> str:
        # Refresh a minute early: a token that expires mid-index would fail
        # a request that had already been retried for other reasons.
        if self._cached and time.time() < self._expires_at - 60:
            return self._cached
        request = urllib.request.Request(
            self._url,
            data=self._body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=30) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:  # pragma: no cover - needs a tenant
            raise StoreError(
                f"Could not get a SharePoint token ({exc.code}). Check the tenant id, "
                "client id/secret, and that admin consent was granted."
            ) from exc
        self._cached = payload["access_token"]
        self._expires_at = time.time() + float(payload.get("expires_in", 3600))
        return self._cached


@dataclass
class GraphResponse:
    status: int
    headers: dict
    body: bytes

    def json(self) -> dict:
        return json.loads(self.body) if self.body else {}


class GraphClient:
    """Thin transport: auth header, retries, throttling. No spec knowledge."""

    def __init__(
        self,
        tokens: TokenProvider,
        opener=None,  # noqa: ANN001 - injected in tests
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        self._tokens = tokens
        self._opener = opener or urllib.request.urlopen
        self._sleep = sleep
        self._max_attempts = max_attempts

    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict | None = None,
    ) -> GraphResponse:
        if url.startswith("/"):
            url = GRAPH_ROOT + url
        attempt = 0
        while True:
            attempt += 1
            request = urllib.request.Request(url, data=body, method=method)
            request.add_header("Authorization", f"Bearer {self._tokens.token()}")
            for name, value in (headers or {}).items():
                request.add_header(name, value)
            try:
                with self._opener(request, timeout=60) as response:
                    return GraphResponse(
                        status=getattr(response, "status", 200),
                        headers=dict(getattr(response, "headers", {}) or {}),
                        body=response.read(),
                    )
            except urllib.error.HTTPError as exc:
                status = exc.code
                error_body = exc.read() if hasattr(exc, "read") else b""
                # 412 is not a failure to retry -- it means the caller's
                # precondition is genuinely stale, which is information.
                if status in (409, 412):
                    return GraphResponse(status, dict(exc.headers or {}), error_body)
                if status in (429, 500, 502, 503, 504) and attempt < self._max_attempts:
                    self._sleep(self._retry_delay(exc.headers, attempt))
                    continue
                raise StoreError(
                    f"SharePoint request failed ({status}) for {method} {url}: "
                    f"{error_body[:400].decode('utf-8', 'replace')}"
                ) from exc
            except urllib.error.URLError as exc:
                if attempt < self._max_attempts:
                    self._sleep(self._retry_delay(None, attempt))
                    continue
                raise StoreError(f"Could not reach SharePoint: {exc.reason}") from exc

    def _retry_delay(self, headers, attempt: int) -> float:  # noqa: ANN001
        """Honour Retry-After when Graph sends it -- it knows better than we
        do -- otherwise exponential backoff with jitter so a fleet of
        clients doesn't retry in lockstep."""
        if headers:
            retry_after = headers.get("Retry-After")
            if retry_after:
                try:
                    return min(float(retry_after), _MAX_BACKOFF_SECONDS)
                except (TypeError, ValueError):
                    pass
        return min(2.0 ** (attempt - 1) + random.random(), _MAX_BACKOFF_SECONDS)

    def paged(self, url: str) -> Iterator[dict]:
        """Walk @odata.nextLink to the end, yielding each page's payload."""
        while url:
            response = self.request("GET", url)
            payload = response.json()
            yield payload
            url = payload.get("@odata.nextLink", "")


class GraphStore:
    """One SharePoint document library (or a folder within one)."""

    def __init__(
        self,
        client: GraphClient,
        drive_id: str,
        root_path: str = "",
        label: str = "",
        fetch_concurrency: int = _DEFAULT_FETCH_CONCURRENCY,
    ) -> None:
        self._client = client
        self._drive_id = drive_id
        # Restrict to a folder inside the library, or "" for the whole thing.
        self._root_path = root_path.strip("/")
        self._label = label or f"SharePoint drive {drive_id}"
        self._fetch_concurrency = fetch_concurrency
        self._delta_link = ""

    # -- identity -------------------------------------------------------

    @property
    def root_label(self) -> str:
        return self._label

    def _drive(self) -> str:
        return f"/drives/{self._drive_id}"

    def _item_url(self, key: str) -> str:
        return f"{self._drive()}/items/{key}"

    # -- enumeration ----------------------------------------------------

    def list_specs(self) -> Iterable[StoredItem]:
        """Every spec in the library, via a delta walk.

        Using /delta rather than recursively listing children does double
        duty: it enumerates everything on the first call *and* leaves a token
        that makes "what changed since?" cheap, which is what stands in for
        a file watcher.
        """
        items: list[StoredItem] = []
        url = f"{self._drive()}/root:/{self._root_path}:/delta" if self._root_path else f"{self._drive()}/root/delta"
        for payload in self._client.paged(url):
            for raw in payload.get("value", []):
                item = self._to_item(raw)
                if item is not None:
                    items.append(item)
            if payload.get("@odata.deltaLink"):
                self._delta_link = payload["@odata.deltaLink"]
        return items

    def _to_item(self, raw: dict) -> StoredItem | None:
        """Translate a drive item, or None if it isn't a spec we track."""
        if "folder" in raw or raw.get("deleted"):
            return None
        name = raw.get("name", "")
        if not name or is_hidden_or_lock_filename(name) or not is_spec_filename(name):
            return None
        # parentReference.path looks like "/drive/root:/Daisy/Pouches"
        parent = (raw.get("parentReference") or {}).get("path", "")
        folder = parent.split("root:", 1)[-1].strip("/") if "root:" in parent else ""
        if self._root_path and folder.startswith(self._root_path):
            folder = folder[len(self._root_path):].strip("/")
        return StoredItem(
            key=raw["id"],
            name=name,
            folder=folder,
            etag=raw.get("eTag", "") or raw.get("cTag", ""),
            size=int(raw.get("size", 0) or 0),
        )

    def item(self, key: str) -> StoredItem | None:
        response = self._client.request("GET", self._item_url(key))
        return self._to_item(response.json())

    # -- content --------------------------------------------------------

    def read(self, key: str) -> tuple[bytes, str]:
        """Bytes plus the eTag they were read at, so a later write can carry
        it as a precondition."""
        meta = self._client.request("GET", self._item_url(key)).json()
        etag = meta.get("eTag", "") or meta.get("cTag", "")
        content = self._client.request("GET", f"{self._item_url(key)}/content")
        if not content.body:
            raise StoreError(f"SharePoint returned no content for item {key}")
        return content.body, etag

    def read_many(self, keys: list[str]) -> Iterator[tuple[str, bytes | None, str]]:
        """Overlap the downloads -- against a remote library the round-trip
        latency, not parsing, is what makes indexing slow."""
        return concurrent_read_many(self.read, keys, self._fetch_concurrency)

    def write(self, key: str, data: bytes, etag: str | None = None) -> str:
        if len(data) > _SIMPLE_UPLOAD_LIMIT:
            return self._write_chunked(key, data, etag)
        headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        if etag:
            headers["If-Match"] = etag
        response = self._client.request(
            "PUT", f"{self._item_url(key)}/content", body=data, headers=headers
        )
        if response.status in (409, 412):
            raise ConflictError(key)
        payload = response.json()
        return payload.get("eTag", "") or payload.get("cTag", "")

    def _write_chunked(self, key: str, data: bytes, etag: str | None) -> str:
        """Upload session, for the rare spec too large for a simple PUT."""
        body = json.dumps({"item": {"@microsoft.graph.conflictBehavior": "replace"}}).encode()
        headers = {"Content-Type": "application/json"}
        if etag:
            headers["If-Match"] = etag
        session = self._client.request(
            "POST", f"{self._item_url(key)}/createUploadSession", body=body, headers=headers
        )
        if session.status in (409, 412):
            raise ConflictError(key)
        upload_url = session.json().get("uploadUrl")
        if not upload_url:
            raise StoreError(f"SharePoint did not return an upload URL for item {key}")

        chunk_size = 5 * 1024 * 1024
        total = len(data)
        last: GraphResponse | None = None
        for start in range(0, total, chunk_size):
            chunk = data[start : start + chunk_size]
            end = start + len(chunk) - 1
            last = self._client.request(
                "PUT",
                upload_url,
                body=chunk,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{total}",
                },
            )
        payload = last.json() if last else {}
        return payload.get("eTag", "") or payload.get("cTag", "")

    def create(self, folder: str, name: str, data: bytes) -> StoredItem:
        """Add a spec. conflictBehavior=fail so duplicating onto an existing
        spec number is refused rather than silently overwriting it."""
        parts = [p for p in (self._root_path, folder) if p]
        prefix = "/".join(parts)
        path = f"{prefix}/{name}" if prefix else name
        encoded = urllib.parse.quote(path)
        url = (
            f"{self._drive()}/root:/{encoded}:/content"
            "?@microsoft.graph.conflictBehavior=fail"
        )
        response = self._client.request(
            "PUT",
            url,
            body=data,
            headers={"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        )
        if response.status == 409:
            raise StoreError(f"Destination already exists: {path}")
        item = self._to_item(response.json())
        if item is None:
            raise StoreError(f"SharePoint accepted {path} but returned no usable item")
        return item

    def delete(self, key: str) -> None:
        self._client.request("DELETE", self._item_url(key))

    # -- change notification --------------------------------------------

    def changes(self) -> list[str]:
        """Keys changed since the last call. Cheap: Graph returns only what
        moved, and the token advances each time."""
        if not self._delta_link:
            self.list_specs()  # establishes the token
            return []
        changed: list[str] = []
        url = self._delta_link
        while url:
            payload = self._client.request("GET", url).json()
            for raw in payload.get("value", []):
                if "folder" in raw:
                    continue
                name = raw.get("name", "")
                if raw.get("deleted") or (name and is_spec_filename(name)):
                    changed.append(raw["id"])
            url = payload.get("@odata.nextLink", "")
            if payload.get("@odata.deltaLink"):
                self._delta_link = payload["@odata.deltaLink"]
        return changed

    def watch(
        self,
        on_change: Callable[[list[str]], None],
        interval: float = 15.0,
        stop_event=None,  # noqa: ANN001
    ) -> Callable[[], None]:
        """Poll for changes on a background thread.

        Polling rather than Graph webhooks on purpose: a webhook subscription
        needs an endpoint SharePoint can reach from the internet, which an
        internal deployment usually can't offer. Delta polling works from
        anywhere and costs one request per interval when nothing changed.
        """
        import threading

        stop = stop_event or threading.Event()

        def loop() -> None:
            while not stop.wait(interval):
                try:
                    changed = self.changes()
                except StoreError:
                    continue  # transient; the next tick tries again
                if changed:
                    try:
                        on_change(changed)
                    except Exception:  # noqa: BLE001 - a listener must not kill polling
                        pass

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()

        def stop_watching() -> None:
            stop.set()
            thread.join(timeout=2)

        return stop_watching


# --------------------------------------------------------------------------
# Discovery helpers -- turning what a person can copy out of a browser into
# the drive id the store needs.
# --------------------------------------------------------------------------


def resolve_drive_from_site(client: GraphClient, hostname: str, site_path: str, library: str = "") -> tuple[str, str]:
    """Find a document library's drive id from a SharePoint site URL.

    People have a site URL, not a drive id -- given
    ``https://contoso.sharepoint.com/sites/Packaging`` the hostname is
    ``contoso.sharepoint.com`` and the site path ``/sites/Packaging``.
    Returns ``(drive_id, label)``; ``library`` picks a specific document
    library by name when a site has several, defaulting to the first.
    """
    site = client.request("GET", f"/sites/{hostname}:{site_path}").json()
    site_id = site.get("id")
    if not site_id:
        raise StoreError(f"No SharePoint site found at {hostname}{site_path}")
    drives = client.request("GET", f"/sites/{site_id}/drives").json().get("value", [])
    if not drives:
        raise StoreError(f"Site {site_path} has no document libraries")
    chosen = drives[0]
    if library:
        for drive in drives:
            if drive.get("name", "").lower() == library.lower():
                chosen = drive
                break
        else:
            names = ", ".join(d.get("name", "?") for d in drives)
            raise StoreError(f"No library named {library!r}. Available: {names}")
    label = f"{site.get('displayName', site_path)} / {chosen.get('name', 'Documents')}"
    return chosen["id"], label
