"""PyInstaller's entry script -- kept separate from specwrite/desktop.py
so the frozen build has a plain top-level script to point at, rather than
relying on `python -m` module invocation inside a frozen exe."""

import multiprocessing

from specwrite.desktop import main

if __name__ == "__main__":
    # Required before anything else runs in a frozen (PyInstaller) exe that
    # uses multiprocessing (vault.py parallelizes indexing a large vault
    # across worker processes) -- on Windows, each worker process
    # re-launches this same exe with special arguments to bootstrap itself;
    # without this call, that re-launch would just run the whole app again
    # (another server, another browser tab, recursively) instead of
    # becoming a worker. A no-op on platforms that don't need it.
    multiprocessing.freeze_support()
    main()
