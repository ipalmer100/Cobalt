# PyInstaller spec for the SpecWrite desktop app.
#
# Bundles the Python backend (FastAPI/uvicorn) together with the frontend's
# production build so the resulting exe is the whole app: no separate
# Python or Node.js install needed on the machine that runs it. Node is
# only needed at BUILD time (to produce frontend/dist), not at runtime --
# the backend serves those static files itself (see api.py's
# `_frontend_dist_dir`).
#
# Build from the repo root with:
#   pyinstaller packaging/specwrite.spec
# (see packaging/build_windows_exe.bat for the one-command wrapper, and
# packaging/README.md for full prerequisites)

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
    a.binaries,
    a.datas,
    [],
    name="SpecWrite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
