"""PyInstaller's entry script -- kept separate from specwrite/desktop.py
so the frozen build has a plain top-level script to point at, rather than
relying on `python -m` module invocation inside a frozen exe."""

from specwrite.desktop import main

if __name__ == "__main__":
    main()
