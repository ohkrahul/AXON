"""Whole-PC file catalog — lets AXON find & know about any file on any drive.

Walks every fixed drive once (in a background thread), stores a lightweight
catalog of file paths on disk, and answers substring searches instantly across
the entire PC. No third-party dependencies.

The catalog is just paths (not contents) — cheap to build and store. To answer
questions about a file's *content*, AXON reads it on demand (pc_tools.read_file).
"""
from __future__ import annotations

import ctypes
import json
import os
import string
import threading
import time

_APPDIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "axon")
_CATALOG = os.path.join(_APPDIR, "catalog.json")
_MAX = int(os.environ.get("AXON_INDEX_MAX", "800000"))   # cap entries for memory

# Directories we never descend into (system noise / dev clutter / loops).
_EXCLUDE = {
    "$recycle.bin", "system volume information", "windows", "recovery",
    "perflogs", "node_modules", ".git", ".venv", "__pycache__",
    "$windows.~ws", "$windows.~bt", ".cache", "site-packages",
}

_paths: list[str] = []                      # in-memory catalog (full paths)
_status = {"state": "idle", "count": 0, "drives": [], "finished": 0.0}
_lock = threading.Lock()


def fixed_drives() -> list[str]:
    """Return roots of all FIXED disks, e.g. ['C:\\\\', 'D:\\\\']."""
    k = ctypes.windll.kernel32
    mask = k.GetLogicalDrives()
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            root = f"{letter}:\\"
            if k.GetDriveTypeW(ctypes.c_wchar_p(root)) == 3:   # DRIVE_FIXED
                out.append(root)
    return out


def _build() -> None:
    global _paths
    _status.update(state="building", count=0)
    drives = fixed_drives()
    _status["drives"] = drives
    found: list[str] = []
    try:
        for root in drives:
            for dp, dns, fns in os.walk(root, topdown=True, followlinks=False):
                dns[:] = [d for d in dns
                          if d.lower() not in _EXCLUDE and not d.startswith("$")]
                for d in dns:                       # folders are searchable too
                    found.append(os.path.join(dp, d))
                for fn in fns:                      # and files
                    found.append(os.path.join(dp, fn))
                _status["count"] = len(found)
                if len(found) >= _MAX:
                    break
            if len(found) >= _MAX:
                break
        _paths = found
        os.makedirs(_APPDIR, exist_ok=True)
        with open(_CATALOG, "w", encoding="utf-8") as f:
            json.dump({"paths": found, "built": time.time()}, f)
        _status.update(state="ready", count=len(found), finished=time.time())
    except Exception as e:  # noqa: BLE001
        _paths = found
        _status.update(state="partial", count=len(found), error=str(e))


def rebuild(background: bool = True) -> None:
    if background:
        threading.Thread(target=_build, daemon=True).start()
    else:
        _build()


def load_or_build() -> None:
    """Load the saved catalog if present; otherwise build it in the background."""
    global _paths
    if os.path.exists(_CATALOG):
        try:
            with open(_CATALOG, encoding="utf-8") as f:
                _paths = json.load(f)["paths"]
            _status.update(state="ready", count=len(_paths))
            return
        except Exception:  # noqa: BLE001
            pass
    rebuild(background=True)


def ready() -> bool:
    return _status["state"] in ("ready", "partial") and bool(_paths)


def status() -> dict:
    return dict(_status)


def search(query: str, limit: int = 15) -> list[str]:
    """Ranked case-insensitive search: name matches beat path matches, and
    exact/prefix name matches rank highest (so 'e20' finds the e20 folder, not
    random files whose path happens to contain 'e20')."""
    q = query.strip().lower()
    if not q:
        return []
    scored: list[tuple[int, int, str]] = []
    seen = 0
    for p in _paths:
        pl = p.lower()
        if q not in pl:
            continue
        name = pl[pl.rfind("\\") + 1:]
        if q in name:
            score = 0 if name == q else 1 if name.startswith(q) else 2
        else:
            score = 5                     # matched only deeper in the path
        scored.append((score, len(p), p))
        seen += 1
        if seen >= 4000:                  # cap work for very common substrings
            break
    scored.sort(key=lambda t: (t[0], t[1]))
    return [p for _, _, p in scored[:limit]]
