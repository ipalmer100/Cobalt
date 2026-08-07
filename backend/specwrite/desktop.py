"""Entry point for the packaged desktop app (see packaging/specwrite.spec).

Runs the same FastAPI app as `uvicorn specwrite.api:app`, but as a
double-click .exe instead of a command someone types into a terminal:
starts the server, opens the default browser to it, and keeps a console
window open for as long as the app is running (closing that window, or
Ctrl+C, stops the server -- there is no separate background/tray mode).
"""

from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from .api import app
from .doc_conversion import soffice_path

HOST = "127.0.0.1"
PORT = 8765


def _port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _open_browser_when_ready() -> None:
    url = f"http://{HOST}:{PORT}/"
    for _ in range(50):  # ~10s of polling before giving up
        if _port_is_open(HOST, PORT):
            webbrowser.open(url)
            return
        time.sleep(0.2)
    print(f"Server didn't come up in time -- open {url} manually.")


def main() -> None:
    if _port_is_open(HOST, PORT):
        # Already running (e.g. the .exe was double-clicked a second time);
        # just focus the existing instance instead of failing to bind.
        webbrowser.open(f"http://{HOST}:{PORT}/")
        return

    print("Starting SpecWrite...")
    print(f"Opening http://{HOST}:{PORT}/ in your browser.")
    print("Keep this window open while you're using SpecWrite; closing it stops the app.\n")

    found_soffice = soffice_path()
    if found_soffice:
        print(f".doc conversion: available ({found_soffice})")
    else:
        print(".doc conversion: unavailable -- install LibreOffice to enable it.")
    print()
    # Frozen console apps (especially on Windows) can buffer stdout past
    # the point of usefulness once uvicorn.run() below blocks for the rest
    # of the app's life -- flush explicitly so all of the above is visible
    # immediately rather than whenever the OS pipe buffer happens to fill.
    sys.stdout.flush()
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
