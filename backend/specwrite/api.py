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
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .docx_sections import ALL_SECTIONS
from .docx_writer import append_row, apply_revision, write_cell, write_field_value
from .vault import Vault
from .views import READONLY_COLUMNS, VIEW_NAMES, build_view

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
    return {"views": VIEW_NAMES, "readonly_columns": READONLY_COLUMNS}


@app.get("/views/{section}")
def get_view(section: str) -> dict:
    if section not in ALL_SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section}")
    rows = build_view(_vault().entries(), section)
    return {"section": section, "rows": rows}


@app.put("/spec/cell")
def put_cell(req: WriteCellRequest) -> dict:
    vault = _vault()
    try:
        write_cell(req.path, req.section, req.row, req.col, req.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    vault.refresh(req.path)
    return {"ok": True}


@app.put("/spec/field")
def put_field(req: WriteFieldRequest) -> dict:
    vault = _vault()
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
