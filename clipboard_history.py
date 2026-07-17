"""Rolling clipboard history — lets AXON recall what you copied recently.

A background thread polls the clipboard (Windows only needs win32clipboard,
already installed via pywin32) and keeps the last N distinct text entries in
memory. Nothing is persisted to disk — it's cleared when AXON restarts.
"""
from __future__ import annotations

import threading
import time

import win32clipboard

_MAX_ITEMS = 30
_POLL_SECONDS = 1.0

_history: list[dict] = []          # newest first: {"text": str, "t": float}
_lock = threading.Lock()
_last_seen: str | None = None


def _read_clipboard_text() -> str | None:
    try:
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            return None
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001
        return None


def _poll_loop() -> None:
    global _last_seen
    while True:
        text = _read_clipboard_text()
        if text and text.strip() and text != _last_seen:
            _last_seen = text
            with _lock:
                _history.insert(0, {"text": text, "t": time.time()})
                del _history[_MAX_ITEMS:]
        time.sleep(_POLL_SECONDS)


def start() -> None:
    threading.Thread(target=_poll_loop, daemon=True).start()


def history(limit: int = 10) -> list[dict]:
    with _lock:
        return list(_history[:limit])


def copy_text(text: str) -> bool:
    """Put `text` back on the clipboard (e.g. so the user can paste it)."""
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception:  # noqa: BLE001
        return False
