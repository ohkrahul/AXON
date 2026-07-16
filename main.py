"""AXON — main launcher (GUI + Claude brain + PC control + voice output).

You type into the floating orb; Claude thinks, can act on your PC, and speaks
the reply aloud. Voice INPUT (a microphone) is optional and handled separately
(see voice_input.py) — this launcher works with no microphone at all.

Run:  python main.py
"""
from __future__ import annotations

import asyncio
import sys
import threading

import config
import mouth
import voice_input
from brain import Brain
from ui import Orb

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class AxonApp:
    def __init__(self) -> None:
        self.orb = Orb(on_submit=self._on_submit)
        self.loop = asyncio.new_event_loop()
        self.brain = Brain()
        self.voice: voice_input.VoiceSession | None = None
        self._stopping = False
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._voice_thread = threading.Thread(target=self._voice_boot, daemon=True)

    # ── worker thread: owns the async Claude conversation ────────────────
    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.brain.start())
        if config.SPEAK_GREETING:
            self.orb.set_reply(config.GREETING)
            self.orb.set_state("speaking")
            mouth.speak(config.GREETING)
            self.orb.set_state("idle")
        else:
            self.orb.set_reply("Online. Type a command below.")
        self.loop.run_forever()

    def _on_submit(self, text: str) -> None:
        asyncio.run_coroutine_threadsafe(self._handle(text), self.loop)

    # ── voice-input thread (only if a mic is available) ──────────────────
    def _voice_boot(self) -> None:
        if not config.ENABLE_VOICE_INPUT:
            return
        if not voice_input.mic_available():
            print("[voice] no usable microphone — running in text mode.")
            return
        print("[voice] microphone detected — 'Hey Axon' is live.")
        self.voice = voice_input.VoiceSession()
        while not self._stopping:
            self.orb.set_state("listening")
            cmd = self.voice.next_command()
            if self._stopping:
                break
            if cmd:
                fut = asyncio.run_coroutine_threadsafe(self._handle(cmd), self.loop)
                try:
                    fut.result()          # finish speaking before we listen again
                except Exception:  # noqa: BLE001
                    pass
            self.orb.set_state("idle")

    async def _handle(self, text: str) -> None:
        self.orb.set_user(text)
        self.orb.set_state("thinking")
        try:
            reply = await self.brain.ask(text)
        except Exception as e:  # noqa: BLE001
            self.orb.set_state("error")
            self.orb.set_reply(f"Error: {e}")
            return
        self.orb.set_reply(reply)
        self.orb.set_state("speaking")
        await self.loop.run_in_executor(None, mouth.speak, reply)
        self.orb.set_state("idle")

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        self._worker.start()
        self._voice_thread.start()
        self.orb.root.protocol("WM_DELETE_WINDOW", self._shutdown)
        self.orb.run()

    def _shutdown(self) -> None:
        self._stopping = True
        if self.voice is not None:
            self.voice.kill()
        try:
            asyncio.run_coroutine_threadsafe(self.brain.stop(), self.loop).result(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.orb.root.destroy()


if __name__ == "__main__":
    AxonApp().start()
