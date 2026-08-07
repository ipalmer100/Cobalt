# Building SpecWrite.exe (Windows desktop app)

Produces a single `SpecWrite.exe` that a non-technical user can double-click
to run the whole app — no Python, no Node.js, no terminal. Under the hood
it's the same FastAPI backend serving the same built frontend, bundled
into one binary with [PyInstaller](https://pyinstaller.org/); the browser
is just how it displays its UI, the same way many desktop apps embed a
web view.

This has to be **built on a Windows machine** — PyInstaller bundles a real
Windows binary and doesn't cross-compile from Linux/Mac. The steps below
are a one-time setup on whichever Windows machine does the building; the
resulting `SpecWrite.exe` then runs on any similar Windows machine with no
further setup.

The packaging mechanics themselves (bundling the frontend build and the
backend's blank-spec template correctly into the frozen binary, serving
both from one process, the WebSocket live-sync) have been verified
end-to-end via an equivalent Linux build of this same spec file — so
mechanically this is expected to work; treat this doc as unverified only
on the *Windows-specific* details (the exe launching cleanly, Windows
Defender / SmartScreen's reaction to an unsigned exe, and watchdog's
Windows filesystem-watching backend) since those can only be confirmed on
real Windows.

## One-time build machine setup

1. **Git** — https://git-scm.com/download/win
2. **Python 3.11+** — https://www.python.org/downloads/ (check "Add
   python.exe to PATH" during install)
3. **Node.js 20+** — https://nodejs.org/ (LTS)

## Build it

```
git clone https://github.com/ipalmer100/SpecWrite.git
cd SpecWrite
git checkout claude/toppan-spec-management-r7nmue
packaging\build_windows_exe.bat
```

The script:
1. `npm install` + `npm run build` in `frontend/` — produces `frontend/dist`.
2. Creates an isolated Python virtual environment at
   `packaging\.build-venv` and installs the backend plus PyInstaller into
   it (keeps this off your system Python entirely).
3. Runs PyInstaller against `packaging/specwrite.spec`, which bundles the
   backend, the built frontend, and the blank "New Spec" template into one
   binary.

Takes a few minutes. When it finishes: **`packaging\dist\SpecWrite.exe`**
is the whole app. Copy that one file anywhere — a USB drive, another
machine, the desktop — and double-clicking it is the entire "install."

## Running it

Double-click `SpecWrite.exe`. A console window opens (this is intentional —
it shows what the app is doing and is how you stop it later) and your
default browser opens to the app automatically. Point it at a folder of
spec `.docx` files and click "Open Vault", same as the source-code
version. Closing the console window (or Ctrl+C in it) stops the app;
double-clicking the exe again while it's already running just refocuses
your browser instead of erroring out.

## Known constraints of this v1 packaging

- **No LibreOffice bundled.** Converting legacy `.doc` files to `.docx`
  still needs LibreOffice installed separately on the machine *running*
  the exe, with `soffice` on PATH — it's a full office suite, too large to
  bundle into the exe itself. Everything else works with no other
  installs; this only matters if you have `.doc` (not `.docx`) files to
  convert.
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
- **Rebuilding after code changes.** There's no auto-update — re-run
  `packaging\build_windows_exe.bat` after pulling new changes to get a
  fresh `SpecWrite.exe`.
