# SpecWrite

"Obsidian for specs" — point it at a folder of flexible-packaging customer
spec `.docx` files and get a live, instantly-synced view of all of them,
plus a tabular mass-edit grid per section (Bill of Materials, Slitting
Information, etc.) instead of opening one Word document at a time.

## How it works

- **`backend/specwrite/docx_sections.py`** — reads a spec: finds each of
  the 11 sections by locating its title paragraph and taking the table
  that follows it (Product Description is the exception — it lives in
  the page header, with a fallback to the first body table for older
  specs that never got one).
- **`backend/specwrite/docx_writer.py`** — writes a spec by cell address
  (row/col or label), preserving the target cell's existing formatting,
  and a composite `apply_revision()` that bumps the header's Revision #
  and appends a Revision History row in one call.
- **`backend/specwrite/vault.py`** — indexes a folder of specs and
  watches it for changes (`watchdog`), the same "select a folder, it's
  instantly live" model as Obsidian's vault.
- **`backend/specwrite/views.py`** — flattens every spec's copy of a
  section into `Spec Number | Customer | <columns> | File Path` rows —
  the shape of the sample Bill of Materials workbook, generalized to all
  11 sections. Bill of Materials specifically unions Primary + Secondary
  Approved Materials into one grid with a Material Type column, matching
  the existing VBA extractor's output.
- **`backend/specwrite/api.py`** — FastAPI HTTP + WebSocket layer over
  the above. One vault open at a time; the WebSocket pushes a "changed"
  event on every write (ours or an external Word edit) so open views
  refresh immediately.
- **`frontend/`** — a small React/Vite shell: sidebar file list, a
  read-only Spec Detail view, and the tabular Mass Edit grid.

## Running it

Backend:

```
cd backend
pip install -e .
python -m uvicorn specwrite.api:app --reload
```

Frontend (separate terminal):

```
cd frontend
npm install
npm run dev
```

Open the printed Vite URL, enter the absolute path to a folder of spec
`.docx` files, and click "Open Vault".

## Testing

```
cd backend
python -m pytest
```

Tests run entirely against a synthetic spec generated at test time
(`backend/tests/fixtures/builder.py`) — no real customer files are ever
checked into the repo (see `.gitignore`). To validate against real specs
by hand:

```
cd backend
python scripts/validate_real_specs.py /path/to/spec1.docx /path/to/spec2.docx
```

## Known limitations (v1 scaffold)

- One row in Slitting Information sometimes stacks two labels
  (`Core Tags:` / `Splice Code:`) inside a single physical cell; the
  parser currently reads that as one combined field instead of two.
- Legacy `.doc` files (pre-2007 binary format) are detected and flagged
  as unsupported rather than parsed — they'd need a conversion step.
- Only one vault can be open at a time (matches the single-folder,
  single-window model this is meant to emulate, but is a real constraint
  if multiple admins need concurrent access).
- No conflict handling if two people edit the same file at once, or if a
  file changes on disk mid-write.
