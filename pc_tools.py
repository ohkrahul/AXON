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
import os
import subprocess
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool, create_sdk_mcp_server

import config
import mouth

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


def _speak_safe(text: str) -> None:
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


# ── tools ────────────────────────────────────────────────────────────────
@tool("open_app", "Open an application or program on the PC by name, "
      "e.g. 'notepad', 'chrome', 'spotify', 'settings'.", {"name": str})
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


@tool("lock_pc", "Lock the Windows workstation (requires password to unlock).",
      {})
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


@tool("run_powershell", "Run an arbitrary PowerShell command and return its "
      "output. Use ONLY for things the other tools can't do.",
      {"command": str})
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
    (list_models, "list_models"), (set_model, "set_model"),
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
