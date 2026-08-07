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
  and appends a Revision History row in one call. This is the *only* path
  that's allowed to touch either of those — see "Revision History" below.
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
  refresh immediately. (Needs `uvicorn[standard]` — plain `uvicorn` has no
  WebSocket implementation and silently 404s `/ws`; see pyproject.toml.)
- **`backend/specwrite/doc_conversion.py`** — converts legacy `.doc`
  files to `.docx` via LibreOffice headless (`soffice --headless
  --convert-to docx`). The original `.doc` is never touched/deleted.
- **`backend/specwrite/creation.py`** — creates a new spec, either by
  duplicating an existing one (data tables carry over as a starting
  point; Spec #, Customer, and Revision History reset) or from the
  bundled blank template (`specwrite/templates/blank_spec_template.docx`
  — a synthetic placeholder with no real branding; swap in a real blank
  Toppan master template by regenerating via
  `scripts/build_blank_template.py` or replacing the file directly).
- **`backend/specwrite/audit_log.py`** — a second, independent change log,
  entirely separate from Revision History. Every write the app makes
  (mass-edit cell/field, row add, revision, conversion, new spec) is
  appended as one JSON line to `<vault_root>/.specwrite/audit_log.jsonl`
  — never into a `.docx`. Lives inside the vault (Obsidian's `.obsidian/`
  convention) so it travels with the folder and is shared by anyone who
  opens it. `GET /audit-log` reads it back; the frontend's "Audit Log"
  tab shows it as a table (time, who, spec, what changed).
- **`frontend/`** — a small React/Vite shell: sidebar file list with a
  "New Spec" action and a convert-to-.docx link on legacy `.doc` entries,
  a read-only Spec Detail view, the tabular Mass Edit grid, and the
  Audit Log tab. A "Your name" field in the top bar (persisted in
  `localStorage`) is attached to every write for the audit log's "who" —
  there's no login system, so this is a per-browser display name, not
  authentication.

### Revision History is deliberately manual, and deliberately locked

By design, editing data (Mass Edit grid, any field) never touches
Revision History or bumps Revision # — logging a revision is a separate,
manual action ("Add Revision" on a spec's detail view, or `POST
/spec/revision`), matching how the org's compliance process already
works, and keeping table 11 free of the "changed X to Y" busywork a fully
automatic log would generate on every keystroke.

What *is* enforced is that Product Description's Revision # and Revision
History's last row can never drift apart: both endpoints for changing
either one directly are rejected server-side —

- `PUT /spec/field` refuses to set Product Description's `Revision #`
  (every other field on that view stays editable — Spec #, Customer,
  Item, Structure Description, Structure Code, Date of Issue).
- `PUT /spec/cell` and `POST /spec/row` refuse any write to the
  `Revision History` section at all.

Both come back as a 422 with a message pointing at `POST
/spec/revision`, and the Mass Edit grid greys out accordingly (the
dropdown even tags it "Revision History (read-only)"). The only code
path that can ever change either value is `apply_revision()`, which
changes them together, atomically — see `specwrite/views.py`
(`is_view_editable`, `readonly_columns_for`) and the guard in
`specwrite/api.py` (`_require_not_revision_locked`).

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

### Packaged desktop app (Windows)

For a double-click desktop app — no Python/Node install needed on the
machine that *runs* it, and optionally LibreOffice bundled too so `.doc`
conversion works with nothing extra installed there — see
**[`packaging/README.md`](packaging/README.md)**. It's the same backend
and frontend as above, bundled with PyInstaller; building it still
requires Python/Node once, on whichever Windows machine produces it.

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

## Performance

Measured against copies of real spec files (not the tiny synthetic test
fixture), on this dev container's hardware — treat as directional, not a
guarantee of your deployment target, but the shape of the numbers should
hold:

| Operation | 50 files | 200 files | 1000 files |
|---|---|---|---|
| Cold vault open (parse everything) | 2.4s | 10.4s | 53.0s |
| Single cell edit, round trip | 161ms | 183ms | 162ms |
| Cross-vault Bill of Materials view, server-side build | 13ms | 7ms | 82ms |

Two things worth knowing:

- **Editing is fast regardless of vault size.** A single cell write only
  ever re-parses the one file that changed, not the whole vault, so it
  stays around 150–200ms whether the vault has 50 files or 1000. This
  used to *not* be true in the frontend specifically — the Mass Edit
  grid was refetching and re-rendering the entire view after every
  single edit, which took 3+ seconds on a 1650-row grid even though the
  write itself was ~180ms. Fixed by patching just the edited cell in
  local state instead of reloading the whole table; verified in a real
  browser that a single edit against a 1650-row grid now takes ~0.35s
  (was ~3.3s).
- **Opening a very large vault for the first time is a real, linear
  cost** (~50ms/file to parse) — 200 files is an ~11 second wait, 1000
  files is closer to a minute. That's a one-time cost per session (not
  per edit), but if real customer vaults run into the hundreds of files
  opened all at once, it's worth knowing about before relying on this
  day-to-day. Fixes if it matters in practice: index in the background
  and populate the sidebar incrementally instead of blocking on the
  full scan, or parallelize parsing across files (parsing is CPU-bound
  and currently single-threaded).

For a realistic single-customer or single-product-line folder (tens of
files), none of this is noticeable — everything above is snappy well
under a second. It only becomes a real wait at the scale of a full
multi-hundred-file archive opened as one vault.

## Known limitations (v1 scaffold)

- One row in Slitting Information sometimes stacks two labels
  (`Core Tags:` / `Splice Code:`) inside a single physical cell; the
  parser currently reads that as one combined field instead of two.
- `.doc` conversion requires LibreOffice installed and functional on the
  machine running the backend (`soffice` on PATH). It degrades to a
  clear error if missing or non-functional, but hasn't been validated
  against a real legacy `.doc` file end-to-end in this repo's own dev
  environment (LibreOffice's headless mode was broken in the sandbox
  this was built in — the code follows the standard approach, but test
  it against your real deployment target before relying on it).
- The blank "New Spec" template is synthetic (no real logo/boilerplate)
  until someone swaps in a real blank Toppan master template.
- Only one vault can be open at a time (matches the single-folder,
  single-window model this is meant to emulate, but is a real constraint
  if multiple admins need concurrent access).
- No conflict handling if two people edit the same file at once, or if a
  file changes on disk mid-write.
- The audit log's "who" is a free-text name typed into the browser, not
  an authenticated identity — fine as a change record, not sufficient on
  its own if compliance ever requires provable attribution.
