"""AXON web HUD backend.

Serves the sci-fi HUD (webui.html) and drives the same Claude brain + PC tools
+ text-to-speech used everywhere else. The browser polls /state and posts to
/say; all the thinking/speaking happens here in Python.

Run:  python server.py   (opens the HUD in an app window automatically)
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

import config
import graph as graph_mod
import indexer
import mouth
import preflight
import voice_input
from brain import Brain

HERE = Path(__file__).parent
HOST, PORT = "127.0.0.1", 8765

STATE = {
    "state": "idle",
    "model": config.MODEL,
    "mic": False,
    "history": [],          # [{role: 'user'|'axon', text: str}]
}
brain = Brain()
_START = time.time()

# auth / first-run state
AUTH = {"cli": True, "logged_in": False, "checked": False}
_brain_started = False
# The Claude SDK's subprocess connection must live in ONE long-lived task, so
# the brain is connected and driven entirely inside _brain_worker() below.
_brain_q: "asyncio.Queue[str]" = asyncio.Queue()
_login_ready = asyncio.Event()


def _add(role: str, text: str) -> None:
    STATE["history"].append({"role": role, "text": text, "t": int(time.time() - _START)})


async def _process(text: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    _add("user", text)
    STATE["state"] = "thinking"
    try:
        reply = await brain.ask(text)
    except Exception as e:  # noqa: BLE001
        STATE["state"] = "error"
        _add("axon", f"Error: {e}")
        STATE["state"] = "idle"
        return
    _add("axon", reply)
    STATE["state"] = "speaking"
    await asyncio.get_running_loop().run_in_executor(None, mouth.speak, reply)
    STATE["state"] = "idle"


async def _brain_worker() -> None:
    """One persistent task: connect after login, then serve every request."""
    global _brain_started
    await _login_ready.wait()
    try:
        await brain.start()
        _brain_started = True
    except Exception as e:  # noqa: BLE001
        print("[brain] failed to start:", e)
        return
    if config.SPEAK_GREETING:
        threading.Thread(target=_greet, daemon=True).start()
    while True:
        text = await _brain_q.get()
        try:
            await _process(text)
        except Exception as e:  # noqa: BLE001
            print("[brain] error:", e)
            STATE["state"] = "idle"


# ── routes ───────────────────────────────────────────────────────────────
async def index(request):
    return HTMLResponse((HERE / "webui.html").read_text(encoding="utf-8"))


async def state(request):
    ix = indexer.status()
    return JSONResponse({**STATE, "model": brain.model,
                         "index": {"state": ix.get("state"), "count": ix.get("count", 0)},
                         "auth": AUTH,
                         "uptime": int(time.time() - _START)})


async def signin(request):
    ok = preflight.launch_login()
    return JSONResponse({"ok": ok})


async def recheck(request):
    loop = asyncio.get_running_loop()
    AUTH["cli"] = preflight.cli_installed()
    AUTH["logged_in"] = await loop.run_in_executor(None, preflight.is_logged_in) if AUTH["cli"] else False
    AUTH["checked"] = True
    if AUTH["logged_in"]:
        _login_ready.set()
    return JSONResponse(AUTH)


async def graph(request):
    return JSONResponse(graph_mod.build_graph())


async def clear(request):
    STATE["history"].clear()
    return JSONResponse({"ok": True})


async def find(request):
    q = request.query_params.get("q", "")
    try:
        limit = int(request.query_params.get("limit", "25"))
    except ValueError:
        limit = 25
    return JSONResponse({"results": indexer.search(q, limit) if q.strip() else [],
                         "state": indexer.status().get("state")})


async def open_path_ep(request):
    data = await request.json()
    p = str(data.get("path") or "")
    ok = False
    try:
        if os.path.exists(p):
            os.startfile(p)  # type: ignore[attr-defined]
            ok = True
    except Exception:  # noqa: BLE001
        ok = False
    return JSONResponse({"ok": ok})


async def say(request):
    data = await request.json()
    text = (data.get("text") or "").strip()
    if text:
        _brain_q.put_nowait(text)      # handled by the persistent brain worker
    return JSONResponse({"ok": True})


# ── voice input (only if a mic exists) ───────────────────────────────────
def _voice_boot(loop: asyncio.AbstractEventLoop) -> None:
    if not config.ENABLE_VOICE_INPUT or not voice_input.mic_available():
        print("[voice] no microphone — type in the HUD instead.")
        return
    print("[voice] microphone detected — 'Hey Axon' is live.")
    STATE["mic"] = True
    session = voice_input.VoiceSession()
    while True:
        STATE["state"] = "listening"
        cmd = session.next_command()
        if cmd:
            loop.call_soon_threadsafe(_brain_q.put_nowait, cmd)
        STATE["state"] = "idle"


def _greet() -> None:
    _add("axon", config.GREETING)
    STATE["state"] = "speaking"
    mouth.speak(config.GREETING)
    STATE["state"] = "idle"


@asynccontextmanager
async def lifespan(app):
    loop = asyncio.get_running_loop()
    indexer.load_or_build()        # load cached PC catalog, or build in background
    asyncio.create_task(_brain_worker())   # persistent task owns the Claude connection

    def _auth_boot() -> None:       # check sign-in off the event loop
        AUTH["cli"] = preflight.cli_installed()
        AUTH["logged_in"] = preflight.is_logged_in() if AUTH["cli"] else False
        AUTH["checked"] = True
        if AUTH["logged_in"]:
            loop.call_soon_threadsafe(_login_ready.set)

    threading.Thread(target=_auth_boot, daemon=True).start()
    threading.Thread(target=_voice_boot, args=(loop,), daemon=True).start()
    yield
    await brain.stop()


app = Starlette(
    routes=[
        Route("/", index),
        Route("/state", state),
        Route("/graph", graph),
        Route("/say", say, methods=["POST"]),
        Route("/clear", clear, methods=["POST"]),
        Route("/find", find),
        Route("/open", open_path_ep, methods=["POST"]),
        Route("/signin", signin, methods=["POST"]),
        Route("/recheck", recheck, methods=["POST"]),
    ],
    middleware=[
        # allow the Next.js dev/prod server to call this API directly
        Middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"]),
    ],
    lifespan=lifespan,
)


# ── open the HUD in a frameless app window if we can ─────────────────────
def _open_window(url: str) -> None:
    edge = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for exe in edge:
        if os.path.exists(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=860,900"])
            return
    webbrowser.open(url)          # fallback: default browser


if __name__ == "__main__":
    # AXON_API_ONLY=1 runs as a pure API (used with the Next.js front-end),
    # so it won't pop the built-in HTML HUD.
    if os.environ.get("AXON_API_ONLY") != "1":
        threading.Timer(1.4, lambda: _open_window(f"http://{HOST}:{PORT}")).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
