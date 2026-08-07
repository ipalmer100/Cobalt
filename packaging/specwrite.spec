# PyInstaller spec for the SpecWrite desktop app.
#
# Bundles the Python backend (FastAPI/uvicorn) together with the frontend's
# production build so the result is the whole app: no separate Python or
# Node.js install needed on the machine that runs it. Node is only needed
# at BUILD time (to produce frontend/dist), not at runtime -- the backend
# serves those static files itself (see api.py's `_frontend_dist_dir`).
#
# Produces a folder (PyInstaller "onedir" mode), not a single .exe: with
# LibreOffice optionally bundled (below) the payload can be several
# hundred MB, and onedir starts instantly since nothing needs extracting
# to a temp dir on every launch, unlike onefile. The folder itself -- copy
# or zip the whole thing -- *is* the "one app" a user runs; they still
# only ever double-click SpecWrite.exe inside it.
#
# Build from the repo root with:
#   pyinstaller packaging/specwrite.spec
# (see packaging/build_windows_exe.bat for the one-command wrapper, and
# packaging/README.md for full prerequisites)

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

repo_root = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is injected by PyInstaller)
backend_dir = repo_root / "backend"
frontend_dist = repo_root / "frontend" / "dist"
template_file = backend_dir / "specwrite" / "templates" / "blank_spec_template.docx"

if not frontend_dist.is_dir():
    raise SystemExit(
        "frontend/dist not found. Run `npm install && npm run build` inside "
        "frontend/ before building the exe -- see packaging/README.md."
    )
if not template_file.is_file():
    raise SystemExit(f"Expected bundled template at {template_file}, not found.")

# uvicorn and watchdog both pick their real implementation dynamically at
# runtime (uvicorn's protocol/loop backends, watchdog's per-OS filesystem
# observer), which PyInstaller's static import analysis can miss --
# collect every submodule of each defensively rather than hand-picking.
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("watchdog")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
    + ["websockets", "wsproto", "httptools", "h11", "anyio"]
)

datas = [
    (str(frontend_dist), "frontend_dist"),
    (str(template_file), "specwrite/templates"),
] + collect_data_files("docx")  # python-docx ships its own default.docx template

# Optional: bundle a full LibreOffice install so .doc conversion works with
# nothing else installed on the machine that runs the app. Set by
# build_windows_exe.bat when it finds LibreOffice already installed on the
# BUILD machine (LibreOffice itself is too large, and its official
# distribution mechanics too particular, to check into this repo or fetch
# automatically here) -- see doc_conversion.py's `_bundled_soffice_path`
# for where this ends up being looked for at runtime. Skipped entirely,
# with no error, if the env var isn't set: .doc conversion then falls back
# to whatever `soffice` it finds on PATH at runtime, exactly as before this
# bundling existed.
libreoffice_dir = os.environ.get("SPECWRITE_LIBREOFFICE_DIR")
if libreoffice_dir:
    lo_path = Path(libreoffice_dir)
    if not (lo_path / "program" / "soffice.exe").is_file():
        raise SystemExit(
            f"SPECWRITE_LIBREOFFICE_DIR={libreoffice_dir} doesn't look like a "
            "LibreOffice install (no program\\soffice.exe under it)."
        )
    datas.append((str(lo_path), "libreoffice"))

a = Analysis(
    [str(repo_root / "packaging" / "run_desktop.py")],
    pathex=[str(backend_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SpecWrite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SpecWrite",
)
