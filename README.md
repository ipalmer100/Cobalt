# Cobalt

"Obsidian for specs" — point it at a folder of flexible-packaging customer
spec `.docx` files and get a live, instantly-synced view of all of them,
plus a tabular mass-edit grid per section (Bill of Materials, Slitting
Information, etc.) instead of opening one Word document at a time.

## How it works

- **`backend/cobalt/docx_sections.py`** — reads a spec: finds each of
  the canonical sections by locating its title paragraph and taking the table
  that follows it (Product Description is the exception — it lives in
  the page header, with a fallback to the first body table for older
  specs that never got one).
- **`backend/cobalt/docx_writer.py`** — writes a spec by cell address
  (row/col or label), preserving the target cell's existing formatting,
  and a composite `apply_revision()` that bumps the header's Revision #
  and appends a Revision History row in one call. This is the *only* path
  that's allowed to touch either of those — see "Revision History" below.
- **`backend/cobalt/vault.py`** — indexes a folder of specs and
  watches it for changes (`watchdog`), the same "select a folder, it's
  instantly live" model as Obsidian's vault.
- **`backend/cobalt/views.py`** — flattens every spec's copy of a
  section into `Spec Number | Customer | <columns> | File Path` rows —
  the shape of the sample Bill of Materials workbook, generalized to all
  canonical sections. Bill of Materials specifically unions Primary + Secondary
  Approved Materials into one grid with a Material Type column, matching
  the existing VBA extractor's output.
- **`backend/cobalt/api.py`** — FastAPI HTTP + WebSocket layer over
  the above. One vault open at a time; the WebSocket pushes a "changed"
  event on every write (ours or an external Word edit) so open views
  refresh immediately. (Needs `uvicorn[standard]` — plain `uvicorn` has no
  WebSocket implementation and silently 404s `/ws`; see pyproject.toml.)
- **`backend/cobalt/doc_conversion.py`** — converts legacy `.doc`
  files to `.docx` via LibreOffice headless (`soffice --headless
  --convert-to docx`). The original `.doc` is never touched/deleted.
  `vault.py` calls this automatically and silently the first time it sees
  a `.doc` without a same-named `.docx` next to it — see "Legacy `.doc`
  handling" below; there's no manual "convert" action anywhere in the UI.
- **`backend/cobalt/creation.py`** — creates a new spec, either by
  duplicating an existing one (data tables carry over as a starting
  point; Spec #, Customer, and Revision History reset) or from the
  bundled blank template (`cobalt/templates/blank_spec_template.docx`
  — a synthetic placeholder with no real branding; swap in a real blank
  Toppan master template by regenerating via
  `scripts/build_blank_template.py` or replacing the file directly).
- **`backend/cobalt/audit_log.py`** — a second, independent change log,
  entirely separate from Revision History. Every write the app makes
  (mass-edit cell/field, row add, revision, conversion, new spec) is
  appended as one JSON line to `<vault_root>/.cobalt/audit_log.jsonl`
  — never into a `.docx`. Lives inside the vault (Obsidian's `.obsidian/`
  convention) so it travels with the folder and is shared by anyone who
  opens it. `GET /audit-log` reads it back; the frontend's "Audit Log"
  tab shows it as a table (time, who, spec, what changed).
- **`frontend/`** — a small React/Vite shell: sidebar file list with a
  "New Spec" action (a legacy `.doc` entry shows its automatic
  conversion's live status — "Converting to .docx…", then either
  disappears once the `.docx` is ready or shows an error — with no click
  required), a read-only Spec Detail view, the tabular Mass Edit grid, and the
  Audit Log tab. A "Your name" field in the top bar (persisted in
  `localStorage`) is attached to every write for the audit log's "who" —
  there's no login system, so this is a per-browser display name, not
  authentication.

### Legacy `.doc` handling is automatic, one-time, and silent

python-docx (and therefore the whole parser/writer) can only read the
post-2007 `.docx` XML format, so a `.doc` file is useless to the app as
it is. Rather than surfacing that as a "please convert this yourself"
prompt, the vault handles it on its own the moment it sees the file:

- The first time `vault.py` indexes a `.doc` with no same-named `.docx`
  next to it, it queues that file for conversion (via
  `doc_conversion.convert_doc_to_docx`) on a dedicated background thread
  — never blocking vault-open or any other request. Deliberately one
  file at a time rather than a pool: concurrent `soffice --headless`
  invocations can collide over the same default LibreOffice
  user-profile lock.
- Until that finishes, the file shows up as a normal vault entry with a
  "Converting to .docx…" status (visible in the sidebar, no click
  needed) rather than being hidden or blocking anything.
- Once conversion succeeds, the resulting `.docx` becomes the real,
  tracked entry (parsed, editable, listed under its own name) and the
  `.doc` entry disappears — the app only ever shows/edits `.docx` from
  that point on. The original `.doc` file is left on disk untouched
  (never deleted or modified) as a safety net; only the app's view of
  the vault stops tracking it.
- If conversion fails (LibreOffice missing, broken, or a genuinely
  corrupt file), the entry shows a "Conversion failed: …" error instead
  of retrying in a loop. Reopening the vault (or fixing LibreOffice and
  restarting the app) tries again, since "does a `.docx` sibling already
  exist" is itself the durable record of "already converted" — there's
  no separate database tracking conversion state, and no re-conversion
  of a `.doc` that already has its `.docx` counterpart.

This means a folder with, say, 150 `.doc` files and 150 `.docx` files
"just works": open the vault, the 150 `.docx` files are immediately
usable, and the 150 `.doc` files quietly become `.docx` in the
background over the next while with no action needed from anyone.

### Choosing the folder, and folders-within-folders

On launch the app asks which folder to open, and remembers the answer:

- The last-opened folder is prefilled and the previous five are listed as
  one-click buttons, so a daily user never retypes a long SharePoint path.
  It is deliberately *not* auto-opened — indexing a large library takes
  real time, so starting that stays an explicit click.
- **Browse…** opens an in-app folder browser rather than the OS dialog.
  This is not laziness: the app runs in the user's default browser, and
  browsers deliberately withhold real filesystem paths
  (`webkitdirectory` and `showDirectoryPicker` hand back file handles,
  never a path), while opening a vault needs a real path. So the
  directory listing is served by the backend — `GET /browse` — which is
  running on the machine that actually holds the files. It shows how many
  specs sit directly in the folder you're looking at, as a "you're in the
  right place" hint. **Change** in the sidebar returns to this screen.
- The typed path still works, and is the escape hatch for a UNC path you
  want to paste (`\\server\share\Specs`).

**Subfolders are always included** — one pick covers a whole library,
however deeply nested. That matters for a SharePoint library synced into
File Explorer and organised by customer, so a spec's folder is shown
wherever it would otherwise be ambiguous: under its name in the sidebar,
and as a vault-relative path in the mass-edit **File Path** column (the
stored value stays absolute — it's the write key). Two specs both called
`HK0071.docx` in different customer folders are therefore
distinguishable, which they weren't when only the filename was shown.

Two things worth knowing before rolling this out on synced storage:

- With OneDrive **Files On-Demand**, cloud-only files are downloaded when
  first read, so the first index of a large library will hydrate it.
  Marking the library "Always keep on this device" avoids a surprise.
- `.cobalt/` (the audit log and the exception queue's decisions) lives
  in the vault, which is the point — it's shared with everyone who opens
  the folder. On synced storage that also means two people deciding at
  the same moment can produce sync conflict copies of those files. There
  is no file locking: two people editing the same spec is last-write-wins
  plus whatever conflict copy the sync client makes.

### Spec categories: not every spec is the same kind of document

The extrusion plants' specs are built around sections no other spec has —
Extruder Distribution, and Blender Verification on the KIEFEL and ALPINE
lines. They are far enough from the standard shape that editing them
alongside the rest was wrong: one grid, one fill, one revision spanning
documents that do not resemble each other.

So a spec has a **category**, read from the sections it carries, and the
category decides what the app offers:

| Category | Sections that define it | Spec Detail | Mass Edit |
| --- | --- | --- | --- |
| **Standard** | — | yes | yes |
| **Blown Film** | Extruder Distribution, Blown Film Blender Verification | yes | no |

Mass Edit is the standard category, and its views are exactly the eleven
standard sections. A Blown Film spec is still fully readable and fully
editable — Spec Detail shows every one of its sections, including the ones
that categorised it, and saving works the same way with the same revision
prompt. What it does not get is bulk treatment alongside documents it does
not resemble, which also means a fill or a batch revision cannot reach one
by accident.

The category is visible without opening anything: a **Category** control at
the top of the sidebar (All / Standard / Blown Film, each with a count), a
chip on each non-standard spec in the list and in its header, and a count in
the Mass Edit toolbar of how many specs the grid's category leaves out — a
row count that silently covers fewer specs than the vault is one nobody can
rely on.

Adding a category later means naming its sections in `docx_sections.py`
(`BLOWN_FILM_SECTIONS` and the two constants beside it) and nothing else:
`STANDARD_SECTIONS`, the view list and the filter all derive from that.

### Table classification: confident matches only, everything else escalates

The Mass Edit dropdown is always exactly the canonical sections. What
varies is which of a document's tables feed each one.

- **A section can have several tables.** Franklin, OH writes specs
  covering two process paths, so FR0282 carries `Process Routing -
  Duplex` *and* `Process Routing - Triplex` (plus two `Physical
  Attributes & Testing` tables, 33 rows each). Both land in that one
  section's view, told apart by a read-only **Variant** column that
  appears only when something in the view actually has one. Each row
  carries the physical table it came from, so editing a Triplex row
  writes to the Triplex table and leaves Duplex untouched — section name
  alone is no longer a unique address.
- **Confident matches are automatic**: the exact section name, a known
  alias (a pouch spec's `Slitting Instructions` is a roll spec's
  `Slitting Information`; `Packing Specifications` is `Packing
  Information`), or a canonical name qualified by a separator
  (`Process Routing - Duplex`, `Slitting Information - IMS Dairy
  Product`).
- **Headings are matched as a reader would read them.** Measuring a real
  1,811-spec archive turned up around forty specs losing a whole section
  to how its heading was typed, and each rule below exists for cases
  found there:
  - punctuation is ignored, so `Bill of Materials-` and `Slitting
    Information:` match;
  - a stray character run together with the name is dropped —
    `eLocations`, `9Revision History`, `2.99Locations`. It has to be
    *run together*: `Press Packing Information` has a space, is a
    different section, and still goes to the queue;
  - a bilingual heading is read up to the slash, so `Packing
    Information/ Information d'emballage` is Packing Information;
  - a misspelling within one edit of a section's name matches it
    (`Packing Informatio`, `litting Information`, `Physical Attribues &
    Testing`, `Location`), two edits for the longer names — and never
    when two sections are both in range, because a heading guessed
    wrong writes into the wrong table.
- **Everything else goes to the Exceptions queue rather than being
  guessed at.** `Press Specification`, `Quality Issues`, `S3 Machine
  Conditions` and the like are shown with a preview of their contents
  and the specs they appear in, and a human allocates each to a
  canonical section (or marks it "not a spec section"). Guessing here would be worse
  than not reading the table at all — a Press Specification quietly
  filed under Process Routing corrupts what everyone reads off the grid,
  invisibly.
- Decisions are keyed by heading text and saved in the vault
  (`.cobalt/section_mappings.json`), so allocating `Quality Issues`
  once covers every spec in the archive that uses that heading, for
  everyone who opens the folder, and survives reopening. They're
  reversible (Undo returns the heading to the queue) and logged to the
  audit log.

One related parsing detail: a table may open with a merged banner row
above its real header (FR0282's duplex Process Routing starts with a
`Comments:` band). Reading that as the header would leave every column
unmapped and the rows blank in the grid, so a single-value first row
followed by a plausible header row is skipped.

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
changes them together, atomically — see `cobalt/views.py`
(`is_view_editable`, `readonly_columns_for`) and the guard in
`cobalt/api.py` (`_require_not_revision_locked`).

## Running it

### Quickest way to try it on your own folder

One command, one port, one browser tab — the backend serves the built
frontend itself, so there's no second terminal and no dev server:

```
cd frontend && npm install && npm run build && cd ..
cd backend && pip install -e . && python -m cobalt.desktop
```

It prints the port, opens your browser, and tells you whether `.doc`
conversion is available:

```
Starting Cobalt...
Opening http://127.0.0.1:8765/ in your browser.
.doc conversion: available (/usr/bin/soffice)
```

Click **Browse…** and pick your folder. Needs Python ≥3.11 and Node once,
on the machine you run it from. LibreOffice is optional — without it
`.docx` specs work normally and each `.doc` shows a clear per-file error
instead of converting.

Leave that window open while you use the app; closing it stops the
server.

### Two-terminal dev setup

For working *on* Cobalt, run the API and Vite separately so both
hot-reload:

```
cd backend
pip install -e .
python -m uvicorn cobalt.api:app --reload
```

```
cd frontend
npm install
npm run dev
```

Open the printed Vite URL (`:5173`), which talks to the backend on
`:8000` via `frontend/.env.development`.

### Packaged desktop app (Windows)

For a double-click desktop app — no Python/Node install needed on the
machine that *runs* it, and optionally LibreOffice bundled too so `.doc`
conversion works with nothing extra installed there — see
**[`packaging/README.md`](packaging/README.md)**. It's the same backend
and frontend as above, bundled with PyInstaller; building it still
requires Python/Node once, on whichever Windows machine produces it.

## Checking revision numbering

A spec states its revision twice — the `Revision #` field in Product
Description, and the last row of Revision History — and those must agree.
When they drift, the document no longer establishes which version it is.

The **Revision Check** tab lists every spec where they don't, and the two
conditions that cause it: a revision number that repeats or goes backwards,
and a Revision History ending in a blank row. It reports only. Renumbering
a regulated document is the spec owner's decision, so each finding says
what both sources claim and what the next revision would continue from,
and stops there.

Same check without opening the app, for sweeping an archive:

```
cd backend
python -m cobalt.revision_audit "/path/to/specs"
```

Exits non-zero if anything was flagged or couldn't be read, so it works in
a scheduled job.

Worth running once over any folder edited by a Cobalt build before
`0c1e54b`: that build took the next revision number from the last row of
Revision History without checking whether the row carried one, so a spec
whose table ends in a blank row was revised from `4` to `01`.

## Describing a library without exporting it

Cobalt's parsing bugs are shape bugs — a data row read as a header, a
merged banner that leaves every column unmapped, a section worded
differently in one plant's template. Finding them needs the skeleton of a
large real library, and none of it needs a single cell value.

```
cd backend
python -m cobalt.structure_export "/path/to/specs" --out cobalt-structure.json
```

It writes two files:

| File | Contents | Send it? |
| --- | --- | --- |
| `cobalt-structure.json` | Section headings as written, table shapes, column and field labels, column/row counts, how many specs share each layout, per-column fill rates and text lengths | Yes — this is the one to share |
| `cobalt-structure-local-map.json` | Which hashed id is which file | **No** — it names your files; it exists so you can trace a finding back locally |

Every cell value is excluded, and so is every path: specs are identified by
a hash of their location, stable between runs. Even the error text for an
unreadable file is scrubbed of anything path-shaped, because python-docx
reports a bad file by quoting its full path.

Specs are grouped by identical layout, so a library of thousands collapses
to a few dozen entries — a 120-spec vault produces 7 KB. The groups are the
useful part: a template used by 1,200 specs and a one-off used by three sit
side by side, and the one-offs are usually where the parser went wrong.

`suspect_labels` lists column names that read like data rather than
headers — empty header cells (`Column 2`), the same text repeated across
columns (`Target (2)`), placeholders (`--`). Those are the misparsed
tables, and they are also the one route by which content can reach the
report: where a header was mis-detected, the "labels" really are that
spec's data. Worth reading that section before sending the file on.

`--limit N` stops after N specs, for a quick sample.

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
3. The audit log (`.cobalt/audit_log.jsonl`) read and JSON-parsed its
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
spec_number/customer/revision, `.doc` files correctly queued for
automatic background conversion rather than left unhandled), the
sidebar, Mass Edit view loading, single-cell edits, and memory footprint
(~800MB resident holding all 13,500 parsed specs — actually *lower* than
before parallelizing indexing, likely because work distributed across
short-lived worker processes leaves less garbage in the long-lived main
process's heap than parsing everything in one process would).

**What this pass did not fix, and is worth knowing about before relying
on this at that scale day-to-day:**
- `.doc` conversion runs one file at a time in the background (see
  "Legacy `.doc` handling" above), deliberately, to avoid concurrent
  `soffice` invocations fighting over the same LibreOffice profile lock.
  At 1,500 `.doc` files converting serially, that's a real, if
  non-blocking, multi-minute-to-longer background tail — everything else
  in the vault is fully usable while it runs, but don't expect all 1,500
  to have finished converting within the first few seconds.
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

## Storage: a local folder, or a SharePoint library

The spec intelligence never touches a filesystem. `docx_sections.py`,
`docx_writer.py`, `models.py` and `views.py` — section detection, the
Duplex/Triplex variant handling, the exception classifier, newline-safe
writes, the revision lock — work on **bytes**, via `parse_bytes()` and
`apply_to_bytes()`. That is what lets the same logic run against a folder
on disk or a document library reached over HTTPS.

Underneath sits `storage.py`, whose `SpecStore` interface is deliberately
small: enumerate the specs, hand over one's bytes, take modified bytes
back, say when something changed. Two implementations:

- **`LocalStore`** — a folder and everything beneath it, watched with the
  OS's own file notifications. This is the desktop app.
- **`GraphStore`** (`graph_store.py`) — a SharePoint document library over
  Microsoft Graph.

The interface acknowledges three places where those genuinely differ,
rather than pretending they're the same:

- **Identity.** A local spec is its absolute path. A SharePoint spec is an
  opaque drive-item id that survives renames and moves, with the path
  being only its current location. Callers treat `StoredItem.key` as
  opaque.
- **Concurrency.** A filesystem write is last-one-wins and silent.
  SharePoint gives every item an eTag and rejects an upload whose
  `If-Match` is stale — the only reliable way to notice that someone
  edited the same spec in Word while it sat open in the grid. `write()`
  takes the eTag the bytes were read at and raises `ConflictError`
  instead of overwriting. This is the answer to the concurrent-edit
  question the local version couldn't solve; `LocalStore` approximates it
  with a size+mtime marker, which catches the realistic case.
- **Change detection.** There is no inotify for SharePoint, so
  `GraphStore` uses `/delta`: the first call enumerates the library and
  leaves a token, and later polls return only what moved. (Graph webhooks
  would push instead of poll, but they need an endpoint SharePoint can
  reach from the internet, which an internal deployment usually can't
  offer.) Throttling is treated as routine, not exceptional — indexing
  thousands of specs earns 429s, so every request honours `Retry-After`.

Auth sits behind a one-method `TokenProvider`. `ClientCredentialsToken`
is app-only: the app authenticates as itself, which is the simplest thing
that works against a test library. The consequence is worth stating
plainly — Graph then sees one identity for everyone, so "who changed
this" is only as trustworthy as whatever login the app puts in front of
itself. Swapping in a delegated (per-user) token provider is what fixes
that, and is the only change needed here.

Graph is unreachable from this repo's build environment, so `GraphStore`
is tested against `tests/fakes/fake_graph.py` — not a stub that agrees
with everything, but a fake reproducing the behaviours that actually
shape the client: eTags with `If-Match` → 412, `@odata.nextLink` paging,
delta tokens, 429 with `Retry-After`, and `conflictBehavior=fail` → 409.

**Not yet wired up:** `Vault` (indexing, the file watcher, the conversion
queue) still talks to the filesystem directly, so the running app is
local-only today. Pointing it at a `SpecStore` is the next step, and is
mechanical by comparison now that the layer beneath it exists. Two other
things that need decisions before a hosted deployment: `.doc` conversion
shells out to LibreOffice on a real path, so under Graph it becomes
download → convert on the server → upload; and the audit log and
exception-queue decisions currently live in `.cobalt/` inside the
folder, which for a multi-user server should become a database (SQLite
behind an interface is enough to start, and upgrades to Postgres or Azure
SQL by connection string).

## Known limitations (v1 scaffold)

- One row in Slitting Information sometimes stacks two labels
  (`Core Tags:` / `Splice Code:`) inside a single physical cell; the
  parser currently reads that as one combined field instead of two.
- Some tables can't be allocated automatically and wait in the exception
  queue until someone decides (see "Table classification" above). Until
  then their rows aren't in any view — visible and pending, never
  silently misfiled.
- `.doc` conversion (automatic, see "Legacy `.doc` handling" above)
  requires LibreOffice installed and functional on the machine running
  the backend (`soffice` on PATH, or bundled into the packaged desktop
  app — see `packaging/README.md`). Each `.doc` degrades to a clear
  per-file error in the sidebar if missing or non-functional. Validated
  end-to-end against a genuine legacy `.doc` file (a real sample spec,
  downgraded to Word 97 binary format and back) — this repo's own dev
  sandbox initially only had `libreoffice-core` installed, which has no
  document filters at all (every format, not just `.doc`, failed to load
  with "source file could not be loaded"); installing `libreoffice-writer`
  on top of it fixed that completely. A normal full LibreOffice install
  (the desktop installer, `apt install libreoffice`, or the Windows
  installer used for the packaged app) already includes Writer, so this
  is only worth knowing about if you hit that same error on an
  intentionally minimal/headless-server LibreOffice install.
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
