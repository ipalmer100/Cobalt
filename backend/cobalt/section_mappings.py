"""Human decisions about where an unrecognized table belongs.

The parser classifies a table's heading onto one of the 11 canonical
sections only when it can do so confidently -- an exact name, a known
alias, or a qualified variant of one ("Process Routing - Duplex"). Anything
else is left unclassified and shows up in the exception queue rather than
being guessed into a section, because filing a Press Specification table
under Process Routing would quietly corrupt what people read off the grid.

Decisions made in that queue live here: a small JSON file inside the vault
(next to the audit log, same convention as Obsidian's ``.obsidian/``) so
they travel with the folder and apply to everyone who opens it. They are
keyed by normalized heading text, so allocating "Press Specification" once
resolves it for every spec in the archive that uses that heading.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone

MAPPINGS_DIRNAME = ".cobalt"
MAPPINGS_FILENAME = "section_mappings.json"

# The app was called SpecWrite before it was called Cobalt, and its state
# lives beside the specs, in the customer's own folder. A vault that has
# already been triaged holds real decisions a person made table by table;
# renaming the folder we look in would silently throw all of them away and
# re-raise every exception. So a legacy directory is adopted where one
# exists, and only new vaults get the new name.
LEGACY_DIRNAME = ".specwrite"


def state_dir(vault_root: str) -> str:
    """The state folder to use for this vault: the current name, unless a
    pre-rename one is already there."""
    current = os.path.join(vault_root, MAPPINGS_DIRNAME)
    if os.path.isdir(current):
        return current
    legacy = os.path.join(vault_root, LEGACY_DIRNAME)
    if os.path.isdir(legacy):
        return legacy
    return current


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def mappings_path(vault_root: str) -> str:
    return os.path.join(state_dir(vault_root), MAPPINGS_FILENAME)


@dataclass
class Mapping:
    heading: str  # as originally written, for display
    section: str  # a canonical section name, or docx_sections.IGNORE
    who: str
    at: str

    def to_dict(self) -> dict:
        return {"heading": self.heading, "section": self.section, "who": self.who, "at": self.at}


def load_mappings(vault_root: str) -> dict[str, Mapping]:
    path = mappings_path(vault_root)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    out: dict[str, Mapping] = {}
    for key, raw in (payload.get("mappings") or {}).items():
        if isinstance(raw, dict) and raw.get("section"):
            out[key] = Mapping(
                heading=raw.get("heading", key),
                section=raw["section"],
                who=raw.get("who", ""),
                at=raw.get("at", ""),
            )
    return out


def overrides_for_parser(mappings: dict[str, Mapping]) -> dict[str, str]:
    """The shape ``parse_document`` wants: normalized heading -> section."""
    return {key: mapping.section for key, mapping in mappings.items()}


def save_mapping(vault_root: str, heading: str, section: str, who: str = "") -> Mapping:
    """Record (or overwrite) one heading's allocation. Written atomically so
    a crash mid-write can't leave the vault with a truncated decision file."""
    mappings = load_mappings(vault_root)
    key = _normalize(heading)
    mapping = Mapping(
        heading=heading.strip(),
        section=section,
        who=who,
        at=datetime.now(timezone.utc).isoformat(),
    )
    mappings[key] = mapping
    _write(vault_root, mappings)
    return mapping


def delete_mapping(vault_root: str, heading: str) -> bool:
    """Undo a decision, returning the heading to the exception queue."""
    mappings = load_mappings(vault_root)
    key = _normalize(heading)
    if key not in mappings:
        return False
    del mappings[key]
    _write(vault_root, mappings)
    return True


def _write(vault_root: str, mappings: dict[str, Mapping]) -> None:
    # Resolved once, and the same folder the final path uses: creating the
    # directory first and asking again would flip state_dir's answer from
    # the adopted legacy folder to the newly created one, leaving the temp
    # file and its target in different directories.
    directory = state_dir(vault_root)
    os.makedirs(directory, exist_ok=True)
    payload = {"version": 1, "mappings": {k: m.to_dict() for k, m in mappings.items()}}
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, prefix=".mappings-", suffix=".tmp", delete=False
    )
    try:
        json.dump(payload, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(handle.name, os.path.join(directory, MAPPINGS_FILENAME))
    except BaseException:
        handle.close()
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
