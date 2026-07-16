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
import mouth
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
_busy = asyncio.Lock()


async def _handle(text: str) -> None:
    STATE["history"].append({"role": "user", "text": text})
    STATE["state"] = "thinking"
    try:
        reply = await brain.ask(text)
    except Exception as e:  # noqa: BLE001
        STATE["state"] = "error"
        STATE["history"].append({"role": "axon", "text": f"Error: {e}"})
        return
    STATE["history"].append({"role": "axon", "text": reply})
    STATE["state"] = "speaking"
    await asyncio.get_running_loop().run_in_executor(None, mouth.speak, reply)
    STATE["state"] = "idle"


async def _guarded(text: str) -> None:
    async with _busy:                 # one exchange at a time
        await _handle(text)


# ── routes ───────────────────────────────────────────────────────────────
async def index(request):
    return HTMLResponse((HERE / "webui.html").read_text(encoding="utf-8"))


async def state(request):
    return JSONResponse({**STATE, "model": brain.model})


async def graph(request):
    return JSONResponse(graph_mod.build_graph())


async def say(request):
    data = await request.json()
    text = (data.get("text") or "").strip()
    if text:
        asyncio.create_task(_guarded(text))
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
            fut = asyncio.run_coroutine_threadsafe(_guarded(cmd), loop)
            try:
                fut.result()
            except Exception:  # noqa: BLE001
                pass
        STATE["state"] = "idle"


def _greet() -> None:
    STATE["history"].append({"role": "axon", "text": config.GREETING})
    STATE["state"] = "speaking"
    mouth.speak(config.GREETING)
    STATE["state"] = "idle"


@asynccontextmanager
async def lifespan(app):
    await brain.start()
    if config.SPEAK_GREETING:
        threading.Thread(target=_greet, daemon=True).start()
    threading.Thread(target=_voice_boot, args=(asyncio.get_running_loop(),),
                     daemon=True).start()
    yield
    await brain.stop()


app = Starlette(
    routes=[
        Route("/", index),
        Route("/state", state),
        Route("/graph", graph),
        Route("/say", say, methods=["POST"]),
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
