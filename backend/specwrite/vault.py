"""The vault: a folder of .docx specs, indexed and watched live — the same
"point the app at a folder, everything in it is instantly there and stays
in sync" model Obsidian uses for a folder of markdown files.

Differences from Obsidian worth being explicit about, since this isn't a
1:1 port:
- Obsidian's files are its own content (markdown); ours are the .docx
  files themselves, so a "note" here is a parsed Spec, not raw text.
- Obsidian treats every file as trusted; we can't parse .doc (legacy
  binary Word format) with python-docx, so those show up as unparsed
  entries rather than crashing the index — same idea as Obsidian showing
  an unsupported attachment type without indexing its content.
- Word's lock files (``~$name.docx``) are filtered out, same category of
  noise as Obsidian ignoring its own ``.obsidian`` config folder.
"""

from __future__ import annotations

import gc
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .docx_sections import parse_document
from .models import Spec

VaultListener = Callable[[str], None]  # called with the changed file's path

_DEBOUNCE_SECONDS = 0.4
_REFRESH_WORKER_COUNT = 4


@dataclass
class VaultEntry:
    path: str
    spec: Spec | None
    error: str | None
    supported: bool


def _is_hidden_or_lock_file(name: str) -> bool:
    return name.startswith("~$") or name.startswith(".")


def _is_spec_file(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(".docx") or lower.endswith(".doc")


# Module-level (not a method) so it can be pickled and sent to worker
# processes for parallel indexing -- see Vault._full_index. Also used
# directly for the single-file case (file-watcher events, our own writes),
# where spawning a whole process pool for one file would be pure overhead.
def _build_entry(path: str) -> VaultEntry:
    if path.lower().endswith(".doc"):
        return VaultEntry(path=path, spec=None, error="Legacy .doc format is not parsed (re-save as .docx).", supported=False)
    try:
        spec = parse_document(path)
        return VaultEntry(path=path, spec=spec, error=None, supported=True)
    except Exception as exc:  # noqa: BLE001 - a bad file shouldn't kill the vault
        return VaultEntry(path=path, spec=None, error=str(exc), supported=False)


# Parsing one .docx is CPU-bound, pure-Python work that holds the GIL for
# its whole duration -- threads wouldn't overlap it at all, so a large
# vault's indexing needs real worker *processes* to actually parallelize.
# Below this many files, spinning up a pool costs more (process startup,
# pickling results back) than it would save.
_PARALLEL_INDEX_THRESHOLD = 32


class Vault:
    """Indexes a root folder of spec documents and keeps the index live."""

    def __init__(self, root: str):
        self.root = str(Path(root).resolve())
        self._entries: dict[str, VaultEntry] = {}
        self._lock = threading.Lock()
        self._listeners: list[VaultListener] = []
        self._observer: Observer | None = None
        self._pending: dict[str, float] = {}
        self._debounce_lock = threading.Lock()
        self._refresh_pool: ThreadPoolExecutor | None = None
        self._scheduler_thread: threading.Thread | None = None
        self._scheduler_stop = threading.Event()

    # -- public API ---------------------------------------------------

    def open(self) -> None:
        """Full initial index, then start watching for live changes.
        Mirrors "select a folder as your vault" in Obsidian: instant read
        of everything already there, then instant reaction to anything
        that changes afterward."""
        self._full_index()
        self._start_watching()

    def close(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
        self._scheduler_stop.set()
        if self._scheduler_thread is not None:
            self._scheduler_thread.join(timeout=2)
            self._scheduler_thread = None
        if self._refresh_pool is not None:
            self._refresh_pool.shutdown(wait=False)
            self._refresh_pool = None

    def entries(self) -> list[VaultEntry]:
        with self._lock:
            return list(self._entries.values())

    def get(self, path: str) -> VaultEntry | None:
        with self._lock:
            return self._entries.get(str(Path(path).resolve()))

    def subscribe(self, listener: VaultListener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: VaultListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def refresh(self, path: str) -> None:
        """Re-parse a single file and notify listeners. Called both by the
        file watcher (external edits) and by our own write path (so every
        view reflects a write immediately, no manual reload)."""
        resolved = str(Path(path).resolve())
        self._index_one(resolved)
        for listener in self._listeners:
            listener(resolved)

    # -- indexing -------------------------------------------------------

    def _full_index(self) -> None:
        with self._lock:
            self._entries.clear()

        paths = list(self._walk())

        if len(paths) < _PARALLEL_INDEX_THRESHOLD:
            for file_path in paths:
                self._store(_build_entry(file_path))
        else:
            self._full_index_parallel(paths)

        # A large vault's parsed Spec objects (nested tables/rows/dicts,
        # millions of tracked containers at thousands of files) sit in
        # memory for the vault's whole lifetime and essentially never
        # change shape. Python's cyclic GC doesn't know that -- every
        # collection it runs walks this entire graph looking for cycles
        # that were never going to be there, and a burst of short-lived
        # allocations (building a mass-edit view's rows is exactly this)
        # is enough to trigger one. Confirmed empirically: the first
        # request after opening a 15,000-file vault took ~3x longer than
        # every request after it, and that gap disappears with this call.
        # gc.freeze() moves everything currently tracked into a permanent
        # generation the collector skips, so only genuinely short-lived
        # request-scoped garbage gets scanned from here on.
        gc.freeze()

    def _full_index_parallel(self, paths: list[str]) -> None:
        worker_count = min(len(paths), os.cpu_count() or 4)
        # A handful of files per IPC round trip, not one, so pickling
        # results back doesn't dominate for a vault that's merely "large"
        # (a few hundred files) rather than "huge" (thousands) -- but never
        # so few workers that a couple of slow files serialize the whole
        # batch behind them.
        chunksize = max(1, min(50, len(paths) // (worker_count * 4)))
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            for entry in executor.map(_build_entry, paths, chunksize=chunksize):
                self._store(entry)

    def _store(self, entry: VaultEntry) -> None:
        with self._lock:
            self._entries[entry.path] = entry

    def _walk(self):
        root = Path(self.root)
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue  # skip .specwrite/ (audit log) and any other dotfolder
            if _is_hidden_or_lock_file(path.name):
                continue
            if not _is_spec_file(path.name):
                continue
            yield str(path)

    def _index_one(self, path: str) -> None:
        if not Path(path).exists():
            with self._lock:
                self._entries.pop(path, None)
            return
        self._store(_build_entry(path))

    # -- live watching ----------------------------------------------------

    def _start_watching(self) -> None:
        handler = _Handler(self)
        observer = Observer()
        observer.schedule(handler, self.root, recursive=True)
        observer.start()
        self._observer = observer

        self._refresh_pool = ThreadPoolExecutor(max_workers=_REFRESH_WORKER_COUNT)
        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(target=self._debounce_scheduler_loop, daemon=True)
        self._scheduler_thread.start()

    def _schedule_refresh(self, path: str) -> None:
        """Debounce bursts of filesystem events (Word/OneDrive fire several
        modify events per save) down to a single re-parse -- and, unlike a
        naive "spawn a thread that sleeps then fires" per event, bounded:
        a single scheduler thread tracks every pending path's fire time and
        a small fixed worker pool actually runs the refreshes. A one-thread-
        per-event version is fine for occasional external edits, but a bulk
        drop of thousands of files into an already-open vault (a migration,
        a network-drive resync) would otherwise spawn thousands of OS
        threads in a burst for no benefit -- they'd almost all just be
        sleeping at once."""
        with self._debounce_lock:
            self._pending[path] = time.monotonic() + _DEBOUNCE_SECONDS

    def _debounce_scheduler_loop(self) -> None:
        while not self._scheduler_stop.is_set():
            now = time.monotonic()
            due: list[str] = []
            with self._debounce_lock:
                for path, fire_at in list(self._pending.items()):
                    if now >= fire_at:
                        due.append(path)
                        del self._pending[path]
            for path in due:
                self._refresh_pool.submit(self.refresh, path)
            time.sleep(0.05)


class _Handler(FileSystemEventHandler):
    def __init__(self, vault: Vault):
        self._vault = vault

    def _maybe_handle(self, path: str) -> None:
        name = Path(path).name
        if _is_hidden_or_lock_file(name) or not _is_spec_file(name):
            return
        self._vault._schedule_refresh(path)

    def on_created(self, event):
        if not event.is_directory:
            self._maybe_handle(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._maybe_handle(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._maybe_handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._maybe_handle(event.src_path)
            self._maybe_handle(event.dest_path)
