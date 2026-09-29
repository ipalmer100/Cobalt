# Handing Cobalt to another plant

Two halves: what you do before handing it over, and what the person
receiving it does. The second half is written so you can paste it into an
email as-is.

Budget about half a day for the first plant and an hour for each one after,
most of it waiting on IT.

---

## Part 1 — Decide how it will be delivered

This is the only decision that really matters, and it should be made before
anything is built.

| | Recipient needs | Effort per plant |
| --- | --- | --- |
| **Signed `.exe`** | Nothing | Zip and send |
| **Unsigned `.exe`** | Nothing, but IT must allow it | An IT exception per site |
| **From source** (`run_cobalt.bat`) | Git + Node.js + Python, and a build | Not a handoff — don't |

`run_cobalt.bat` exists so *you* can keep working while the exe is blocked.
It is not a distribution mechanism: it runs from the source tree and needs a
developer toolchain. Do not send it to a plant.

**If you have a code-signing certificate, use it.** Signed is the only form
that scales — it satisfies SmartScreen, publisher-based AppLocker rules and
Defender's prevalence check at once, with no per-site exception. Without
one, every plant is a separate conversation with IT, and that conversation
is longer than everything else in this document combined.

---

## Part 2 — Before you hand it over

### 1. Get the current code and build it

```
cd C:\path\to\Cobalt
git pull origin claude/toppan-spec-management-r7nmue
```

If you have a certificate, set it first so the build signs the result:

```
set COBALT_SIGN_THUMBPRINT=<the certificate's SHA1 thumbprint>
```

Then:

```
packaging\build_windows_exe.bat
```

The app lands in `packaging\dist\Cobalt\`. Not `packaging\build\` — that is
PyInstaller's scratch directory and the exe inside it will not run.

### 2. Work out whether that plant needs LibreOffice

It is used for one thing: converting legacy `.doc` files the first time
Cobalt sees them. A library that is entirely `.docx` needs none of it, and
bundling it adds several hundred MB.

In that plant's spec folder, search for `*.doc` — with no `x`. If there are
none, skip to step 3.

If there are some, unpack a portable LibreOffice into the Cobalt folder so
that this exists, then re-run the build:

```
packaging\libreoffice\program\soffice.exe
```

### 3. Look at their library before they do

Every plant writes its specs slightly differently, and the parser learns
those differences per heading. Point the structure export at their folder:

```
cd backend
python -m cobalt.structure_export "\\path\to\their\specs" --out plant.json
```

Read three things in `plant.json`:

- **`unreadable`** — should be 0. Anything here is a file Cobalt cannot
  open at all, and you want to know before they do.
- **`unclassified_headings`** — sections Cobalt does not recognise. These
  are the ones that need step 4.
- **`legacy_doc_files_skipped`** — confirms your answer to step 2.

Send them `plant.json` if you like; it contains no cell values, no file
paths and no customer names. Keep `plant-local-map.json` — that one names
their files.

### 4. Triage their unknown sections once, for everyone

Open their folder in Cobalt yourself and go to the **Exceptions** tab. Every
heading Cobalt could not place is listed with a preview. Allocate each one
to a section, or mark it "not a spec section."

Do this before handing over. Decisions are saved into
`<their vault>\.cobalt\section_mappings.json`, so they travel with the
folder and apply for everyone who opens it — you are doing it once for the
whole plant, not once per person.

### 5. Run the revision check and give them the result

```
cd backend
python -m cobalt.revision_audit "\\path\to\their\specs"
```

This reports specs whose Revision # and Revision History disagree. It only
reports — renumbering a regulated document is the spec owner's call, not
yours. Hand the output over as a starting to-do list, not as a defect
report about their work.

### 6. Package it

Zip the **whole** `packaging\dist\Cobalt\` folder. Not just `Cobalt.exe` —
it will not run on its own.

### 7. Tell IT before the recipient hits the wall

If the exe is unsigned, the recipient will be blocked on first run and the
message will not say why. Get ahead of it. Ask their IT for one of:

| If the block is | Ask for |
| --- | --- |
| Defender attack-surface-reduction | An exclusion for the folder the app will live in |
| AppLocker | A path rule for that folder |
| WDAC | The exe in the policy — which means signing it |

Tell them where the folder will be, and that the app needs no
administrator rights, no installer and no network access — it reads and
writes documents in a folder as whoever runs it.

---

## Part 3 — What the recipient does

*Paste this part into the handover email.*

Cobalt reads your existing spec documents where they already are. It does
not move them, convert them, or need them imported — your specs stay as
Word files in the same folders, and Cobalt reads and writes them in place.

1. **Unzip the folder somewhere you can write to** — `Documents\Cobalt\` is
   fine. Not Program Files.
2. **Make sure your spec folder is available offline.** If it is a
   SharePoint library synced with OneDrive, right-click it and choose
   **Always keep on this device**. Cobalt reads the files from disk.
3. **Double-click `Cobalt.exe`.** A console window opens and your browser
   opens onto Cobalt. Leave the console window alone — closing it stops the
   app.
4. **Type your name** in the box at the top right. Every change you make is
   recorded against it.
5. **Point it at your spec folder** and press Open Vault. Browse… lists your
   Desktop to start from, or paste the full path.
6. **Wait for the first index.** Roughly 15 seconds per 1,000 specs; a
   2,000-spec library takes under a minute. This happens once per session,
   not once per spec.

Then check three things before trusting it:

- **The spec count** in the sidebar matches roughly what you expect.
- **Open one spec you know well** and confirm the values match the document.
- **Look at the Revision Check tab** — it lists specs whose revision number
  and revision history disagree. Those are pre-existing, not something
  Cobalt did.

### Things worth knowing

- **One person at a time per spec.** Cobalt does not merge concurrent
  edits. Two people editing the same spec from different machines through
  OneDrive will produce a sync conflict, the same as it would in Word.
- **Nothing is written until you press Save** and describe the revision.
  Cells are read-only until you press Edit. If the app is closed or the
  machine dies mid-edit, nothing is written at all.
- **"Your name" is a typed name, not a login.** It is a change record, not
  proof of identity.
- **Blown Film specs** are shown in Spec Detail only and do not appear in
  Mass Edit — they are built differently enough that bulk-editing them
  alongside the others was a bad idea.
- **To update Cobalt**, replace the whole folder with a new one. There is
  no auto-update.

---

## Part 4 — After the first plant

Two things are worth doing once and reusing:

- **Keep each plant's `plant.json`.** Comparing two plants' structure
  reports tells you what is genuinely different about their templates
  before anyone complains.
- **Feed unknown headings back.** If several plants share a heading Cobalt
  does not recognise, it belongs in the parser rather than in each plant's
  exception queue.
