# Building the Cobalt desktop app

Produces a folder that a non-technical user can double-click into to run
the whole app — no Python, no Node.js, no terminal, and (if you choose to
bundle it) no separately-installed LibreOffice either. Under the hood
it's the same FastAPI backend serving the same built frontend, bundled
with [PyInstaller](https://pyinstaller.org/); the browser is just how it
displays its UI, the same way many desktop apps embed a web view.

The output is a **folder**, not a single `.exe` file — `Cobalt.exe`
plus its support files sit together in `packaging\dist\Cobalt\`. This
is normal for apps this size (it's the same shape as a portable
7-Zip/VS Code install): copy or zip the *whole folder*, and
double-clicking the `.exe` inside it is still the entire "run it"
experience for whoever receives it.

This has to be **built on a Windows machine** — PyInstaller bundles a real
Windows binary and doesn't cross-compile from Linux/Mac. The steps below
are a one-time setup on whichever Windows machine does the building; the
resulting folder then runs on any similar Windows machine with no further
setup.

The packaging mechanics have been verified end-to-end by running this same
spec file as a Linux build and driving the packaged app, most recently
against the current code (storage layer, exception queue, folder picker
included). What that run confirmed:

- the build completes and produces a **57 MB** app folder (without
  LibreOffice bundled),
- the built frontend, the blank-spec template and every backend module are
  actually inside the bundle,
- the packaged app starts, serves both its UI and its API on one port, and
  works with the environment **stripped of `PATH`** — so nothing is quietly
  being borrowed from the build machine,
- opening a folder of four real specs through the packaged app indexed all
  four, auto-converted a legacy `.doc`, served a 47-row Bill of Materials
  across them, and reported four headings in the exception queue.

Treat this doc as unverified only on the *Windows-specific* details, which
can only be confirmed on real Windows: the exe launching cleanly, Windows
Defender / SmartScreen's reaction to an unsigned exe, the real Windows
`soffice.exe` and its DLLs once bundled, and watchdog's Windows
filesystem-watching backend.

**Leave time for the first Windows build.** It is the one step that has
never run on Windows, so budget an afternoon for it rather than the
evening before a presentation.

## One-time build machine setup

1. **Git** — https://git-scm.com/download/win
2. **Python 3.11+** — https://www.python.org/downloads/ (check "Add
   python.exe to PATH" during install)
3. **Node.js 20+** — https://nodejs.org/ (LTS)
4. **LibreOffice** — https://www.libreoffice.org/download/download/ —
   **optional**, only needed on this build machine if you want `.doc`→`.docx`
   conversion to work on the target machine with nothing extra installed
   there. See "Bundling LibreOffice" below before deciding.

## Build it

```
git clone https://github.com/ipalmer100/Cobalt.git
cd Cobalt
git checkout claude/toppan-spec-management-r7nmue
packaging\build_windows_exe.bat
```

The script:
1. `npm install` + `npm run build` in `frontend/` — produces `frontend/dist`.
2. Checks whether LibreOffice is installed on this machine (see below) and
   bundles it if so.
3. Creates an isolated Python virtual environment at
   `packaging\.build-venv` and installs the backend plus PyInstaller into
   it (keeps this off your system Python entirely).
4. Runs PyInstaller against `packaging/cobalt.spec`, which bundles the
   backend, the built frontend, the blank "New Spec" template, and
   (if found) LibreOffice into one app folder.

Before doing any of that it checks that Git, Node and Python 3.11+ are all
present and stops with a list of what's missing (and where to get it)
rather than failing halfway through with a confusing error.

Takes a few minutes (longer if bundling LibreOffice — it's copying a few
hundred MB). When it finishes: **`packaging\dist\Cobalt\`** is the
whole app. Copy or zip that folder anywhere — a USB drive, another
machine, the desktop — and `Cobalt.exe` inside it is the entire
"install."

## Updating an app you already built

Once the one-time setup above is done, picking up newer code is two
commands from the repo folder:

```
git pull
packaging\build_windows_exe.bat
```

`git pull` brings down the new code; the build script rebuilds the
frontend and re-runs PyInstaller. It overwrites `packaging\dist\Cobalt\`
in place, so the app folder you already have is replaced by the new one —
there's nothing to uninstall.

Three things worth knowing:

- **Close the running app first.** Windows won't let PyInstaller overwrite
  `Cobalt.exe` while it's running, and the failure looks like a
  permissions error rather than "the app is open". Close the console
  window the app opened, then build.
- **Your specs are untouched.** The app folder holds no spec data — your
  documents stay wherever they live, and the app remembers your last
  folder in the browser, not in the build. A rebuild doesn't ask you to
  re-pick it.
- **Hard-refresh once after launching** (Ctrl+F5) if the UI looks
  unchanged. The browser can serve the previous version's cached page.

If `git pull` reports a conflict because the app was run from a folder
where files got edited, `git status` will name them; `git checkout -- <file>`
discards local changes to a file you didn't mean to change.

To confirm you actually got the newer build, `git log --oneline -1` before
building tells you which commit you're on.

### If the script misbehaves

The `.bat` cannot be executed in the Linux environment this repo is
developed in, so unlike the rest of the build it has not been run
end-to-end. If it fails in a way that looks like the script rather than
your machine, these are the exact commands it runs — do them in order from
the repo root and you get the same result:

```
cd frontend
npm install
npm run build
cd ..

REM optional: bundle LibreOffice, skip these two lines to build without it
set "COBALT_LIBREOFFICE_DIR=%ProgramFiles%\LibreOffice"

py -3 -m venv packaging\.build-venv
packaging\.build-venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e "backend[build]"

pyinstaller --clean --noconfirm --distpath packaging\dist --workpath packaging\build packaging\cobalt.spec
```

If `py` isn't recognised, use `python` in its place.

## Running it

Double-click `Cobalt.exe` (inside the `Cobalt` folder — moving just
the exe out on its own won't work, it needs its sibling `_internal`
folder). A console window opens (this is intentional — it shows what the
app is doing, including whether `.doc` conversion is available and from
where, and is how you stop it later) and your default browser opens to
the app automatically. Point it at a folder of spec `.docx` files and
click "Open Vault", same as the source-code version. Closing the console
window (or Ctrl+C in it) stops the app; double-clicking the exe again
while it's already running just refocuses your browser instead of
erroring out.

## Setting up a demo copy

For showing this to people, run against a **copy** of a handful of specs,
never the live library. Two folders:

```
C:\CobaltDemo\
    master\      <- pristine specs, never opened in Cobalt
    live\        <- what you open; replaced on every reset
    Cobalt\   <- the app folder from the build
```

Put 20–40 specs in `master\`, in customer subfolders, and include **at
least one legacy `.doc`** — the automatic conversion is one of the
strongest moments and it needs a `.doc` to happen to.

Then, before each run-through:

```
python packaging\reset_demo.py --source C:\CobaltDemo\master --demo C:\CobaltDemo\live
```

Add `--list` to see what it would clear without changing anything.

**Why this matters more than it sounds.** Rehearsing changes the demo. After
one pass the audit log is full of practice edits, the exception queue's
decisions are already made, and — the one that catches people — the `.doc`
has already been converted, so it can never convert again. The app treats
"a `.docx` sibling exists" as the permanent record of "already converted",
so the reset deletes those generated files. Without that, your live demo
silently loses its best beat.

The reset also clears `.cobalt\` (the audit log and the exception-queue
decisions), so the Audit Log tab starts empty and fills up in front of the
room rather than showing yesterday's practice.

### Suggested run of show

1. **Open the folder** — one pick, and every spec across every subfolder
   appears with its spec number and revision. Mention that the library
   structure is untouched; these are the real Word documents.
2. **Read a spec** — all eleven sections on one page. The point: nobody
   opens Word to find the Bill of Materials.
3. **Mass Edit** — one section, every spec, side by side. Edit a cell, then
   drag the fill handle down a range. Say that each edit writes straight
   into that spec's `.docx`.
4. **Sort / filter / group** — the same moves people already know from
   Excel, over live documents.
5. **The `.doc`** — point out the entry that arrived as a legacy file and
   converted itself, originals untouched on disk.
6. **Revision control** — show that Revision History refuses to be edited,
   then log a revision properly and watch the revision number bump. This is
   the answer to "how do we keep this auditable".
7. **Exceptions** — the queue, and the `*** No Tape Allowed on Idlers***`
   card whose preview reveals it is really a Slitting Information table.
   The pitch: the tool doesn't guess about your documents, it asks.
8. **Audit log** — every change made during the demo, with who and when.

### If something goes wrong in the room

- **Browser shows nothing** — the console window must stay open; it *is*
  the app. Re-open http://127.0.0.1:8765/ manually.
- **A spec shows an error instead of a revision** — it's one unreadable
  file, not a crash; click a different spec and carry on.
- **`.doc conversion: unavailable`** in the console — LibreOffice isn't
  bundled or installed. `.docx` specs work normally; skip step 5.
- **Opening feels slow** — you pointed it at too much. Demo folders should
  be tens of specs, not thousands.

## Bundling LibreOffice

`build_windows_exe.bat` automatically checks `%ProgramFiles%\LibreOffice`
and `%ProgramFiles(x86)%\LibreOffice` on the build machine. If it finds
LibreOffice there, it bundles the *entire* install (several hundred MB —
LibreOffice isn't small, and its `soffice.exe` needs its sibling `share\`
folder alongside it to run at all, not just the one exe) into
`Cobalt\_internal\libreoffice\`. `.doc` conversion then works on any
machine running the built app, with nothing else installed there.

If LibreOffice isn't found on the build machine, the script proceeds
without it and says so — the app still works for everything else. `.doc`
conversion in that case falls back to whatever `soffice` it finds on
PATH on the machine *running* the app (the original behavior, unchanged);
if none is installed there either, converting a `.doc` file fails with a
clear error instead of silently doing nothing.

To add LibreOffice to a build that was made without it: install
LibreOffice on the build machine, then re-run
`packaging\build_windows_exe.bat` — it'll be picked up and bundled on the
next build.

## Known constraints of this v1 packaging

- **Unsigned binary.** Windows SmartScreen / Defender will very likely
  flag a fresh, unsigned exe from an unrecognized publisher on first run
  ("Windows protected your PC"). Click "More info" → "Run anyway." Code
  signing would remove this but needs a paid certificate and is out of
  scope for v1.
- **One instance, one vault.** Same constraint as the source-code version
  — double-clicking the exe again while it's running just opens another
  browser tab to the same running instance rather than a second app.
- **No system-tray/background mode.** The console window is the app's
  "on" switch; there's no minimize-to-tray yet. Fine for one person testing
  it; worth revisiting if this becomes the everyday way people run it.
- **Bundling LibreOffice makes for a much bigger download/copy.** If you
  don't have `.doc` (only `.docx`) files to worry about, skip installing
  LibreOffice on the build machine and keep the smaller build.
- **Rebuilding after code changes.** There's no auto-update — re-run
  `packaging\build_windows_exe.bat` after pulling new changes to get a
  fresh build.
