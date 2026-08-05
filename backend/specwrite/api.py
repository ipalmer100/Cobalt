"""HTTP + WebSocket API over a single open vault.

One vault open at a time, matching the desktop-app model this is meant to
emulate (Obsidian, one window, one folder). The WebSocket pushes a
notification every time any file changes — written by this app or edited
externally in Word — so every open browser tab reflects it immediately,
the same "instant" feel as Obsidian's live reload.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .doc_conversion import ConversionError, convert_doc_to_docx
from .creation import CreationError, create_blank_spec, duplicate_spec
from .docx_sections import PRODUCT_DESCRIPTION, ALL_SECTIONS
from .docx_writer import append_row, apply_revision, write_cell, write_field_value
from .vault import Vault
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


app = FastAPI(title="SpecWrite", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class WriteFieldRequest(BaseModel):
    path: str
    section: str
    label: str
    value: str


class AppendRowRequest(BaseModel):
    path: str
    section: str
    values: list[str]


class ReviseRequest(BaseModel):
    path: str
    who: str
    revision_text: str


class ConvertDocRequest(BaseModel):
    path: str


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
def list_vault() -> dict:
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
    return {"root": vault.root, "entries": entries}


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
def get_view(section: str) -> dict:
    if section not in ALL_SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    rows = build_view(_vault().entries(), section)
    return {
        "section": section,
        "rows": rows,
        "editable": is_view_editable(section),
        "readonly_columns": readonly_columns_for(section),
    }


@app.put("/spec/cell")
def put_cell(req: WriteCellRequest) -> dict:
    vault = _vault()
    _require_not_revision_locked(req.section)
    try:
        write_cell(req.path, req.section, req.row, req.col, req.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    vault.refresh(req.path)
    return {"ok": True}


@app.put("/spec/field")
def put_field(req: WriteFieldRequest) -> dict:
    vault = _vault()
    _require_not_revision_locked(req.section, req.label)
    try:
        found = write_field_value(req.path, req.section, req.label, req.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not found:
        raise HTTPException(status_code=404, detail=f"Field not found: {req.label}")
    vault.refresh(req.path)
    return {"ok": True}


@app.post("/spec/row")
def post_row(req: AppendRowRequest) -> dict:
    vault = _vault()
    _require_not_revision_locked(req.section)
    try:
        append_row(req.path, req.section, req.values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    vault.refresh(req.path)
    return {"ok": True}


@app.post("/spec/revision")
def post_revision(req: ReviseRequest) -> dict:
    vault = _vault()
    try:
        new_rev = apply_revision(req.path, req.who, req.revision_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    vault.refresh(req.path)
    return {"ok": True, "revision_number": new_rev}


@app.post("/spec/convert-doc")
def post_convert_doc(req: ConvertDocRequest) -> dict:
    """Convert a legacy .doc file to .docx via LibreOffice headless. The
    original .doc is left in place — nothing is deleted automatically."""
    vault = _vault()
    _require_within_vault(vault, req.path)
    if not req.path.lower().endswith(".doc"):
        raise HTTPException(status_code=422, detail="Not a .doc file")
    try:
        new_path = convert_doc_to_docx(req.path)
    except ConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    vault.refresh(new_path)
    entry = vault.get(new_path)
    return {
        "ok": True,
        "path": new_path,
        "spec_number": entry.spec.spec_number if entry and entry.spec else None,
    }


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
    return {"ok": True, "path": req.dest_path, "spec_number": spec.spec_number}


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
