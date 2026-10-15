"""Opening files whose path is longer than Windows will accept.

Windows limits a path to 260 characters unless the caller opts out, and a
real spec library goes past that without trying. One of the division's
libraries has paths like::

    C:\\Users\\157619\\Desktop\\Specs\\                                      (29)
      Edinburgh Flexible Plant Documentation - Customer Specifications\\    (64)
      Hearthside Food Solution (Previously Standard Candy Company)
          Master Specification\\                                            (81)
      48g. Matte OPP - 48g. MPET - 2.0 mil LLDPE\\                          (42)
      MI1119 - Hearthside Food Sol. (Stan. Candy) - W.W. 5.25
          x C.O. 5.75 - Rev 3.docx                                        (80)
                                                                     total 300

Each individual name is well inside the 255-character limit for a *name*.
It is the total that fails, and nobody looking at the file in Explorer can
see it.

The failure is silent and badly misleading. ``zipfile.is_zipfile`` catches
OSError and returns False, so python-docx reports a path it was never able
to open as ``PackageNotFoundError: Package not found at '<path>'`` -- which
reads as "this is not a Word file" when the truth is "Windows would not
open this path". Three specs in the division survey were diagnosed as
corrupt on that basis. They are fine; their folders are deep.

Prefixing an absolute path with ``\\\\?\\`` tells Windows to skip the limit.
It is exact rather than clever: no forward slashes, no ``.`` or ``..``, so
the path has to be normalised first. Everywhere else this is a no-op, and
the prefix is never stored -- it goes on at the point of the filesystem
call and the app keeps using ordinary paths as keys.
"""

from __future__ import annotations

import os
from pathlib import Path

# Windows' own limit, and the point past which a path needs the prefix.
MAX_PATH = 260

_PREFIX = "\\\\?\\"
_UNC_PREFIX = "\\\\?\\UNC\\"


def is_windows() -> bool:
    return os.name == "nt"


def long_path(path: str | os.PathLike[str]) -> str:
    """The form of ``path`` that Windows will open regardless of length.

    Returns the path unchanged on every other platform, and on Windows for
    anything already prefixed. Applied unconditionally rather than only to
    long paths: a path that is short today is long after someone renames a
    folder, and a prefix that is always present cannot be forgotten.
    """
    text = str(path)
    if not is_windows() or text.startswith(_PREFIX):
        return text

    absolute = os.path.abspath(text)
    if absolute.startswith("\\\\"):
        # A UNC path (\\server\share\...) takes a different prefix, and the
        # leading pair of slashes is replaced rather than kept.
        return _UNC_PREFIX + absolute[2:]
    return _PREFIX + absolute


def exceeds_max_path(path: str | os.PathLike[str]) -> bool:
    """Whether this path is past the limit Windows enforces by default.

    Reported on every platform, deliberately: a library is usually surveyed
    from one machine and opened on another, and a path that is too long on
    Windows is too long whoever is looking at it.
    """
    return len(str(path)) > MAX_PATH


def path_length(path: str | os.PathLike[str]) -> int:
    return len(str(path))


def open_path(path: str | os.PathLike[str]) -> Path:
    """A Path that can be opened, long or not."""
    return Path(long_path(path))
