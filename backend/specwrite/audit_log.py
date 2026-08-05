"""The app's own change log — separate from Revision History (table 11).

Table 11 stays exactly what it's always been: a short, manually-written
audit-compliance record inside the .docx itself. This module is a second,
independent log that captures *every* write the app makes (every mass-edit
cell, every field, every row, every revision, every conversion, every new
spec) with no connection to the Word document at all — nothing here is
ever written into a .docx.

It lives inside the vault itself, at ``<vault_root>/.specwrite/audit_log.jsonl``,
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

_LOG_DIRNAME = ".specwrite"
_LOG_FILENAME = "audit_log.jsonl"

_write_lock = threading.Lock()


def _log_path(vault_root: str) -> Path:
    return Path(vault_root) / _LOG_DIRNAME / _LOG_FILENAME


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


def read_entries(vault_root: str, limit: int = 200) -> list[dict]:
    """Most recent entries first. Missing log (nothing written yet) is not
    an error -- it just means an empty history."""
    path = _log_path(vault_root)
    if not path.exists():
        return []
    entries: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip a corrupted line rather than fail the whole read
    entries.reverse()
    return entries[:limit]
