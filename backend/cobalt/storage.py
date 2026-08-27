"""Where the spec documents live.

Everything above this module works on *bytes* -- the parser and writer never
touch a filesystem (python-docx reads and writes file-like objects happily),
which is what lets the same spec intelligence run against a local folder or
a SharePoint library without change.

A store's job is narrow:

- enumerate the spec documents it holds,
- hand over one's bytes, and take modified bytes back,
- say when something changed underneath us.

Two implementations matter. ``LocalStore`` is the desktop app: a folder on
disk, watched with the OS's own file notifications. ``GraphStore`` (see
graph_store.py) is a SharePoint document library reached over Microsoft
Graph. They differ in ways the interface has to acknowledge rather than
paper over:

- *Identity.* A local spec is identified by its absolute path. A SharePoint
  spec is identified by an opaque drive-item id that survives renames and
  moves, with the path being merely its current location. So callers key
  off ``StoredItem.key`` and treat it as opaque.
- *Concurrency.* A filesystem write is last-one-wins and silent. Graph
  gives every item an eTag and will reject a write whose precondition no
  longer matches -- which is the only way to notice that someone edited the
  same spec in Word while you had it open. ``write()`` therefore takes the
  eTag the bytes were read at, and raises ConflictError instead of
  overwriting a stranger's change. Local storage has no equivalent, so it
  reports an eTag derived from size and mtime: not cryptographic, but
  enough to catch the realistic case of the file changing under us.
- *Fetching in bulk.* Indexing a library is CPU-bound on parsing but
  IO-bound on fetching, and the balance is completely different for a local
  disk versus a few thousand HTTPS round trips. ``read_many`` lets each
  store fetch however suits it while yielding a uniform stream of bytes for
  the parsing pool.
"""

from __future__ import annotations

import hashlib
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Protocol

_LOCK_OR_HIDDEN_PREFIXES = ("~$", ".")
_SPEC_SUFFIXES = (".docx", ".doc")


def is_spec_filename(name: str) -> bool:
    return name.lower().endswith(_SPEC_SUFFIXES)


def is_hidden_or_lock_filename(name: str) -> bool:
    return name.startswith(_LOCK_OR_HIDDEN_PREFIXES)


class StoreError(RuntimeError):
    """Storage failed in a way the caller should surface, not retry blindly."""


class ConflictError(StoreError):
    """The document changed since it was read, so the write was refused.

    Raised rather than silently overwriting: in a controlled-document system
    quietly discarding someone else's edit is the worst possible outcome.
    """

    def __init__(self, key: str, message: str = "") -> None:
        super().__init__(
            message
            or f"{key} was changed by someone else since it was opened. "
            "Reload the spec and re-apply the edit."
        )
        self.key = key


@dataclass(frozen=True)
class StoredItem:
    """One spec document, as the store sees it."""

    key: str  # opaque, stable identity (local: absolute path; Graph: item id)
    name: str  # file name including extension
    folder: str  # folder relative to the store root, "" at the root
    etag: str  # version marker; pass back to write() as a precondition
    size: int = 0

    @property
    def display_path(self) -> str:
        """Where a person would say this spec lives, relative to the root."""
        return f"{self.folder}/{self.name}" if self.folder else self.name


class SpecStore(Protocol):
    """The contract every backend implements. Deliberately small."""

    @property
    def root_label(self) -> str:
        """Human-readable name for what's open (a path, or a library URL)."""

    def list_specs(self) -> Iterable[StoredItem]: ...

    def read(self, key: str) -> tuple[bytes, str]:
        """The document's bytes and the eTag they were read at."""

    def read_many(self, keys: list[str]) -> Iterator[tuple[str, bytes | None, str]]:
        """Yield (key, bytes, etag) for each key, bytes None if unreadable.
        Order is not guaranteed -- callers key off the returned key."""

    def write(self, key: str, data: bytes, etag: str | None = None) -> str:
        """Replace the document's bytes, returning its new eTag. Raises
        ConflictError when `etag` no longer matches what's stored."""

    def create(self, folder: str, name: str, data: bytes) -> StoredItem:
        """Add a new document. Raises StoreError if it already exists."""

    def delete(self, key: str) -> None: ...

    def watch(self, on_change: Callable[[list[str]], None]) -> Callable[[], None]:
        """Start reporting changes; returns a function that stops watching.
        `on_change` receives the keys that changed, possibly coalesced."""


# --------------------------------------------------------------------------
# Local filesystem
# --------------------------------------------------------------------------


def _local_etag(path: Path) -> str:
    """Cheap version marker. Not a hash of the content -- hashing every file
    on every listing would dominate indexing a large library -- but size and
    mtime together catch the case that matters: the file changed since we
    read it."""
    try:
        st = path.stat()
    except OSError:
        return ""
    return hashlib.sha1(f"{st.st_size}:{st.st_mtime_ns}".encode()).hexdigest()[:16]


class LocalStore:
    """A folder on disk, including everything beneath it."""

    def __init__(self, root: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self._observer = None

    @property
    def root_label(self) -> str:
        return str(self.root)

    # -- enumeration ----------------------------------------------------

    def list_specs(self) -> Iterable[StoredItem]:
        for path in self._walk():
            yield self._item_for(path)

    def _walk(self) -> Iterator[Path]:
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root)
            # Skip .cobalt/ and any other dotfolder, the same way Obsidian
            # ignores its own config directory.
            if any(part.startswith(".") for part in relative.parts):
                continue
            if is_hidden_or_lock_filename(path.name) or not is_spec_filename(path.name):
                continue
            yield path

    def _item_for(self, path: Path) -> StoredItem:
        relative = path.relative_to(self.root)
        folder = str(relative.parent) if str(relative.parent) != "." else ""
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return StoredItem(
            key=str(path),
            name=path.name,
            folder=folder.replace(os.sep, "/"),
            etag=_local_etag(path),
            size=size,
        )

    def item(self, key: str) -> StoredItem | None:
        path = Path(key)
        return self._item_for(path) if path.exists() else None

    # -- content --------------------------------------------------------

    def read(self, key: str) -> tuple[bytes, str]:
        path = Path(key)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise StoreError(f"Could not read {key}: {exc}") from exc
        return data, _local_etag(path)

    def read_many(self, keys: list[str]) -> Iterator[tuple[str, bytes | None, str]]:
        # Local reads are fast and the parsing that follows is the real cost,
        # so this stays sequential; the caller parallelises the parsing.
        for key in keys:
            try:
                data, etag = self.read(key)
            except StoreError:
                yield key, None, ""
            else:
                yield key, data, etag

    def write(self, key: str, data: bytes, etag: str | None = None) -> str:
        path = Path(key)
        if etag and path.exists() and _local_etag(path) != etag:
            raise ConflictError(key)
        # Write to a temp file in the same directory and replace, so a crash
        # mid-write can't truncate a spec that Word may also have open.
        tmp = path.with_name(f".{path.name}.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise StoreError(f"Could not write {key}: {exc}") from exc
        return _local_etag(path)

    def create(self, folder: str, name: str, data: bytes) -> StoredItem:
        directory = self.root / folder if folder else self.root
        target = directory / name
        if target.exists():
            raise StoreError(f"Destination already exists: {target}")
        directory.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return self._item_for(target)

    def delete(self, key: str) -> None:
        Path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return Path(key).exists()

    def sibling_key(self, key: str, suffix: str) -> str:
        """Same document, different extension -- how a converted .doc finds
        the .docx that replaces it."""
        return str(Path(key).with_suffix(suffix))

    # -- change notification --------------------------------------------

    def watch(self, on_change: Callable[[list[str]], None]) -> Callable[[], None]:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        debounce = _Debouncer(on_change)

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event) -> None:  # noqa: ANN001
                if event.is_directory:
                    return
                for attr in ("src_path", "dest_path"):
                    path = getattr(event, attr, None)
                    if not path:
                        continue
                    name = os.path.basename(path)
                    if is_hidden_or_lock_filename(name) or not is_spec_filename(name):
                        continue
                    debounce.add(path)

        observer = Observer()
        observer.schedule(Handler(), str(self.root), recursive=True)
        observer.start()
        self._observer = observer

        def stop() -> None:
            debounce.stop()
            observer.stop()
            observer.join(timeout=2)
            self._observer = None

        return stop


class _Debouncer:
    """Collect a burst of change notifications into one callback.

    Saving a .docx in Word produces a flurry of events for a single logical
    edit, and dropping a migration into a folder produces thousands. Both
    should result in one reindex pass, not one per event.
    """

    def __init__(self, on_change: Callable[[list[str]], None], delay: float = 0.4) -> None:
        self._on_change = on_change
        self._delay = delay
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def add(self, key: str) -> None:
        with self._lock:
            self._pending.add(key)
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=0.2)
            if self._stop.is_set():
                return
            if not self._wake.is_set():
                continue
            # Let the burst finish arriving before acting on it.
            self._wake.clear()
            self._stop.wait(self._delay)
            with self._lock:
                batch = sorted(self._pending)
                self._pending.clear()
            if batch:
                try:
                    self._on_change(batch)
                except Exception:  # noqa: BLE001 - a listener must not kill the watcher
                    pass

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=2)


def concurrent_read_many(
    read_one: Callable[[str], tuple[bytes, str]],
    keys: list[str],
    workers: int,
) -> Iterator[tuple[str, bytes | None, str]]:
    """Fetch many documents at once, yielding them as they arrive.

    Shared by any store whose reads are network round trips: there the
    bottleneck is latency, not CPU, so overlapping the fetches is the whole
    game. Results stream out as they complete rather than being collected,
    so parsing can start on the first document instead of the last.
    """
    results: queue.Queue = queue.Queue()

    def fetch(key: str) -> None:
        try:
            data, etag = read_one(key)
            results.put((key, data, etag))
        except Exception:  # noqa: BLE001 - reported as unreadable, not fatal
            results.put((key, None, ""))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for key in keys:
            pool.submit(fetch, key)
        for _ in range(len(keys)):
            yield results.get()
