# Cobalt

**Read and mass-edit a library of packaging specification documents
without opening them one at a time.**

Point Cobalt at a folder of customer spec `.docx` files — a plant's
library, a customer's folder, a whole division's archive — and everything
inside it, however deeply nested, is indexed and live. Change a material
across hundreds of specs, or even thousands, from one grid instead of opening Word docs individually.
Nothing is imported, exported or converted into a database: the `.docx`
files on the network drive stay the originals, and Cobalt edits them in
place.

It runs on your own machine against your own folder. There is no server to
stand up, no account to create, and nothing leaves the network drive the
specs already live on.

---

## Get it

**[⬇ `install_cobalt.bat`](https://github.com/ipalmer100/Cobalt/releases/latest)**
— download "install_cobalt.bat" and double-click it.

No Python, no Node.js, no Git, no terminal, no administrator rights. It
downloads the current build of Cobalt, puts it in `%LOCALAPPDATA%\Cobalt`,
adds a **Cobalt** shortcut to your Desktop, and offers to start it. Run the
same file again any time to update.

Everything else is on the releases page.

| File | Use it when |
| --- | --- |
| `install_cobalt.bat` | Normally. It installs and updates Cobalt for you. |
| `Cobalt-windows.zip` | You want the app folder itself — to put on a share, or to install somewhere the installer cannot reach. Unzip and double-click `Cobalt.exe` inside. |

Both URLs always resolve to the newest release, so they are safe to paste
into an email:

```
https://github.com/ipalmer100/Cobalt/releases/latest/download/install_cobalt.bat
https://github.com/ipalmer100/Cobalt/releases/latest/download/Cobalt-windows.zip
```

A few things worth knowing either way:

- **Keep the app folder together.** `Cobalt.exe` does not run if you move
  it out on its own — it needs the `_internal` folder beside it. The
  installer handles this; a manual copy is where it goes wrong.
- **`%LOCALAPPDATA%` is deliberate**, not the Desktop or Documents. Those
  are OneDrive-synced here, and the app is several thousand files that
  would be uploaded one at a time.
- **Your spec files are never touched.** They stay in their own folder,
  which neither route goes near.
- **On a managed PC, Windows may refuse a newly-built unsigned
  executable.** The installer clears the downloaded-from-the-internet mark
  that causes the SmartScreen prompt, but Defender's
  attack-surface-reduction rules and AppLocker are separate and need IT.
  The symptoms look similar and the fixes are not; the table in
  [`packaging/README.md`](packaging/README.md#running-it-on-a-managed-pc)
  tells them apart, and running Cobalt from source avoids the executable
  entirely.

Publishing a release is [`RELEASING.md`](RELEASING.md).

---

## What it does

- **Reads a whole library at once.** Subfolders included — one pick covers
  a library organised by customer. A 1,000-spec folder opens in about 15
  seconds, 15,000 in about three minutes.
- **Mass Edit**: one section of every spec as a single table — Bill of
  Materials across the library, Slitting Information across the library —
  sortable, filterable per column, and editable in place. Edits write
  straight back into the Word files.
- **Spec Detail**: one spec, every section, exactly as the document has
  it, editable field by field.
- **Finds the specs you mean.** Search by spec number, customer, file name
  or folder; filter by customer, by spec category, and by
  active/inactive — a spec filed under an *Inactive* or *Obsolete* folder
  is hidden from both the list and the grid with one toggle.
- **Creates a new spec** by duplicating an existing one or from a blank
  template, and refuses a spec number another spec in the folder already
  carries.
- **Keeps revision numbering honest.** Revision History and the header's
  Revision # can only change together, through the explicit "Add Revision"
  action — no data edit ever touches either. **Revision Check** lists every
  spec where the two have drifted apart.
- **Logs every change it makes** to `.cobalt/audit_log.jsonl` inside the
  folder — who, when, which spec, what changed — separately from the
  documents' own Revision History.
- **Handles legacy `.doc` files** by converting them to `.docx` in the
  background on first sight, leaving the original untouched. Half of the
  division's archive is still `.doc`.
- **Reads paths Windows normally can't.** A customer folder deep enough to
  push a path past Windows' 260-character limit used to look like a corrupt
  file; it opens.
- **Light and dark**, following the system or set explicitly.

---

## Opening it

The same application however you start it — the same backend serving the
same interface on one local port, which your browser displays. Pick by
what is installed on the machine that will run it, not by what you want it
to do. The installer from [Get it](#get-it) above covers the common case;
these are the rest.

### The packaged app — nothing installed at all

See [Get it](#get-it) above. Nothing needs installing on the machine that
runs it, not even Python or Node — but somebody has to build it first, on
Windows, and publish it ([`RELEASING.md`](RELEASING.md)).

1. Download and unzip `Cobalt-windows.zip`, or get the `Cobalt` folder from
   whoever built it. Keep the **whole folder** together; `Cobalt.exe` needs
   its `_internal` sibling.
2. Double-click **`Cobalt.exe`** inside it.
3. A console window opens — leave it open, it *is* the running app — and
   your browser opens to Cobalt.
4. Click **Browse…**, pick your folder of specs, and click **Open Vault**.

Closing the console window stops the app. Double-clicking the exe again
while it is already running just brings your browser back to it.

On a managed corporate PC the first launch may be blocked — by SmartScreen,
by Defender's attack-surface-reduction rules, or by AppLocker. Each looks
different and each has a different fix; the table in
[`packaging/README.md`](packaging/README.md#running-it-on-a-managed-pc)
tells them apart. The usual answer is `packaging\run_cobalt.bat`, which
starts the identical app through Python so there is no new executable for
allow-listing to object to, and `packaging\create_shortcut.bat`, which puts
a double-clickable **Cobalt** shortcut on the Desktop pointing at it.
Cobalt has never needed administrator rights.

### From the command line

For a machine with Python and Node, or for running it from source. One
command, one port, one browser tab — the backend serves the built frontend
itself, so there is no second terminal and no dev server:

```bash
cd frontend && npm install && npm run build && cd ..
cd backend && pip install -e . && python -m cobalt.desktop
```

It prints the port, opens your browser, and says whether `.doc` conversion
is available:

```
Starting Cobalt...
Opening http://127.0.0.1:8765/ in your browser.
.doc conversion: available (/usr/bin/soffice)
```

Then click **Browse…** and pick your folder, the same as above. Needs
Python ≥3.11 and Node once, on the machine you run it from. LibreOffice is
optional — without it `.docx` specs work normally and each `.doc` shows a
clear per-file error instead of converting.

Leave that terminal open while you use the app; closing it stops the
server.

There are also two command-line tools that answer a question about a
library without opening the app at all — a revision-numbering audit and a
structure survey. Both are below, under
[Checking revision numbering](#checking-revision-numbering) and
[Describing a library without exporting it](#describing-a-library-without-exporting-it).

### For working on Cobalt itself

Run the API and Vite separately so both hot-reload:

```bash
cd backend
pip install -e .
python -m uvicorn cobalt.api:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

Open the printed Vite URL (`:5173`), which talks to the backend on `:8000`
via `frontend/.env.development`.

---

## Finding your way around

Five tabs across the top, and a sidebar listing every spec in the folder.

| Tab | What it's for |
| --- | --- |
| **Spec Detail** | One spec, every section, as the document has it. Edit a field, or add a revision. |
| **Mass Edit** | One section across every spec, as a grid. Pick the section from the dropdown. |
| **Audit Log** | Every change Cobalt has made to this folder — who, when, which spec. |
| **Revision Check** | Specs whose header Revision # and Revision History disagree. Report only. |
| **Exceptions** | Tables whose heading Cobalt would not guess a section for, waiting for someone to allocate them. |

In the sidebar: a search box (spec number, customer, file name or folder),
and — each appearing only when the folder actually holds more than one of
the thing it filters — a customer dropdown, a Category control, and the
Active/Inactive toggles. The filters apply everywhere: a spec hidden in
the list is hidden in Mass Edit too, and each control shows its count, so
you can see that nothing has gone missing, it has only moved.

**+ New Spec** creates one, by duplicating an existing spec or from the
blank template. Duplicating carries the data tables over as a starting
point and resets Spec #, Customer and Revision History. A spec number
already used in the open folder is refused, naming the spec that holds it.

**Your name**, top right, is attached to every write for the audit log.
There is no login — it is a per-browser display name, not authentication.
Beside it, the appearance control cycles Match system → Light → Dark.

---

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

### Several plants at once

Pointed at a division folder — plant folders over customer folders —
`--by-plant` adds a per-plant table, because that is the unit a rollout is
planned in and divisional totals answer none of its questions:

```
python -m cobalt.structure_export "/path/to/division" --out division.json --by-plant
```

```
  Plant                                        specs   .doc  layouts  unknown   bad
  Elk Grove Flexible Plant Documentation          20      0        1        0     0
  Waco Flexible Plant Documentation - Cus...      14      5        1        1     0
  Franklin OH Plant Specifications                 9      0        2        0     0
```

`.doc` says which plants need LibreOffice at all, `layouts` how varied
their templates are, and `unknown` how much triaging each needs before
anyone there uses Cobalt.

It is off by default, and it is the only option that puts a folder name in
the report: that top-level folder is a plant only when the path is rooted
at a division. Rooted at one site it is a customer, so this stays
something the caller turns on knowingly.

## Under the hood

Everything below is for working on Cobalt rather than using it.

### How it works

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
- **`backend/cobalt/paths.py`** — the `\\?\` prefix that lets Windows
  open a path longer than 260 characters. Applied at every filesystem
  call rather than stored, so paths stay ordinary everywhere else. Without
  it a spec in a deep customer folder reports
  `PackageNotFoundError`, which reads as "this is not a Word file" when
  the truth is "Windows would not open this path" — three specs in the
  division survey were diagnosed as corrupt on that basis and were fine.
- **`backend/cobalt/creation.py`** — creates a new spec, either by
  duplicating an existing one (data tables carry over as a starting
  point; Spec #, Customer, and Revision History reset) or from the
  bundled blank template (`cobalt/templates/blank_spec_template.docx`
  — a synthetic placeholder with no real branding; swap in a real blank
  Toppan master template by regenerating via
  `scripts/build_blank_template.py` or replacing the file directly). Also
  owns the spec-number guardrail: `find_number_conflicts` says which specs
  in the folder already carry a number, and `api.py` refuses creation with
  a 409 rather than letting two documents answer to one number. The
  browser runs the same rule (`frontend/src/specNumber.ts`) to disable the
  button as you type, but the server is the authority — a browser's index
  can be seconds stale.
- **`backend/cobalt/audit_log.py`** — a second, independent change log,
  entirely separate from Revision History. Every write the app makes
  (mass-edit cell/field, row add, revision, conversion, new spec) is
  appended as one JSON line to `<vault_root>/.cobalt/audit_log.jsonl`
  — never into a `.docx`. Lives inside the vault (Obsidian's `.obsidian/`
  convention) so it travels with the folder and is shared by anyone who
  opens it. `GET /audit-log` reads it back; the frontend's "Audit Log"
  tab shows it as a table (time, who, spec, what changed).
- **`frontend/`** — a React/Vite shell: a virtualized sidebar file list
  with search, customer, category and active/inactive filters and a "New
  Spec" action (a legacy `.doc` entry shows its automatic conversion's
  live status — "Converting to .docx…", then either disappears once the
  `.docx` is ready or shows an error — with no click required), an
  editable Spec Detail view, the virtualized Mass Edit grid, and the Audit
  Log, Revision Check and Exceptions tabs. A "Your name" field in the top
  bar (persisted in `localStorage`) is attached to every write for the
  audit log's "who" — there's no login system, so this is a per-browser
  display name, not authentication. The active/inactive rule lives in
  `src/specStatus.ts` and is shared by the sidebar and the grid, so a spec
  hidden in one is hidden in both.

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

Mass Edit is the standard category, and its views are exactly the thirteen
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
  guessed at.** `Press Specification`, `S3 Machine Conditions` and the
  like are shown with a preview of their contents
  and the specs they appear in, and a human allocates each to a
  canonical section (or marks it "not a spec section"). Guessing here would be worse
  than not reading the table at all — a Press Specification quietly
  filed under Process Routing corrupts what everyone reads off the grid,
  invisibly.
- Decisions are keyed by heading text and saved in the vault
  (`.cobalt/section_mappings.json`), so allocating `Press Specification`
  once covers every spec in the archive that uses that heading, for
  everyone who opens the folder, and survives reopening. They're
  reversible (Undo returns the heading to the queue) and logged to the
  audit log.
- **A heading common enough across the division becomes canonical rather
  than staying in the queue.** `Quality Issues` and `Die Cut Information`
  arrived that way: the structure survey found them in roughly 5,600 and
  1,550 specs respectively, across every plant, which is a section the
  templates have and Cobalt did not — not an exception for each plant to
  triage separately.

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
works, and keeping Revision History free of the "changed X to Y" busywork
a fully automatic log would generate on every keystroke.

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
- **Packing Information and Slitting Information are laid out two
  different ways across the division, and Cobalt reads one of them wrong.**
  The structure survey of 8,212 specs found Packing Information parsing as
  a `Label:`/value grid in 7,985 specs and as a header-plus-rows table in
  639 (Slitting: 6,957 and 78). In the minority shape the first data row is
  read as the header, so that spec's own values become column names — 261
  distinct ones, which is why the Mass Edit grid for those sections shows
  columns nobody recognises. The two shapes need telling apart before the
  grid for those sections can be trusted division-wide; everything else
  parses consistently.
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
