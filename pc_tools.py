"""PC-control tools that Claude can call by voice.

These are exposed to Claude as an in-process MCP server. Each is a small,
*curated* action — deliberately not a blank-cheque shell — so a misheard
command can't do real damage. A raw PowerShell escape hatch exists but is
disabled unless config.ALLOW_RAW_SHELL is on.

Everything here uses only the Python standard library plus Windows built-ins
(ctypes + PowerShell invoked by *our* trusted code), so there are no fragile
third-party wheels to install.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import win32con
import win32gui
from claude_agent_sdk import tool, create_sdk_mcp_server

import clipboard_history
import config
import indexer
import mouth

_APPDIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "axon"
_APPDIR.mkdir(parents=True, exist_ok=True)
_TODOS_FILE = _APPDIR / "todos.json"
_ROUTINES_FILE = _APPDIR / "routines.json"
_ACTIVITY_FILE = _APPDIR / "activity.json"


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def log_activity(tool_name: str, summary: str) -> None:
    entry = {"t": datetime.now().strftime("%I:%M %p"), "tool": tool_name, "summary": summary}
    items = _load_json(_ACTIVITY_FILE, [])
    items.insert(0, entry)
    del items[200:]
    _save_json(_ACTIVITY_FILE, items)


def _logged(name: str):
    """Decorator for tool handlers: records the call in the activity log.
    Goes between @tool(...) and the function so it wraps the raw handler
    before the SDK's tool() decorator turns it into an SdkMcpTool object."""
    import functools

    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(args):
            result = await fn(args)
            try:
                text = result["content"][0]["text"]
            except Exception:  # noqa: BLE001
                text = ""
            log_activity(name, text[:140])
            return result
        return wrapper
    return deco

user32 = ctypes.windll.user32

# Virtual-key codes for the multimedia keys (no dependencies needed).
VK = {
    "mute": 0xAD, "vol_down": 0xAE, "vol_up": 0xAF,
    "next": 0xB0, "prev": 0xB1, "stop": 0xB2, "playpause": 0xB3,
}
KEYEVENTF_KEYUP = 0x0002

# Friendly names -> what Windows should actually launch.
APP_ALIASES = {
    "browser": "https://www.google.com",
    "chrome": "chrome", "edge": "msedge", "firefox": "firefox",
    "notepad": "notepad", "calculator": "calc", "calc": "calc",
    "paint": "mspaint", "explorer": "explorer", "files": "explorer",
    "file explorer": "explorer", "settings": "ms-settings:",
    "task manager": "taskmgr", "cmd": "cmd", "terminal": "wt",
    "powershell": "powershell", "word": "winword", "excel": "excel",
    "spotify": "spotify", "vscode": "code", "vs code": "code", "code": "code",
}


# ── helpers ──────────────────────────────────────────────────────────────
def _ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _tap(vk: int, times: int = 1) -> None:
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def _run_ps(command: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=timeout,
    )


# ── SendInput plumbing (type unicode text into the focused window) ───────
_PUL = ctypes.POINTER(ctypes.c_ulong)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", _PUL)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", _PUL)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort),
                ("wParamH", ctypes.c_ushort)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTUNION)]


_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004


def _type_unicode(text: str) -> None:
    data = text.encode("utf-16-le")
    units = [data[i] | (data[i + 1] << 8) for i in range(0, len(data), 2)]
    for scan in units:
        for flags in (_KEYEVENTF_UNICODE, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP):
            ki = _KEYBDINPUT(0, scan, flags, 0, None)
            inp = _INPUT(1, _INPUTUNION(ki=ki))     # type 1 = keyboard
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


# ── volume via Core Audio (exact %) ─────────────────────────────────────
def _endpoint_volume():
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    devices = AudioUtilities.GetSpeakers()
    iface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


# ── timers / reminders ───────────────────────────────────────────────────
_timers: dict[int, threading.Timer] = {}
_timer_seq = [0]

# server.py registers a callback here so timer/reminder/routine alerts show up
# in the chat transcript (and can trigger a browser notification), not just
# speak silently in the background. Falls back to speaking only if unset
# (e.g. when running main.py / main_text.py without the web server).
ANNOUNCE: Any = None


def _speak_safe(text: str) -> None:
    if ANNOUNCE is not None:
        try:
            ANNOUNCE(text)
            return
        except Exception:  # noqa: BLE001
            pass
    try:
        mouth.speak(text)
    except Exception:  # noqa: BLE001
        print("[speak]", text)


def _fire_timer(tid: int, label: str) -> None:
    _timers.pop(tid, None)
    _speak_safe(f"Sir, your timer{(' for ' + label) if label else ''} is up.")


def _fire_reminder(message: str) -> None:
    _speak_safe(f"Reminder, sir: {message}")


def _human_duration(secs: int) -> str:
    m, s = divmod(secs, 60)
    parts = []
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s:
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " ".join(parts) or "0 seconds"


# ── file system access ───────────────────────────────────────────────────
_FS_SEARCH = str(Path(__file__).parent / "fs_search.ps1")
_KNOWN_FOLDERS = {
    "home": "~", "user": "~",
    "desktop": "~/Desktop",
    "documents": "~/Documents", "docs": "~/Documents",
    "downloads": "~/Downloads", "download": "~/Downloads",
    "pictures": "~/Pictures", "photos": "~/Pictures",
    "music": "~/Music", "videos": "~/Videos", "movies": "~/Videos",
    "appdata": os.environ.get("APPDATA", ""),
    "temp": os.environ.get("TEMP", ""),
}


def _resolve(name: str) -> str:
    key = name.strip().strip('"').lower()
    return os.path.expanduser(_KNOWN_FOLDERS.get(key, name.strip().strip('"')))


def _fallback_search(q: str, limit: int) -> list[str]:
    roots = [os.path.expanduser(p) for p in
             ("~/Desktop", "~/Documents", "~/Downloads", "~/Pictures")]
    ql, hits, scanned = q.lower(), [], 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, dns, fns in os.walk(root):
            scanned += 1
            for nm in dns + fns:
                if ql in nm.lower():
                    hits.append(os.path.join(dp, nm))
                    if len(hits) >= limit:
                        return hits
            if scanned > 3000:
                return hits
    return hits


# ── tools ────────────────────────────────────────────────────────────────
@tool("open_app", "Open an application or program on the PC by name, "
      "e.g. 'notepad', 'chrome', 'spotify', 'settings'.", {"name": str})
@_logged("open_app")
async def open_app(args: dict[str, Any]) -> dict[str, Any]:
    raw = str(args.get("name", "")).strip()
    target = APP_ALIASES.get(raw.lower(), raw)
    try:
        if target.startswith(("http://", "https://", "ms-settings:")):
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            # 'start' uses the shell's app resolution (Start Menu, PATH, etc.)
            subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
        return _ok(f"Opening {raw}.")
    except Exception as e:  # noqa: BLE001
        return _ok(f"I couldn't open {raw}: {e}")


@tool("open_url", "Open a web page in the default browser.", {"url": str})
async def open_url(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    os.startfile(url)  # type: ignore[attr-defined]
    return _ok(f"Opening {url}.")


@tool("web_search", "Search the web in the default browser for a query.",
      {"query": str})
async def web_search(args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("query", "")).strip()
    url = "https://www.google.com/search?q=" + urllib.parse.quote(q)
    os.startfile(url)  # type: ignore[attr-defined]
    return _ok(f"Searching the web for {q}.")


@tool("volume", "Control system volume. action is one of: 'up', 'down', "
      "'mute'. Optional 'steps' (default 5) sets how many notches for up/down.",
      {"action": str, "steps": int})
async def volume(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action", "")).strip().lower()
    steps = int(args.get("steps") or 5)
    if action == "up":
        _tap(VK["vol_up"], steps); return _ok("Turned the volume up.")
    if action == "down":
        _tap(VK["vol_down"], steps); return _ok("Turned the volume down.")
    if action in ("mute", "unmute", "toggle"):
        _tap(VK["mute"]); return _ok("Toggled mute.")
    return _ok("I can turn the volume up, down, or mute it.")


@tool("media", "Control media playback. action: 'playpause', 'next', "
      "'prev', or 'stop'.", {"action": str})
async def media(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action", "")).strip().lower()
    key = {"play": "playpause", "pause": "playpause", "playpause": "playpause",
           "next": "next", "skip": "next", "prev": "prev", "previous": "prev",
           "back": "prev", "stop": "stop"}.get(action)
    if not key:
        return _ok("I can play, pause, skip, or go back a track.")
    _tap(VK[key])
    return _ok(f"Done: {action}.")


@tool("take_screenshot", "Capture the screen and save it to the Pictures "
      "folder. Returns the saved file path.", {})
async def take_screenshot(args: dict[str, Any]) -> dict[str, Any]:
    pics = Path(os.path.expanduser("~")) / "Pictures"
    pics.mkdir(exist_ok=True)
    # Timestamp is fine here — this runs on the real machine, not the workflow VM.
    out = pics / f"axon_shot_{datetime.now():%Y%m%d_%H%M%S}.png"
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height);"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
        f"$bmp.Save('{out.as_posix()}');"
    )
    r = _run_ps(ps)
    if r.returncode == 0 and out.exists():
        return _ok(f"Screenshot saved to {out}.")
    return _ok(f"Screenshot failed: {r.stderr.strip() or 'unknown error'}")


_OCR_PS = str(Path(__file__).parent / "ocr.ps1")


def _run_ocr(image_path: str) -> str | None:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", _OCR_PS, "-ImagePath", image_path],
            capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


@tool("read_screen", "Take a screenshot and read the text on screen right now "
      "using OCR — use when the user asks what's on their screen, or to read "
      "an error message, window, or document that's currently visible.", {})
async def read_screen(args: dict[str, Any]) -> dict[str, Any]:
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height);"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
        f"$bmp.Save('{tmp}');"
    )
    try:
        r = _run_ps(ps)
        if r.returncode != 0:
            return _ok(f"Couldn't capture the screen: {r.stderr.strip()}")
        text = _run_ocr(tmp)
        if text is None:
            return _ok("OCR isn't available on this PC right now.")
        if not text.strip():
            return _ok("I captured the screen but didn't find any readable text on it.")
        return _ok(f"Text currently on screen:\n\n{text[:4000]}")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


@tool("ocr_image", "Read the text inside an image file using OCR. Give a "
      "full path (use find_files first if needed).", {"path": str})
async def ocr_image(args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(str(args.get("path", "")))
    if not os.path.isfile(path):
        return _ok(f"That's not a file I can read: {path}")
    text = _run_ocr(path)
    if text is None:
        return _ok("OCR isn't available on this PC right now.")
    if not text.strip():
        return _ok(f"No readable text found in {os.path.basename(path)}.")
    return _ok(f"Text in {os.path.basename(path)}:\n\n{text[:4000]}")


@tool("lock_pc", "Lock the Windows workstation (requires password to unlock).",
      {})
@_logged("lock_pc")
async def lock_pc(args: dict[str, Any]) -> dict[str, Any]:
    user32.LockWorkStation()
    return _ok("Locking the PC.")


@tool("system_status", "Get current time, date, and battery level.", {})
async def system_status(args: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now().strftime("%A %d %B %Y, %I:%M %p")

    class _PWR(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte),
                    ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte),
                    ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_ulong),
                    ("BatteryFullLifeTime", ctypes.c_ulong)]

    st = _PWR()
    batt = "unknown"
    if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        pct = st.BatteryLifePercent
        plugged = "charging" if st.ACLineStatus == 1 else "on battery"
        batt = f"{pct}% ({plugged})" if pct != 255 else "no battery detected"
    return _ok(f"It's {now}. Battery: {batt}.")


@tool("set_volume", "Set the system volume to an exact percentage (0-100).",
      {"percent": int})
async def set_volume(args: dict[str, Any]) -> dict[str, Any]:
    pct = max(0, min(100, int(args.get("percent") or 0)))
    try:
        _endpoint_volume().SetMasterVolumeLevelScalar(pct / 100.0, None)
        return _ok(f"Volume set to {pct} percent.")
    except Exception as e:  # noqa: BLE001
        return _ok(f"Couldn't set exact volume: {e}")


@tool("type_text", "Type text into whatever window currently has focus "
      "(click into a text field first).", {"text": str})
@_logged("type_text")
async def type_text(args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text", ""))
    if not text:
        return _ok("Nothing to type.")
    try:
        _type_unicode(text)
        return _ok("Typed it.")
    except Exception as e:  # noqa: BLE001
        return _ok(f"Couldn't type that: {e}")


@tool("set_timer", "Set a countdown timer that announces out loud when it ends. "
      "Give minutes and/or seconds, plus an optional label.",
      {"minutes": int, "seconds": int, "label": str})
async def set_timer(args: dict[str, Any]) -> dict[str, Any]:
    secs = int(args.get("minutes") or 0) * 60 + int(args.get("seconds") or 0)
    if secs <= 0:
        return _ok("Tell me how long — in minutes or seconds.")
    label = str(args.get("label") or "").strip()
    _timer_seq[0] += 1
    tid = _timer_seq[0]
    t = threading.Timer(secs, _fire_timer, args=(tid, label))
    t.daemon = True
    t.start()
    _timers[tid] = t
    return _ok(f"Timer set for {_human_duration(secs)}"
               f"{(' — ' + label) if label else ''}.")


@tool("set_reminder", "Remind the user of something after a delay; the reminder "
      "is spoken aloud. Give minutes and/or seconds and a message.",
      {"minutes": int, "seconds": int, "message": str})
async def set_reminder(args: dict[str, Any]) -> dict[str, Any]:
    secs = int(args.get("minutes") or 0) * 60 + int(args.get("seconds") or 0)
    message = str(args.get("message") or "").strip()
    if secs <= 0 or not message:
        return _ok("I need both a delay and a message.")
    t = threading.Timer(secs, _fire_reminder, args=(message,))
    t.daemon = True
    t.start()
    return _ok(f"I'll remind you in {_human_duration(secs)}.")


@tool("play_music", "Play or search for music on Spotify (falls back to the "
      "browser). With no query, toggle play/pause.", {"query": str})
async def play_music(args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("query", "")).strip()
    if not q:
        _tap(VK["playpause"])
        return _ok("Toggled playback.")
    quoted = urllib.parse.quote(q)
    try:
        os.startfile(f"spotify:search:{quoted}")  # type: ignore[attr-defined]
        return _ok(f"Searching Spotify for {q}.")
    except Exception:  # noqa: BLE001
        os.startfile(f"https://open.spotify.com/search/{quoted}")  # type: ignore[attr-defined]
        return _ok(f"Opening a Spotify web search for {q}.")


@tool("smart_home", "Trigger a configured smart-home action such as 'lights on'. "
      "Requires webhooks in config.SMART_HOME_WEBHOOKS.", {"action": str})
@_logged("smart_home")
async def smart_home(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action", "")).strip().lower()
    url = config.SMART_HOME_WEBHOOKS.get(action)
    if not url:
        have = ", ".join(config.SMART_HOME_WEBHOOKS) or "nothing yet"
        return _ok(f"I don't have a smart-home action called '{action}'. "
                   f"Configured actions: {have}.")
    try:
        urllib.request.urlopen(url, timeout=8)
        return _ok(f"Done — {action}.")
    except Exception as e:  # noqa: BLE001
        return _ok(f"Couldn't trigger {action}: {e}")


@tool("open_folder", "Open a folder in File Explorer. Accepts a known name "
      "(downloads, documents, desktop, pictures, music, videos, home) or a full "
      "path.", {"name": str})
async def open_folder(args: dict[str, Any]) -> dict[str, Any]:
    raw = str(args.get("name", "")).strip()
    path = _resolve(raw)
    if not os.path.isdir(path):
        return _ok(f"I couldn't find the folder '{raw}'. Try a full path or a "
                   f"name like Downloads.")
    os.startfile(path)  # type: ignore[attr-defined]
    return _ok(f"Opening {os.path.basename(path.rstrip(os.sep)) or path}.")


@tool("open_path", "Open any file or folder by full path — files open in their "
      "default app, folders open in Explorer.", {"path": str})
@_logged("open_path")
async def open_path(args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(str(args.get("path", "")))
    if not os.path.exists(path):
        return _ok(f"That path doesn't exist: {path}")
    os.startfile(path)  # type: ignore[attr-defined]
    return _ok(f"Opening {os.path.basename(path.rstrip(os.sep)) or path}.")


_TEXT_EXT = {".txt", ".md", ".markdown", ".py", ".js", ".ts", ".tsx", ".jsx",
             ".json", ".csv", ".log", ".html", ".htm", ".css", ".xml", ".yml",
             ".yaml", ".ini", ".cfg", ".conf", ".toml", ".bat", ".ps1", ".sh",
             ".sql", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".rb",
             ".php", ".env", ".gitignore", ".tsv", ".rtf"}
_DOC_EXT = {".pdf", ".docx"}


def _extract_doc_text(path: str, ext: str, max_chars: int) -> str | None:
    """Extract text from a PDF or Word doc. Returns None if the format isn't
    supported here or extraction fails (caller falls back gracefully)."""
    try:
        if ext == ".pdf":
            import pypdf
            reader = pypdf.PdfReader(path)
            parts = []
            total = 0
            for page in reader.pages:
                t = page.extract_text() or ""
                parts.append(t)
                total += len(t)
                if total >= max_chars:
                    break
            return "\n".join(parts)
        if ext == ".docx":
            import docx
            d = docx.Document(path)
            return "\n".join(p.text for p in d.paragraphs)
    except Exception:  # noqa: BLE001
        return None
    return None


@tool("find_files", "Search the WHOLE PC (every drive, anywhere) for files or "
      "folders by name. Returns matching full paths.", {"query": str, "limit": int})
async def find_files(args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("query", "")).strip()
    limit = int(args.get("limit") or 12)
    if not q:
        return _ok("What should I search for?")
    paths: list[str] = []
    if indexer.ready():                       # full-PC catalog (all drives)
        paths = indexer.search(q, limit)
    if not paths:                             # fall back while catalog builds
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", _FS_SEARCH, "-Query", q, "-Limit", str(limit)],
                capture_output=True, text=True, timeout=45)
            paths = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
        except Exception:  # noqa: BLE001
            pass
    if not paths:
        paths = _fallback_search(q, limit)
    if not paths:
        st = indexer.status()
        extra = (f" I'm still indexing the PC ({st['count']:,} files so far)."
                 if st["state"] == "building" else "")
        return _ok(f"I couldn't find anything matching '{q}'.{extra}")
    return _ok(f"Found {len(paths)} match(es) for '{q}':\n" + "\n".join(paths[:limit]))


@tool("read_file", "Read the contents of a file so you can answer about it — "
      "supports plain text files, PDFs, and Word (.docx) documents. Give a "
      "full path (use find_files first if needed).",
      {"path": str, "max_chars": int})
async def read_file(args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(str(args.get("path", "")))
    if not os.path.isfile(path):
        return _ok(f"That's not a file I can read: {path}")
    mx = int(args.get("max_chars") or 6000)
    ext = os.path.splitext(path)[1].lower()
    try:
        size = os.path.getsize(path)
        if ext in _DOC_EXT:
            text = _extract_doc_text(path, ext, mx)
            if text is None:
                return _ok(f"I couldn't extract text from {os.path.basename(path)}.")
            if not text.strip():
                return _ok(f"{os.path.basename(path)} has no extractable text "
                           f"(likely a scanned/image-based document).")
            more = " …(truncated)" if len(text) > mx else ""
            return _ok(f"{os.path.basename(path)} ({size:,} bytes):\n\n{text[:mx]}{more}")
        if ext not in _TEXT_EXT:
            return _ok(f"'{os.path.basename(path)}' is a {ext or 'binary'} file "
                       f"({size:,} bytes); I can only read text, PDF, and Word files.")
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read(mx + 1)
        more = " …(truncated)" if len(content) > mx else ""
        return _ok(f"{os.path.basename(path)} ({size:,} bytes):\n\n{content[:mx]}{more}")
    except Exception as e:  # noqa: BLE001
        return _ok(f"I couldn't read {path}: {e}")


@tool("search_file_contents", "Search INSIDE text files across the PC for a "
      "phrase (not just filenames) — e.g. find a document that mentions a "
      "specific term. Scans a bounded sample of indexed text files for speed.",
      {"query": str, "limit": int})
async def search_file_contents(args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("query", "")).strip().lower()
    limit = int(args.get("limit") or 8)
    if not q:
        return _ok("What phrase should I search for inside your files?")
    hits: list[str] = []
    scanned = 0
    candidates = indexer.all_paths() if indexer.ready() else []
    for p in candidates:
        ext = os.path.splitext(p)[1].lower()
        if ext not in _TEXT_EXT:
            continue
        if scanned >= 4000 or len(hits) >= limit:
            break
        scanned += 1
        try:
            if os.path.getsize(p) > 2_000_000:      # skip huge logs etc.
                continue
            with open(p, encoding="utf-8", errors="ignore") as f:
                text = f.read(200_000)
            idx = text.lower().find(q)
            if idx != -1:
                snippet = text[max(0, idx - 40):idx + 80].replace("\n", " ")
                hits.append(f"{p}\n    …{snippet}…")
        except OSError:
            continue
    if not hits:
        return _ok(f"Scanned {scanned} text files but found no mention of '{q}'.")
    return _ok(f"Found '{q}' in {len(hits)} file(s):\n" + "\n".join(hits))


@tool("recent_changes", "List files that were created or modified recently on "
      "the PC — a 'what changed today' digest.",
      {"hours": int, "limit": int})
async def recent_changes(args: dict[str, Any]) -> dict[str, Any]:
    hours = float(args.get("hours") or 24)
    limit = int(args.get("limit") or 20)
    if not indexer.ready():
        return _ok("The file index isn't ready yet — try again shortly.")
    items = indexer.recent(hours=hours, limit=limit)
    if not items:
        return _ok(f"Nothing changed in the last {hours:g} hours.")
    lines = [f"{Path(p).name}  ({datetime.fromtimestamp(m):%b %d, %I:%M %p})"
             for p, m in items]
    return _ok(f"{len(items)} item(s) changed in the last {hours:g} hours:\n" + "\n".join(lines))


@tool("pc_index_status", "Report how much of the PC file catalog has been built.", {})
async def pc_index_status(args: dict[str, Any]) -> dict[str, Any]:
    st = indexer.status()
    drives = ", ".join(st.get("drives") or []) or "detecting"
    return _ok(f"File index: {st['state']}, {st['count']:,} files catalogued "
               f"across {drives}.")


@tool("reindex_pc", "Rebuild the whole-PC file catalog from scratch (runs in the "
      "background).", {})
@_logged("reindex_pc")
async def reindex_pc(args: dict[str, Any]) -> dict[str, Any]:
    indexer.rebuild(background=True)
    return _ok("Re-scanning every drive now; it'll be ready shortly.")


@tool("list_directory", "List what's inside a folder (known name or full path).",
      {"path": str})
async def list_directory(args: dict[str, Any]) -> dict[str, Any]:
    raw = str(args.get("path", "")).strip()
    path = _resolve(raw)
    if not os.path.isdir(path):
        return _ok(f"'{raw}' isn't a folder I can open.")
    try:
        entries = sorted(os.listdir(path))
    except Exception as e:  # noqa: BLE001
        return _ok(f"I can't read {path}: {e}")
    dirs = [e for e in entries if os.path.isdir(os.path.join(path, e))]
    files = [e for e in entries if e not in dirs]
    names = ", ".join((dirs + files)[:40]) or "nothing"
    return _ok(f"{path} has {len(dirs)} folders and {len(files)} files: {names}.")


@tool("list_models", "List the AI models AXON can run on and say which is "
      "active. Use when the user asks what models are available.", {})
async def list_models(args: dict[str, Any]) -> dict[str, Any]:
    import brain
    cur = getattr(brain.ACTIVE_BRAIN, "model", config.MODEL)
    parts = []
    for _alias, (mid, desc) in config.AVAILABLE_MODELS.items():
        parts.append(desc + (" — currently active" if mid == cur else ""))
    return _ok("I can run on: " + "; ".join(parts) + ".")


@tool("set_model", "Switch AXON to a different AI model. Accepts a short name "
      "like 'opus', 'sonnet', 'haiku' or 'fable'. Applies on the next reply.",
      {"model": str})
@_logged("set_model")
async def set_model(args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("model", "")).strip().lower()
    target = None
    for alias, (mid, desc) in config.AVAILABLE_MODELS.items():
        if q == alias or q == mid.lower() or alias in q or q in mid.lower():
            target = (mid, desc)
            break
    if target is None:
        return _ok(f"I don't have a model called '{q}'. I can switch to: "
                   + ", ".join(config.AVAILABLE_MODELS) + ".")
    import brain
    if brain.ACTIVE_BRAIN is not None:
        brain.ACTIVE_BRAIN.request_model(target[0])
    name = target[1].split(" — ")[0]
    return _ok(f"Switching to {name} on my next reply.")


# ── window management ────────────────────────────────────────────────────
def _enum_windows() -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title.strip():
                out.append((hwnd, title))
        return True

    win32gui.EnumWindows(cb, None)
    return out


def _find_window(name: str) -> tuple[int, str] | None:
    name = name.lower().strip()
    for hwnd, title in _enum_windows():
        if name in title.lower():
            return hwnd, title
    return None


@tool("list_windows", "List the titles of all currently open windows.", {})
async def list_windows(args: dict[str, Any]) -> dict[str, Any]:
    titles = [t for _h, t in _enum_windows()]
    if not titles:
        return _ok("No visible windows found.")
    return _ok(f"{len(titles)} open window(s):\n" + "\n".join(titles[:30]))


@tool("focus_window", "Bring a window to the front by (part of) its title.",
      {"name": str})
@_logged("focus_window")
async def focus_window(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name", "")).strip()
    hit = _find_window(name)
    if not hit:
        return _ok(f"I couldn't find a window matching '{name}'.")
    hwnd, title = hit
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return _ok(f"Switched to {title}.")
    except Exception as e:  # noqa: BLE001
        return _ok(f"Couldn't switch to {title}: {e}")


@tool("snap_window", "Arrange a window by (part of) its title. action: "
      "'maximize', 'minimize', 'restore', 'left' (snap left half), or "
      "'right' (snap right half).", {"name": str, "action": str})
@_logged("snap_window")
async def snap_window(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name", "")).strip()
    action = str(args.get("action", "")).strip().lower()
    hit = _find_window(name)
    if not hit:
        return _ok(f"I couldn't find a window matching '{name}'.")
    hwnd, title = hit
    try:
        if action == "maximize":
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        elif action == "minimize":
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        elif action == "restore":
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        elif action in ("left", "right"):
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            x = 0 if action == "left" else sw // 2
            win32gui.SetWindowPos(hwnd, 0, x, 0, sw // 2, sh, win32con.SWP_NOZORDER)
        else:
            return _ok("I can maximize, minimize, restore, or snap a window left/right.")
        return _ok(f"{action.capitalize()}d {title}.")
    except Exception as e:  # noqa: BLE001
        return _ok(f"Couldn't arrange {title}: {e}")


# ── clipboard history ────────────────────────────────────────────────────
@tool("clipboard_history", "Show recently copied clipboard text entries.",
      {"limit": int})
async def clipboard_history_tool(args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit") or 10)
    items = clipboard_history.history(limit)
    if not items:
        return _ok("No clipboard history yet.")
    lines = [f"{i + 1}. {it['text'][:90]}" for i, it in enumerate(items)]
    return _ok(f"Recent clipboard items:\n" + "\n".join(lines))


@tool("copy_to_clipboard", "Copy specific text back onto the clipboard "
      "(e.g. to restore an earlier clipboard item) so the user can paste it.",
      {"text": str})
@_logged("copy_to_clipboard")
async def copy_to_clipboard(args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text", ""))
    if not text:
        return _ok("What text should I copy?")
    ok = clipboard_history.copy_text(text)
    return _ok("Copied to clipboard — press Ctrl+V to paste it." if ok
               else "Couldn't access the clipboard.")


# ── to-do list ───────────────────────────────────────────────────────────
@tool("add_todo", "Add an item to the user's to-do list.", {"text": str})
async def add_todo(args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text", "")).strip()
    if not text:
        return _ok("What should I add to the to-do list?")
    items = _load_json(_TODOS_FILE, [])
    nid = (max((i["id"] for i in items), default=0)) + 1
    items.append({"id": nid, "text": text, "done": False,
                 "created": datetime.now().strftime("%b %d, %I:%M %p")})
    _save_json(_TODOS_FILE, items)
    return _ok(f"Added to your to-do list: {text}")


@tool("list_todos", "List the user's to-do items (pending and/or done).",
      {"include_done": bool})
async def list_todos(args: dict[str, Any]) -> dict[str, Any]:
    items = _load_json(_TODOS_FILE, [])
    include_done = bool(args.get("include_done"))
    shown = items if include_done else [i for i in items if not i["done"]]
    if not shown:
        return _ok("Your to-do list is empty.")
    lines = [f"{'[x]' if i['done'] else '[ ]'} #{i['id']} {i['text']}" for i in shown]
    return _ok(f"{len(shown)} item(s):\n" + "\n".join(lines))


@tool("complete_todo", "Mark a to-do item done by its id or matching text.",
      {"item": str})
async def complete_todo(args: dict[str, Any]) -> dict[str, Any]:
    item = str(args.get("item", "")).strip().lower()
    items = _load_json(_TODOS_FILE, [])
    for i in items:
        if str(i["id"]) == item or item in i["text"].lower():
            i["done"] = True
            _save_json(_TODOS_FILE, items)
            return _ok(f"Marked done: {i['text']}")
    return _ok(f"I couldn't find a to-do matching '{item}'.")


@tool("remove_todo", "Delete a to-do item by its id or matching text.",
      {"item": str})
async def remove_todo(args: dict[str, Any]) -> dict[str, Any]:
    item = str(args.get("item", "")).strip().lower()
    items = _load_json(_TODOS_FILE, [])
    kept = [i for i in items if not (str(i["id"]) == item or item in i["text"].lower())]
    if len(kept) == len(items):
        return _ok(f"I couldn't find a to-do matching '{item}'.")
    _save_json(_TODOS_FILE, kept)
    return _ok("Removed.")


# ── scheduled routines (checked by server.py's background thread) ────────
def get_routines() -> list[dict]:
    """Used by server.py's scheduler thread to check due routines."""
    return _load_json(_ROUTINES_FILE, [])


def mark_routine_ran(rid: int, date_str: str) -> None:
    routines = _load_json(_ROUTINES_FILE, [])
    for r in routines:
        if r["id"] == rid:
            r["last_run"] = date_str
    _save_json(_ROUTINES_FILE, routines)


@tool("add_routine", "Schedule a recurring daily instruction for AXON to run "
      "on its own, e.g. 'summarize new files' every day at a given time.",
      {"time": str, "instruction": str})
@_logged("add_routine")
async def add_routine(args: dict[str, Any]) -> dict[str, Any]:
    t = str(args.get("time", "")).strip()
    instruction = str(args.get("instruction", "")).strip()
    if not t or not instruction:
        return _ok("I need both a daily time (e.g. '09:00') and what to do.")
    try:
        hh, mm = [int(x) for x in t.replace(".", ":").split(":")]
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:  # noqa: BLE001
        return _ok("Give the time as HH:MM, e.g. 09:00 or 18:30.")
    routines = _load_json(_ROUTINES_FILE, [])
    nid = (max((r["id"] for r in routines), default=0)) + 1
    routines.append({"id": nid, "time": f"{hh:02d}:{mm:02d}",
                     "instruction": instruction, "last_run": ""})
    _save_json(_ROUTINES_FILE, routines)
    return _ok(f"Scheduled daily at {hh:02d}:{mm:02d}: {instruction}")


@tool("list_routines", "List AXON's scheduled daily routines.", {})
async def list_routines(args: dict[str, Any]) -> dict[str, Any]:
    routines = _load_json(_ROUTINES_FILE, [])
    if not routines:
        return _ok("No scheduled routines yet.")
    lines = [f"#{r['id']} {r['time']} — {r['instruction']}" for r in routines]
    return _ok(f"{len(routines)} routine(s):\n" + "\n".join(lines))


@tool("remove_routine", "Delete a scheduled routine by its id.", {"id": int})
async def remove_routine(args: dict[str, Any]) -> dict[str, Any]:
    rid = int(args.get("id") or -1)
    routines = _load_json(_ROUTINES_FILE, [])
    kept = [r for r in routines if r["id"] != rid]
    if len(kept) == len(routines):
        return _ok(f"No routine with id {rid}.")
    _save_json(_ROUTINES_FILE, kept)
    return _ok("Removed.")


# ── activity log ─────────────────────────────────────────────────────────
@tool("activity_log", "Show a log of recent actions AXON has taken on this PC.",
      {"limit": int})
async def activity_log(args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit") or 15)
    items = _load_json(_ACTIVITY_FILE, [])[:limit]
    if not items:
        return _ok("No recorded activity yet.")
    lines = [f"{it['t']} — {it['summary']}" for it in items]
    return _ok(f"Recent activity:\n" + "\n".join(lines))


@tool("run_powershell", "Run an arbitrary PowerShell command and return its "
      "output. Use ONLY for things the other tools can't do.",
      {"command": str})
@_logged("run_powershell")
async def run_powershell(args: dict[str, Any]) -> dict[str, Any]:
    cmd = str(args.get("command", ""))
    try:
        r = _run_ps(cmd, timeout=60)
        out = (r.stdout or "").strip() or (r.stderr or "").strip() or "(no output)"
        return _ok(out[:1500])
    except Exception as e:  # noqa: BLE001
        return _ok(f"Command failed: {e}")


# ── server wiring ────────────────────────────────────────────────────────
# (tool object, registered name) — name kept explicit so we don't depend on
# an internal attribute of the decorated object.
_SAFE_TOOLS = [
    (open_app, "open_app"), (open_url, "open_url"), (web_search, "web_search"),
    (volume, "volume"), (set_volume, "set_volume"), (media, "media"),
    (take_screenshot, "take_screenshot"), (lock_pc, "lock_pc"),
    (system_status, "system_status"), (type_text, "type_text"),
    (set_timer, "set_timer"), (set_reminder, "set_reminder"),
    (play_music, "play_music"), (smart_home, "smart_home"),
    (open_folder, "open_folder"), (open_path, "open_path"),
    (find_files, "find_files"), (list_directory, "list_directory"),
    (read_file, "read_file"), (pc_index_status, "pc_index_status"),
    (reindex_pc, "reindex_pc"),
    (list_models, "list_models"), (set_model, "set_model"),
    # content / recency
    (search_file_contents, "search_file_contents"),
    (recent_changes, "recent_changes"),
    # screen / images
    (read_screen, "read_screen"), (ocr_image, "ocr_image"),
    # windows
    (list_windows, "list_windows"), (focus_window, "focus_window"),
    (snap_window, "snap_window"),
    # clipboard
    (clipboard_history_tool, "clipboard_history"),
    (copy_to_clipboard, "copy_to_clipboard"),
    # to-do list
    (add_todo, "add_todo"), (list_todos, "list_todos"),
    (complete_todo, "complete_todo"), (remove_todo, "remove_todo"),
    # scheduled routines
    (add_routine, "add_routine"), (list_routines, "list_routines"),
    (remove_routine, "remove_routine"),
    # activity log
    (activity_log, "activity_log"),
]
if config.ALLOW_RAW_SHELL:
    _SAFE_TOOLS.append((run_powershell, "run_powershell"))

SERVER_NAME = "pc"
PC_SERVER = create_sdk_mcp_server(
    name=SERVER_NAME, version="1.0.0",
    tools=[t for t, _ in _SAFE_TOOLS],
)

# Fully-qualified tool names Claude is allowed to call without a prompt.
ALLOWED_TOOL_NAMES = [f"mcp__{SERVER_NAME}__{name}" for _, name in _SAFE_TOOLS]
