"""HTTP + WebSocket API over a single open vault.

One vault open at a time, matching the desktop-app model this is meant to
emulate (Obsidian, one window, one folder). The WebSocket pushes a
notification every time any file changes — written by this app or edited
externally in Word — so every open browser tab reflects it immediately,
the same "instant" feel as Obsidian's live reload.
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .audit_log import append_entry, read_entries
from .creation import CreationError, create_blank_spec, duplicate_spec
from .docx_sections import ALL_SECTIONS, IGNORE, PRODUCT_DESCRIPTION
from .section_mappings import delete_mapping, load_mappings, save_mapping
from .docx_writer import (
    append_row,
    apply_revision,
    commit_with_revision,
    write_cell,
    write_edits_batch,
    write_field_value,
)
from .vault import Vault, is_spec_file
from .views import (
    REVISION_HISTORY,
    REVISION_NUMBER_FIELD,
    VIEW_NAMES,
    build_view,
    is_view_editable,
    readonly_columns_for,
)

_state: dict[str, Any] = {"vault": None, "loop": None, "sockets": []}


@asynccontextmanager
async def _lifespan(_: FastAPI):
    _state["loop"] = asyncio.get_event_loop()
    yield
    vault = _state.get("vault")
    if vault is not None:
        vault.close()


app = FastAPI(title="Cobalt", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# Mass-edit views over a large vault can be tens of MB of repetitive JSON
# (see get_view below) -- compress it. Doesn't help the same-machine dev
# setup, but matters once the frontend and backend aren't on localhost.
app.add_middleware(GZipMiddleware, minimum_size=1024)


def _vault() -> Vault:
    vault = _state["vault"]
    if vault is None:
        raise HTTPException(status_code=400, detail="No vault is open. POST /vault/open first.")
    return vault


def _require_within_vault(vault: Vault, path: str) -> None:
    """New files get written by this API (conversion, duplication, blank
    creation) — keep them inside the open vault rather than letting a
    client point the app at an arbitrary path on disk."""
    resolved = Path(path).resolve()
    root = Path(vault.root)
    if root not in resolved.parents and resolved != root:
        raise HTTPException(status_code=400, detail=f"Path must be inside the open vault ({vault.root})")


_REVISION_LOCK_MESSAGE = (
    "Revision History and Product Description's Revision # can only change together, "
    "via POST /spec/revision (the \"Add Revision\" action) — this keeps the audit trail "
    "and the spec's stated revision number from ever drifting apart."
)


def _require_not_revision_locked(section: str, label: str | None = None) -> None:
    if section == REVISION_HISTORY:
        raise HTTPException(status_code=422, detail=_REVISION_LOCK_MESSAGE)
    if section == PRODUCT_DESCRIPTION and label is not None and label.strip().rstrip(":").strip().lower() == REVISION_NUMBER_FIELD.lower():
        raise HTTPException(status_code=422, detail=_REVISION_LOCK_MESSAGE)


def _spec_number_for(vault: Vault, path: str) -> str | None:
    entry = vault.get(path)
    return entry.spec.spec_number if entry and entry.spec else None


def _pick_table(vault: Vault, path: str, section: str, table_index: int | None):
    """The specific table a write addresses. A spec can hold several tables
    for one section, so table_index (carried by every mass-edit row) decides
    which -- falling back to the first only when the caller didn't say."""
    entry = vault.get(path)
    if not entry or not entry.spec:
        return None
    tables = entry.spec.tables.get(section) or []
    if not tables:
        return None
    if table_index is not None and table_index >= 0:
        for table in tables:
            if table.table_index == table_index:
                return table
        return None
    return tables[0]


def _current_cell_value(
    vault: Vault, path: str, section: str, row: int, col: int, table_index: int | None = None
) -> str | None:
    """Best-effort lookup of a cell's value before it's overwritten, using
    the vault's already-parsed in-memory copy (no extra disk read)."""
    table = _pick_table(vault, path, section, table_index)
    if not table or row >= len(table.rows) or col >= len(table.rows[row]):
        return None
    return table.rows[row][col]


def _current_field_value(
    vault: Vault, path: str, section: str, label: str, table_index: int | None = None
) -> str | None:
    table = _pick_table(vault, path, section, table_index)
    if not table:
        return None
    target = label.strip().rstrip(":").strip().lower()
    for key, value in table.fields().items():
        if key.strip().rstrip(":").strip().lower() == target:
            return value
    return None


def _broadcast(path: str) -> None:
    loop = _state["loop"]
    if loop is None:
        return
    for ws in list(_state["sockets"]):
        asyncio.run_coroutine_threadsafe(_safe_send(ws, path), loop)


async def _safe_send(ws: WebSocket, path: str) -> None:
    try:
        await ws.send_json({"type": "changed", "path": path})
    except Exception:  # noqa: BLE001 - socket may already be closed
        pass


class OpenVaultRequest(BaseModel):
    root: str


class WriteCellRequest(BaseModel):
    path: str
    section: str
    row: int
    col: int
    value: str
    who: str = ""
    table_index: int | None = None


class WriteFieldRequest(BaseModel):
    path: str
    section: str
    label: str
    value: str
    who: str = ""
    table_index: int | None = None


class AppendRowRequest(BaseModel):
    path: str
    section: str
    values: list[str]
    who: str = ""
    table_index: int | None = None


class BatchEditItem(BaseModel):
    path: str
    section: str
    kind: str  # "record" or "field"
    row: int | None = None
    col: int | None = None
    label: str | None = None
    value: str
    table_index: int | None = None


class WriteCellsBatchRequest(BaseModel):
    edits: list[BatchEditItem]
    who: str = ""


class ReviseRequest(BaseModel):
    path: str
    who: str
    revision_text: str


class CommitRequest(BaseModel):
    """A batch of edits plus the revision statement that accounts for them.

    One unit of work: the specs touched come out holding both, or neither.
    """

    edits: list[BatchEditItem]
    who: str
    revision_text: str


class DuplicateSpecRequest(BaseModel):
    source_path: str
    dest_path: str
    spec_number: str
    customer: str
    who: str


class CreateBlankSpecRequest(BaseModel):
    dest_path: str
    spec_number: str
    customer: str
    who: str


def _drive_roots() -> list[dict]:
    """Windows drive letters, so the picker has somewhere to start. A
    SharePoint library synced into File Explorer shows up either as a mapped
    drive or under the user's profile, so both are offered."""
    roots: list[dict] = []
    if sys.platform == "win32":
        import string

        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if Path(drive).exists():
                roots.append({"name": drive, "path": drive})
    else:
        roots.append({"name": "/", "path": "/"})
    home = Path.home()
    if home.exists():
        roots.append({"name": f"Home ({home.name or home})", "path": str(home)})
    return roots


def _default_browse_start() -> Path | None:
    """Where the folder picker opens when nothing has been chosen yet.

    The Desktop, because that is the landmark people navigate from — and on
    a OneDrive-backed profile the real Desktop lives under the OneDrive
    folder, not directly under the home directory, so both are checked.
    Returns None when there's no Desktop to be found, leaving the caller to
    fall back to the drive list.
    """
    home = Path.home()
    candidates = [home / "Desktop"]
    try:
        candidates.extend(sorted(home.glob("OneDrive*/Desktop")))
    except OSError:
        pass
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def _count_specs_directly_in(directory: Path) -> int:
    """Spec files sitting in this folder itself (not its subfolders) — enough
    of a hint that you're in the right place, without walking the tree."""
    count = 0
    try:
        with os.scandir(directory) as it:
            for item in it:
                if item.is_file() and is_spec_file(item.name):
                    count += 1
    except OSError:
        return 0
    return count


@app.get("/browse")
def browse_folders(path: str | None = None) -> dict:
    """List subfolders so the UI can offer a folder picker.

    The app opens in the user's default browser, which by design cannot see
    real filesystem paths (`webkitdirectory` and `showDirectoryPicker` both
    withhold them) — and the backend needs a real path to open a vault. So
    the browsing happens here, on the machine that actually has the files.
    """
    if not path:
        # Open on the Desktop rather than a bare list of drive letters:
        # a synced SharePoint library and most working folders are a step
        # or two from there, and "C:\" with 40 system folders under it is
        # where people get lost. Falls back to the drive list if there is
        # no Desktop (renamed, redirected, or a non-Windows machine).
        desktop = _default_browse_start()
        if desktop is not None:
            path = str(desktop)
        else:
            return {"path": None, "parent": None, "entries": _drive_roots(), "spec_count": 0}

    try:
        target = Path(path).expanduser().resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Bad path: {exc}") from exc
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Not a folder: {target}")

    entries: list[dict] = []
    try:
        with os.scandir(target) as it:
            for item in it:
                if not item.is_dir(follow_symlinks=False) or item.name.startswith("."):
                    continue
                entries.append({"name": item.name, "path": item.path})
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"Can't read that folder: {exc}") from exc
    entries.sort(key=lambda e: e["name"].lower())

    parent = str(target.parent) if target.parent != target else None
    return {
        "path": str(target),
        "parent": parent,
        "entries": entries,
        "spec_count": _count_specs_directly_in(target),
    }


@app.post("/vault/open")
def open_vault(req: OpenVaultRequest) -> dict:
    old = _state["vault"]
    if old is not None:
        old.close()

    vault = Vault(req.root)
    vault.subscribe(_broadcast)
    vault.open()
    _state["vault"] = vault
    return {"root": vault.root, "file_count": len(vault.entries())}


@app.get("/vault")
def list_vault() -> JSONResponse:
    vault = _vault()
    entries = []
    for e in vault.entries():
        entries.append(
            {
                "path": e.path,
                "supported": e.supported,
                "error": e.error,
                "spec_number": e.spec.spec_number if e.spec else None,
                "customer": e.spec.customer if e.spec else None,
                "revision_number": e.spec.revision_number if e.spec else None,
                "warnings": e.spec.warnings if e.spec else [],
            }
        )
    # Returned as a raw JSONResponse rather than a plain dict: at thousands
    # of vault entries, FastAPI's default response path would otherwise run
    # every value through jsonable_encoder's recursive isinstance checks even
    # though this is already all plain str/bool/list -- measurably slower
    # for no benefit at this size (see get_view below for the same fix on
    # the much larger mass-edit view payload, where it matters even more).
    return JSONResponse({"root": vault.root, "entries": entries})


@app.get("/spec")
def get_spec(path: str) -> dict:
    entry = _vault().get(path)
    if entry is None:
        raise HTTPException(status_code=404, detail="File not in vault")
    if entry.spec is None:
        raise HTTPException(status_code=422, detail=entry.error or "Unparsed file")
    return entry.spec.to_dict()


@app.get("/views")
def list_views() -> dict:
    return {
        "views": VIEW_NAMES,
        "views_meta": {
            name: {"editable": is_view_editable(name), "readonly_columns": readonly_columns_for(name)}
            for name in VIEW_NAMES
        },
    }


@app.get("/views/{section}")
def get_view(section: str) -> JSONResponse:
    if section not in ALL_SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    rows = build_view(_vault().entries(), section)
    # A raw JSONResponse, not a plain dict: this can be tens of thousands of
    # rows at a large vault (e.g. Bill of Materials unions Primary +
    # Secondary across every spec), and FastAPI's default response path
    # would run jsonable_encoder recursively over every cell even though
    # build_view() already returns plain strings -- confirmed empirically
    # to matter: ~7.6s to build+serialize a 15,000-file vault's Bill of
    # Materials view before this fix.
    return JSONResponse(
        {
            "section": section,
            "rows": rows,
            "editable": is_view_editable(section),
            "readonly_columns": readonly_columns_for(section),
            # So the grid can show File Path relative to the vault, which is
            # what tells two same-named specs in different customer folders
            # apart. The stored value stays absolute -- it's the write key.
            "root": _vault().root,
        }
    )


@app.put("/spec/cell")
def put_cell(req: WriteCellRequest) -> dict:
    vault = _vault()
    _require_not_revision_locked(req.section)
    old_value = _current_cell_value(vault, req.path, req.section, req.row, req.col, req.table_index)
    try:
        write_cell(req.path, req.section, req.row, req.col, req.value, req.table_index)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    vault.refresh(req.path)
    append_entry(
        vault.root,
        "write_cell",
        req.who,
        file_path=req.path,
        spec_number=_spec_number_for(vault, req.path),
        section=req.section,
        row=req.row,
        col=req.col,
        old_value=old_value,
        new_value=req.value,
    )
    return {"ok": True}


@app.put("/spec/field")
def put_field(req: WriteFieldRequest) -> dict:
    vault = _vault()
    _require_not_revision_locked(req.section, req.label)
    old_value = _current_field_value(vault, req.path, req.section, req.label, req.table_index)
    try:
        found = write_field_value(req.path, req.section, req.label, req.value, req.table_index)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not found:
        raise HTTPException(status_code=404, detail=f"Field not found: {req.label}")
    vault.refresh(req.path)
    append_entry(
        vault.root,
        "write_field",
        req.who,
        file_path=req.path,
        spec_number=_spec_number_for(vault, req.path),
        section=req.section,
        label=req.label,
        old_value=old_value,
        new_value=req.value,
    )
    return {"ok": True}


@app.post("/spec/row")
def post_row(req: AppendRowRequest) -> dict:
    vault = _vault()
    _require_not_revision_locked(req.section)
    try:
        append_row(req.path, req.section, req.values, req.table_index)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    vault.refresh(req.path)
    append_entry(
        vault.root,
        "append_row",
        req.who,
        file_path=req.path,
        spec_number=_spec_number_for(vault, req.path),
        section=req.section,
        values=req.values,
    )
    return {"ok": True}


@app.put("/spec/cells/batch")
def put_cells_batch(req: WriteCellsBatchRequest) -> dict:
    """Apply many edits (the fill-handle drag's write path) in one request.
    All-or-nothing: if any edit would touch the revision lock, the whole
    batch is rejected before anything is written. Grouped internally so
    each file is opened and saved once, not once per cell."""
    vault = _vault()
    if not req.edits:
        return {"ok": True, "count": 0}

    for edit in req.edits:
        _require_not_revision_locked(edit.section, edit.label)

    old_values: dict[int, str | None] = {}
    for i, edit in enumerate(req.edits):
        if edit.kind == "record":
            old_values[i] = _current_cell_value(
                vault, edit.path, edit.section, edit.row, edit.col, edit.table_index
            )
        else:
            old_values[i] = _current_field_value(
                vault, edit.path, edit.section, edit.label, edit.table_index
            )

    try:
        write_edits_batch([e.model_dump() for e in req.edits])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    touched_paths = sorted({e.path for e in req.edits})
    for path in touched_paths:
        vault.refresh(path)

    by_path: dict[str, list[dict]] = {}
    for i, edit in enumerate(req.edits):
        by_path.setdefault(edit.path, []).append(
            {
                "section": edit.section,
                "kind": edit.kind,
                "row": edit.row,
                "col": edit.col,
                "label": edit.label,
                "old_value": old_values[i],
                "new_value": edit.value,
            }
        )
    for path, path_edits in by_path.items():
        append_entry(
            vault.root,
            "fill_column",
            req.who,
            file_path=path,
            spec_number=_spec_number_for(vault, path),
            section=path_edits[0]["section"],
            edits=path_edits,
        )

    return {"ok": True, "count": len(req.edits)}


@app.post("/spec/revision")
def post_revision(req: ReviseRequest) -> dict:
    vault = _vault()
    try:
        new_rev = apply_revision(req.path, req.who, req.revision_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    vault.refresh(req.path)
    append_entry(
        vault.root,
        "apply_revision",
        req.who,
        file_path=req.path,
        spec_number=_spec_number_for(vault, req.path),
        revision_number=new_rev,
        revision_text=req.revision_text,
    )
    return {"ok": True, "revision_number": new_rev}


@app.post("/spec/commit")
def post_commit(req: CommitRequest) -> dict:
    """Write a batch of edits together with the revision describing them.

    The editing surfaces buffer changes in the browser and send them here in
    one call, rather than saving each cell as it is typed. Revisions are
    manual but regulatorily required, so a spec holding edited values with
    no Revision History row to account for them is a defect, not a
    transient state -- and an interrupted save must leave the documents
    untouched rather than half-updated.
    """
    vault = _vault()
    if not req.edits:
        raise HTTPException(status_code=422, detail="Nothing to save.")
    if not req.revision_text.strip():
        raise HTTPException(status_code=422, detail="A revision description is required.")
    if not req.who.strip():
        raise HTTPException(status_code=422, detail="Your name is required to record a revision.")

    # Same locks the single-cell endpoints enforce: the revision number and
    # the Revision History table only ever move together, through this
    # commit's own revision step, never as ordinary edited cells.
    for edit in req.edits:
        _require_within_vault(vault, edit.path)
        _require_not_revision_locked(edit.section, edit.label)

    edits_by_path: dict[str, list[dict]] = {}
    for edit in req.edits:
        edits_by_path.setdefault(edit.path, []).append(edit.model_dump())

    # Captured before the write so the audit log can show what each cell
    # changed from, not just what it changed to.
    old_values: dict[int, str | None] = {}
    for i, edit in enumerate(req.edits):
        if edit.kind == "record":
            old_values[i] = _current_cell_value(vault, edit.path, edit.section, edit.row, edit.col, edit.table_index)
        else:
            old_values[i] = _current_field_value(vault, edit.path, edit.section, edit.label, edit.table_index)

    try:
        new_revisions = commit_with_revision(edits_by_path, req.who, req.revision_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    for path in edits_by_path:
        vault.refresh(path)

    per_path: dict[str, list[dict]] = {}
    for i, edit in enumerate(req.edits):
        per_path.setdefault(edit.path, []).append(
            {
                "section": edit.section,
                "kind": edit.kind,
                "row": edit.row,
                "col": edit.col,
                "label": edit.label,
                "old_value": old_values[i],
                "new_value": edit.value,
            }
        )

    committed = []
    for path, path_edits in per_path.items():
        append_entry(
            vault.root,
            "commit_revision",
            req.who,
            file_path=path,
            spec_number=_spec_number_for(vault, path),
            revision_number=new_revisions.get(path),
            revision_text=req.revision_text,
            edits=path_edits,
        )
        committed.append(
            {
                "path": path,
                "spec_number": _spec_number_for(vault, path),
                "revision_number": new_revisions.get(path),
                "edit_count": len(path_edits),
            }
        )

    return {"ok": True, "committed": committed, "spec_count": len(committed)}


@app.post("/spec/duplicate")
def post_duplicate_spec(req: DuplicateSpecRequest) -> dict:
    vault = _vault()
    _require_within_vault(vault, req.source_path)
    _require_within_vault(vault, req.dest_path)
    try:
        spec = duplicate_spec(req.source_path, req.dest_path, req.spec_number, req.customer, req.who)
    except CreationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    vault.refresh(req.dest_path)
    append_entry(
        vault.root,
        "duplicate_spec",
        req.who,
        source_path=req.source_path,
        dest_path=req.dest_path,
        spec_number=spec.spec_number,
        customer=req.customer,
    )
    return {"ok": True, "path": req.dest_path, "spec_number": spec.spec_number}


@app.post("/spec/create-blank")
def post_create_blank_spec(req: CreateBlankSpecRequest) -> dict:
    vault = _vault()
    _require_within_vault(vault, req.dest_path)
    try:
        spec = create_blank_spec(req.dest_path, req.spec_number, req.customer, req.who)
    except CreationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    vault.refresh(req.dest_path)
    append_entry(
        vault.root,
        "create_blank_spec",
        req.who,
        dest_path=req.dest_path,
        spec_number=spec.spec_number,
        customer=req.customer,
    )
    return {"ok": True, "path": req.dest_path, "spec_number": spec.spec_number}


@app.get("/audit-log")
def get_audit_log(limit: int = 200) -> dict:
    vault = _vault()
    return {"entries": read_entries(vault.root, limit=limit)}


@app.get("/exceptions")
def get_exceptions() -> dict:
    """Tables the parser could not confidently file under one of the 11
    sections, grouped by heading, plus the decisions already made. This is
    the queue a human works through — the app deliberately does not guess."""
    vault = _vault()
    mappings = load_mappings(vault.root)
    return {
        "pending": vault.unclassified(),
        "resolved": [m.to_dict() for m in mappings.values()],
        "sections": ALL_SECTIONS,
        "ignore_value": IGNORE,
    }


class AssignExceptionRequest(BaseModel):
    heading: str
    section: str  # a canonical section name, or IGNORE
    who: str = ""


@app.post("/exceptions/assign")
def post_assign_exception(req: AssignExceptionRequest) -> dict:
    """Allocate every table under this heading to a section (or IGNORE it).
    The decision is saved into the vault and applied immediately, so the
    rows appear in that section's mass-edit view without a reopen."""
    vault = _vault()
    if req.section != IGNORE and req.section not in ALL_SECTIONS:
        raise HTTPException(status_code=422, detail=f"Unknown section: {req.section}")
    save_mapping(vault.root, req.heading, req.section, req.who)
    vault.reload_mappings()
    append_entry(
        vault.root,
        "assign_section",
        req.who,
        heading=req.heading,
        section=req.section,
    )
    _broadcast(vault.root)
    return {"ok": True, "heading": req.heading, "section": req.section}


class UnassignExceptionRequest(BaseModel):
    heading: str
    who: str = ""


@app.post("/exceptions/unassign")
def post_unassign_exception(req: UnassignExceptionRequest) -> dict:
    """Undo an allocation, returning the heading to the pending queue."""
    vault = _vault()
    removed = delete_mapping(vault.root, req.heading)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No decision recorded for: {req.heading}")
    vault.reload_mappings()
    append_entry(vault.root, "unassign_section", req.who, heading=req.heading)
    _broadcast(vault.root)
    return {"ok": True, "heading": req.heading}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _state["sockets"].append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _state["sockets"]:
            _state["sockets"].remove(websocket)


def _frontend_dist_dir() -> Path | None:
    """Where the built frontend (`npm run build`'s `dist/`) lives, so this
    same process can serve it alongside the API -- the single-origin,
    single-port setup the packaged desktop app depends on (see desktop.py).
    Checked in two places: PyInstaller's extracted bundle dir when frozen,
    otherwise the sibling `frontend/dist` in the source tree. Returns None
    (and the route below is never mounted) if neither exists, so running
    the API alone against a separate dev frontend server is unaffected."""
    frozen_base = getattr(sys, "_MEIPASS", None)
    candidate = (
        Path(frozen_base) / "frontend_dist"
        if frozen_base
        else Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    )
    return candidate if candidate.is_dir() else None


_dist_dir = _frontend_dist_dir()
if _dist_dir is not None:
    app.mount("/", StaticFiles(directory=_dist_dir, html=True), name="frontend")
