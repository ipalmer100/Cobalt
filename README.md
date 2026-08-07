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
fixture), on this dev container's hardware (4 cores) — treat as
directional, not a guarantee of your deployment target, but the shape of
the numbers should hold:

| Operation | 50 files | 200 files | 1000 files | 15,000 files |
|---|---|---|---|---|
| Cold vault open (parse everything, parallelized) | ~1s | ~3s | ~15s | ~3 min |
| Single cell edit, round trip | 161ms | 183ms | 162ms | ~180ms |
| Bill of Materials view, server-side build + serialize | 13ms | 7ms | 82ms | ~1.1s |
| Audit log read (last 200 entries) | <1ms | <1ms | <1ms | <1ms regardless of log size |

Three things worth knowing:

- **Editing is fast regardless of vault size.** A single cell write only
  ever re-parses the one file that changed, not the whole vault, so it
  stays around 150–200ms whether the vault has 50 files or 15,000. This
  used to *not* be true in the frontend specifically — the Mass Edit
  grid was refetching and re-rendering the entire view after every
  single edit, which took 3+ seconds on a 1650-row grid even though the
  write itself was ~180ms. Fixed by patching just the edited cell in
  local state instead of reloading the whole table; verified in a real
  browser that a single edit against a 1650-row grid now takes ~0.35s
  (was ~3.3s).
- **Opening a large vault is parallelized across CPU cores**, not
  single-threaded. docx parsing is pure-Python, CPU-bound work that holds
  the GIL for its whole duration, so threads wouldn't help — indexing
  splits the file list across worker *processes* instead (see
  `vault.py`'s `_full_index_parallel`). Confirmed on this 4-core sandbox:
  a 15,000-file vault (13,500 `.docx` + 1,500 legacy `.doc`) that took
  **~17 minutes** to cold-open before this fix takes **~3 minutes** after
  it — a real machine with more cores should do better still. Below 32
  files it stays sequential, since spinning up a process pool costs more
  than it would save at that size.
- **The first request against a freshly-opened large vault used to pay a
  one-time garbage-collector tax.** Python's cyclic GC periodically walks
  every tracked container object looking for reference cycles — including
  the thousands of already-parsed, never-changing Spec objects sitting in
  memory — even though a request like "build the Bill of Materials view"
  never creates a cycle involving them. Confirmed empirically: the first
  view request after opening a 15,000-file vault took ~3x longer than
  every one after it (5–7.6s vs. ~1.6s), and calling `gc.freeze()` right
  after the initial index (exempting that static object graph from future
  collections) closed the gap — both now land around ~1.1–1.2s.

For a realistic single-customer or single-product-line folder (tens of
files), none of this is noticeable — everything above is snappy well
under a second. It only becomes a real wait at the scale of a full
multi-hundred-file archive opened as one vault, and even then, opening is
now a few minutes rather than tens of minutes at the high end (15,000
files) tested here.

### Scenario analysis: a 15,000-file mixed .doc/.docx library

Run against a synthetic vault of 13,500 `.docx` + 1,500 legacy `.doc`
files (real sample spec content, copied and renamed, not hand-built
fixtures) to find where this breaks at the scale a full multi-year
archive could reach. Four real, confirmed bugs came out of it and are
fixed (see above and the git history for `vault.py`, `audit_log.py`,
`api.py`, and `Sidebar.tsx`):

1. Cold vault open was single-threaded (~17 min at 15,000 files) — fixed
   via parallelized indexing across worker processes.
2. The first Mass Edit view request after opening a large vault paid a
   one-time GC scan of the whole persistent object graph (~3x slower
   than every request after it) — fixed via `gc.freeze()`.
3. The audit log (`.specwrite/audit_log.jsonl`) read and JSON-parsed its
   *entire* contents on every request regardless of how many entries were
   actually requested — harmless on a fresh vault, but a heavily-used
   15,000-file vault's log can realistically grow to hundreds of MB over
   months, and it was taking 4+ seconds to fetch just the last 200
   entries out of a 300,000-line/74MB simulated log. Fixed by reading
   backward from the end of the file in chunks instead of the whole thing
   (now sub-millisecond for the common case).
4. The sidebar's file list rendered every vault entry as a real,
   permanently-mounted DOM node with no windowing — fine at dozens of
   files, a real problem at thousands. Fixed with the same
   `@tanstack/react-virtual` windowing the Mass Edit grid already used,
   so only the visible slice (~30 nodes) is ever mounted regardless of
   vault size.

One more, lower-severity fix from the same pass: a bulk drop of many
files into an already-open vault (a migration, a network-drive resync)
used to spawn a brand-new OS thread per debounced file-change event with
no cap. Replaced with a single scheduler thread plus a small fixed
worker pool, so a burst of thousands of events no longer scales thread
count with burst size.

**What's confirmed working correctly at 15,000 files, mixed `.doc`/
`.docx`:** indexing (all 15,000 entries land with correct
spec_number/customer/revision, `.doc` files correctly flagged
unsupported without attempting to parse them), the sidebar, Mass Edit
view loading, single-cell edits, and memory footprint (~800MB resident
holding all 13,500 parsed specs — actually *lower* than before
parallelizing indexing, likely because work distributed across
short-lived worker processes leaves less garbage in the long-lived main
process's heap than parsing everything in one process would).

**What this pass did not fix, and is worth knowing about before relying
on this at that scale day-to-day:**
- Converting `.doc` files to `.docx` is still one-at-a-time from the
  sidebar. Fine for occasional legacy files; a real gap if a 15,000-file
  archive has hundreds or thousands of `.doc` files needing conversion —
  a batch "convert all" endpoint would be the natural next step.
- `/views/{section}` still returns every matching row across the whole
  vault in one response (Bill of Materials at 15,000 files was a 64MB
  JSON payload). The Mass Edit grid's own rendering is virtualized and
  handles that fine once loaded, but the fetch itself is a real,
  un-paginated cost every time that view is opened or refreshed. True
  pagination would need reworking how the grid's client-side sort/filter/
  group-by operate (currently over the full row set) and was out of scope
  for this pass.
- No progress indicator during a multi-minute cold open — just an
  indefinite "Opening…" label. Tolerable at ~3 minutes; was a real risk
  of looking hung at the old ~17-minute figure. Worth adding if vaults
  routinely open in the multi-minute range in practice.

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
