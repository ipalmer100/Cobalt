# Building the SpecWrite desktop app

Produces a folder that a non-technical user can double-click into to run
the whole app — no Python, no Node.js, no terminal, and (if you choose to
bundle it) no separately-installed LibreOffice either. Under the hood
it's the same FastAPI backend serving the same built frontend, bundled
with [PyInstaller](https://pyinstaller.org/); the browser is just how it
displays its UI, the same way many desktop apps embed a web view.

The output is a **folder**, not a single `.exe` file — `SpecWrite.exe`
plus its support files sit together in `packaging\dist\SpecWrite\`. This
is normal for apps this size (it's the same shape as a portable
7-Zip/VS Code install): copy or zip the *whole folder*, and
double-clicking the `.exe` inside it is still the entire "run it"
experience for whoever receives it.

This has to be **built on a Windows machine** — PyInstaller bundles a real
Windows binary and doesn't cross-compile from Linux/Mac. The steps below
are a one-time setup on whichever Windows machine does the building; the
resulting folder then runs on any similar Windows machine with no further
setup.

The packaging mechanics themselves (bundling the frontend build, the
backend's blank-spec template, and — see below — a full LibreOffice
install correctly into the frozen app; serving everything from one
process; the WebSocket live-sync) have been verified end-to-end via an
equivalent Linux build of this same spec file, including proving the
bundled LibreOffice copy is what actually gets used (by running the
frozen build with its PATH environment variable stripped, so nothing
else on the test machine could have been substituted in). Mechanically
this is expected to work; treat this doc as unverified only on the
*Windows-specific* details (the exe launching cleanly, Windows Defender /
SmartScreen's reaction to an unsigned exe, the real Windows `soffice.exe`
and its DLLs running correctly once bundled, and watchdog's Windows
filesystem-watching backend) since those can only be confirmed on real
Windows.

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
git clone https://github.com/ipalmer100/SpecWrite.git
cd SpecWrite
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
4. Runs PyInstaller against `packaging/specwrite.spec`, which bundles the
   backend, the built frontend, the blank "New Spec" template, and
   (if found) LibreOffice into one app folder.

Takes a few minutes (longer if bundling LibreOffice — it's copying a few
hundred MB). When it finishes: **`packaging\dist\SpecWrite\`** is the
whole app. Copy or zip that folder anywhere — a USB drive, another
machine, the desktop — and `SpecWrite.exe` inside it is the entire
"install."

## Running it

Double-click `SpecWrite.exe` (inside the `SpecWrite` folder — moving just
the exe out on its own won't work, it needs its sibling `_internal`
folder). A console window opens (this is intentional — it shows what the
app is doing, including whether `.doc` conversion is available and from
where, and is how you stop it later) and your default browser opens to
the app automatically. Point it at a folder of spec `.docx` files and
click "Open Vault", same as the source-code version. Closing the console
window (or Ctrl+C in it) stops the app; double-clicking the exe again
while it's already running just refocuses your browser instead of
erroring out.

## Bundling LibreOffice

`build_windows_exe.bat` automatically checks `%ProgramFiles%\LibreOffice`
and `%ProgramFiles(x86)%\LibreOffice` on the build machine. If it finds
LibreOffice there, it bundles the *entire* install (several hundred MB —
LibreOffice isn't small, and its `soffice.exe` needs its sibling `share\`
folder alongside it to run at all, not just the one exe) into
`SpecWrite\_internal\libreoffice\`. `.doc` conversion then works on any
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
