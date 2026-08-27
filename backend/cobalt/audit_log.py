"""The app's own change log — separate from Revision History (table 11).

Table 11 stays exactly what it's always been: a short, manually-written
audit-compliance record inside the .docx itself. This module is a second,
independent log that captures *every* write the app makes (every mass-edit
cell, every field, every row, every revision, every conversion, every new
spec) with no connection to the Word document at all — nothing here is
ever written into a .docx.

It lives inside the vault itself, at ``<vault_root>/.cobalt/audit_log.jsonl``,
the same "dotfolder colocated with the vault" convention Obsidian uses for
its own config — so the log travels with the folder (network share, backup,
zip) and is shared automatically by anyone who opens that vault, without
needing a separate database or server-side identity system.

Append-only JSON Lines: one JSON object per line, so a crash mid-write
can't corrupt earlier entries the way a single large JSON array could.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .section_mappings import state_dir

_LOG_FILENAME = "audit_log.jsonl"

_write_lock = threading.Lock()


def _log_path(vault_root: str) -> Path:
    # Shares the vault's state folder with the exception-queue decisions,
    # which keeps reading a pre-rename ".specwrite" directory where one
    # exists -- an audit trail that silently restarted at the rename would
    # be worse than useless.
    return Path(state_dir(vault_root)) / _LOG_FILENAME


def append_entry(vault_root: str, action: str, who: str, **fields: Any) -> dict:
    """Append one entry and return it (so the caller/tests can inspect
    exactly what was recorded, including the generated timestamp)."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "who": who or "",
        **fields,
    }
    path = _log_path(vault_root)
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


_TAIL_CHUNK_SIZE = 65536


def _read_tail_lines(path: Path, min_lines: int) -> list[bytes]:
    """The last `min_lines` (or more -- always whole lines) raw lines of
    `path`, in file order, read by seeking backward from the end in chunks
    rather than reading the whole file. A vault used heavily for months
    can accumulate a log hundreds of MB long; every previous "just show
    the last N entries" call still paid to read and JSON-parse all of it
    first. Confirmed empirically: 4+ seconds for the last 200 entries out
    of a 300,000-line/74MB log, before this fix."""
    with open(path, "rb") as f:
        file_size = f.seek(0, 2)
        position = file_size
        chunks: list[bytes] = []
        newline_count = 0
        while position > 0 and newline_count <= min_lines:
            read_size = min(_TAIL_CHUNK_SIZE, position)
            position -= read_size
            f.seek(position)
            chunk = f.read(read_size)
            newline_count += chunk.count(b"\n")
            chunks.append(chunk)
        return b"".join(reversed(chunks)).splitlines()


def read_entries(vault_root: str, limit: int = 200) -> list[dict]:
    """Most recent entries first. Missing log (nothing written yet) is not
    an error -- it just means an empty history."""
    path = _log_path(vault_root)
    if not path.exists():
        return []

    entries: list[dict] = []
    for raw in reversed(_read_tail_lines(path, limit)):
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # skip a corrupted line rather than fail the whole read
        if len(entries) >= limit:
            break
    return entries
