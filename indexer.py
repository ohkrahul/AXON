"""Whole-PC file catalog — lets AXON find & know about any file on any drive.

Walks every fixed drive once (in a background thread), stores a lightweight
catalog of file paths + modified-times on disk, and answers substring
searches and "what changed recently" queries instantly across the entire PC.
No third-party dependencies.

The catalog is just paths + mtimes (not contents) — cheap to build and store.
To answer questions about a file's *content*, AXON reads it on demand
(pc_tools.read_file / search_file_contents).
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

_entries: list[tuple[str, float]] = []      # in-memory catalog: (full path, mtime)
_status = {"state": "idle", "count": 0, "drives": [], "finished": 0.0}


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


def _scan(root: str, found: list[tuple[str, float]]) -> None:
    """Iterative os.scandir walk — DirEntry.stat() is cheap on Windows (data
    comes from the same FindFirstFile call), so mtimes cost ~nothing extra."""
    stack = [root]
    while stack and len(found) < _MAX:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except (PermissionError, OSError):
            continue
        for e in entries:
            if len(found) >= _MAX:
                break
            nm = e.name
            if nm.startswith(".") or nm.lower() in _EXCLUDE or nm.startswith("$"):
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
                mtime = e.stat(follow_symlinks=False).st_mtime
            except OSError:
                continue
            found.append((e.path, mtime))
            if is_dir:
                stack.append(e.path)


def _build() -> None:
    global _entries
    _status.update(state="building", count=0)
    drives = fixed_drives()
    _status["drives"] = drives
    found: list[tuple[str, float]] = []
    try:
        for root in drives:
            _scan(root, found)
            _status["count"] = len(found)
            if len(found) >= _MAX:
                break
        _entries = found
        os.makedirs(_APPDIR, exist_ok=True)
        with open(_CATALOG, "w", encoding="utf-8") as f:
            json.dump({"entries": found, "built": time.time()}, f)
        _status.update(state="ready", count=len(found), finished=time.time())
    except Exception as e:  # noqa: BLE001
        _entries = found
        _status.update(state="partial", count=len(found), error=str(e))


def rebuild(background: bool = True) -> None:
    if background:
        threading.Thread(target=_build, daemon=True).start()
    else:
        _build()


def load_or_build() -> None:
    """Load the saved catalog if present; otherwise build it in the background."""
    global _entries
    if os.path.exists(_CATALOG):
        try:
            with open(_CATALOG, encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("entries")
            if raw is None:                 # older catalog format (paths only)
                raw = [[p, 0.0] for p in data.get("paths", [])]
            _entries = [(p, m) for p, m in raw]
            _status.update(state="ready", count=len(_entries))
            return
        except Exception:  # noqa: BLE001
            pass
    rebuild(background=True)


def ready() -> bool:
    return _status["state"] in ("ready", "partial") and bool(_entries)


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
    for p, _m in _entries:
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


def recent(hours: float = 24.0, limit: int = 50) -> list[tuple[str, float]]:
    """Files modified within the last `hours`, newest first."""
    cutoff = time.time() - hours * 3600
    hits = [(p, m) for p, m in _entries if m >= cutoff]
    hits.sort(key=lambda t: -t[1])
    return hits[:limit]


def all_paths() -> list[str]:
    """All catalogued paths (files + folders) — used by content search."""
    return [p for p, _m in _entries]
