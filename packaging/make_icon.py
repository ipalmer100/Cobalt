"""Regenerate packaging/cobalt.ico from frontend/public/cobalt-icon.svg.

The SVG is the single source of truth for the mark; Windows needs a real
.ico for the exe's taskbar/Explorer icon, so this bakes one out of it. The
committed .ico is what the build uses -- this script is only needed when
the mark itself changes, and it is deliberately NOT part of the Windows
build (it needs Chromium to rasterise, which a build machine won't have).

    python packaging/make_icon.py

Writes PNG-encoded ICO entries, which Windows has supported since Vista and
which keeps the file small compared with uncompressed BMP entries.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SVG = REPO_ROOT / "frontend" / "public" / "cobalt-icon.svg"
ICO = REPO_ROOT / "packaging" / "cobalt.ico"

# 16 for the title bar, 256 for large Explorer tiles, the rest for the
# sizes Windows actually picks between.
SIZES = [16, 24, 32, 48, 64, 128, 256]


def render_pngs(svg_text: str) -> dict[int, bytes]:
    from playwright.sync_api import sync_playwright

    out: dict[int, bytes] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        for size in SIZES:
            page = browser.new_page(viewport={"width": size, "height": size})
            # Transparent background: an icon sits on the taskbar, on a
            # folder background, on a dark theme -- a baked-in white square
            # would show as a card around the mark in all of them.
            page.set_content(
                "<style>html,body{margin:0;padding:0;background:transparent}"
                f"svg{{display:block;width:{size}px;height:{size}px}}</style>{svg_text}"
            )
            out[size] = page.screenshot(omit_background=True)
            page.close()
        browser.close()
    return out


def build_ico(pngs: dict[int, bytes]) -> bytes:
    entries = sorted(pngs.items())
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(header) + 16 * len(entries)
    directory, blobs = b"", b""
    for size, data in entries:
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,  # 0 means 256 in the ICO header
            0 if size >= 256 else size,
            0,  # palette size: 0 for a truecolour image
            0,  # reserved
            1,  # colour planes
            32,  # bits per pixel
            len(data),
            offset,
        )
        blobs += data
        offset += len(data)
    return header + directory + blobs


def main() -> int:
    if not SVG.is_file():
        print(f"missing {SVG}", file=sys.stderr)
        return 1
    ico = build_ico(render_pngs(SVG.read_text(encoding="utf-8")))
    ICO.write_bytes(ico)
    print(f"wrote {ICO} ({len(ico):,} bytes, sizes: {', '.join(map(str, SIZES))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
