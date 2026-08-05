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

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .docx_sections import parse_document
from .models import Spec

VaultListener = Callable[[str], None]  # called with the changed file's path

_DEBOUNCE_SECONDS = 0.4


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
        for file_path in self._walk():
            self._index_one(file_path)

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
        name = Path(path).name
        if not Path(path).exists():
            with self._lock:
                self._entries.pop(path, None)
            return

        if path.lower().endswith(".doc"):
            entry = VaultEntry(path=path, spec=None, error="Legacy .doc format is not parsed (re-save as .docx).", supported=False)
        else:
            try:
                spec = parse_document(path)
                entry = VaultEntry(path=path, spec=spec, error=None, supported=True)
            except Exception as exc:  # noqa: BLE001 - a bad file shouldn't kill the vault
                entry = VaultEntry(path=path, spec=None, error=str(exc), supported=False)

        with self._lock:
            self._entries[path] = entry

    # -- live watching ----------------------------------------------------

    def _start_watching(self) -> None:
        handler = _Handler(self)
        observer = Observer()
        observer.schedule(handler, self.root, recursive=True)
        observer.start()
        self._observer = observer

    def _schedule_refresh(self, path: str) -> None:
        """Debounce bursts of filesystem events (Word/OneDrive fire several
        modify events per save) down to a single re-parse."""
        now = time.monotonic()
        with self._debounce_lock:
            self._pending[path] = now

        def _fire():
            time.sleep(_DEBOUNCE_SECONDS)
            with self._debounce_lock:
                if self._pending.get(path) != now:
                    return  # a newer event superseded this one
                del self._pending[path]
            self.refresh(path)

        threading.Thread(target=_fire, daemon=True).start()


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
