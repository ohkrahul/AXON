"""Text-mode AXON — type instead of talk.

This is the first testable milestone: it exercises the Claude brain, the PC
tools, and text-to-speech, WITHOUT needing a microphone, wake word, or the UI.
Once this works end to end, we bolt on ears (STT), the wake word, and the orb.

Run:  python main_text.py
"""
from __future__ import annotations

import asyncio

import config
import mouth
from brain import Brain


async def main() -> None:
    print(f"=== {config.ASSISTANT_NAME} (text mode) — model: {config.MODEL} ===")
    print("Type a message and press Enter. Type 'quit' to exit.\n")
    async with Brain() as brain:
        loop = asyncio.get_event_loop()
        while True:
            try:
                # run blocking input() off the event loop
                text = (await loop.run_in_executor(None, input, "You> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if text.lower() in {"quit", "exit", "bye", "goodbye"}:
                break
            if not text:
                continue
            try:
                reply = await brain.ask(text)
            except Exception as e:  # noqa: BLE001
                reply = f"Something went wrong talking to Claude: {e}"
            print(f"{config.ASSISTANT_NAME}> {reply}\n")
            mouth.speak(reply)
    print("Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
