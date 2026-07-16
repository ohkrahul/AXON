"""Floating 'orb' UI for AXON.

A small always-on-top window with a glowing circle that changes colour with
state (idle / listening / thinking / speaking), a transcript of the last
exchange, and a text box you can type into. Thread-safe: background workers
push updates through a queue that the Tk main loop drains via `after`.
"""
from __future__ import annotations

import queue
import tkinter as tk
from typing import Callable

import config

STATE_COLORS = {
    "idle":      ("#2b6cff", "Idle"),
    "listening": ("#28c76f", "Listening…"),
    "thinking":  ("#ffb020", "Thinking…"),
    "speaking":  ("#9b5cff", "Speaking…"),
    "error":     ("#ff5470", "Error"),
}


class Orb:
    def __init__(self, on_submit: Callable[[str], None] | None = None) -> None:
        self.on_submit = on_submit
        self._q: queue.Queue = queue.Queue()
        self._state = "idle"
        self._pulse = 0
        self._grow = True

        self.root = tk.Tk()
        self.root.title(config.ASSISTANT_NAME)
        self.root.configure(bg="#0d1117")
        self.root.geometry("380x300")
        self.root.attributes("-topmost", True)

        self.canvas = tk.Canvas(self.root, width=380, height=140,
                                bg="#0d1117", highlightthickness=0)
        self.canvas.pack(pady=(14, 4))

        self.state_lbl = tk.Label(self.root, text="Idle", fg="#8b949e",
                                  bg="#0d1117", font=("Segoe UI", 10))
        self.state_lbl.pack()

        self.you_lbl = tk.Label(self.root, text="", fg="#c9d1d9", bg="#0d1117",
                                wraplength=340, justify="left",
                                font=("Segoe UI", 9))
        self.you_lbl.pack(fill="x", padx=18, pady=(8, 0))

        self.reply_lbl = tk.Label(self.root, text=f"Type to talk to {config.ASSISTANT_NAME}.",
                                  fg="#58a6ff", bg="#0d1117", wraplength=340,
                                  justify="left", font=("Segoe UI", 10, "bold"))
        self.reply_lbl.pack(fill="x", padx=18, pady=(4, 8))

        entry_row = tk.Frame(self.root, bg="#0d1117")
        entry_row.pack(fill="x", padx=14, pady=(0, 12), side="bottom")
        self.entry = tk.Entry(entry_row, bg="#161b22", fg="#e6edf3",
                              insertbackground="#e6edf3", relief="flat",
                              font=("Segoe UI", 10))
        self.entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 6))
        self.entry.bind("<Return>", self._submit)
        tk.Button(entry_row, text="Send", command=self._submit, relief="flat",
                  bg="#238636", fg="white", font=("Segoe UI", 9, "bold"),
                  activebackground="#2ea043").pack(side="right")

        self._animate()
        self.root.after(60, self._drain)

    # ── public, thread-safe ──────────────────────────────────────────────
    def set_state(self, state: str) -> None:
        self._q.put(("state", state))

    def set_user(self, text: str) -> None:
        self._q.put(("user", text))

    def set_reply(self, text: str) -> None:
        self._q.put(("reply", text))

    def run(self) -> None:
        self.root.mainloop()

    # ── internals ────────────────────────────────────────────────────────
    def _submit(self, *_event) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        if self.on_submit:
            self.on_submit(text)

    def _drain(self) -> None:
        try:
            while True:
                kind, val = self._q.get_nowait()
                if kind == "state":
                    self._state = val
                    _, label = STATE_COLORS.get(val, STATE_COLORS["idle"])
                    self.state_lbl.config(text=label)
                elif kind == "user":
                    self.you_lbl.config(text=f"You:  {val}")
                elif kind == "reply":
                    self.reply_lbl.config(text=f"{config.ASSISTANT_NAME}:  {val}")
        except queue.Empty:
            pass
        self.root.after(60, self._drain)

    def _animate(self) -> None:
        color, _ = STATE_COLORS.get(self._state, STATE_COLORS["idle"])
        self._pulse += 1 if self._grow else -1
        if self._pulse >= 14:
            self._grow = False
        elif self._pulse <= 0:
            self._grow = True
        cx, cy = 190, 70
        base = 34
        r = base + self._pulse
        self.canvas.delete("all")
        # soft outer halo
        for i, alpha in enumerate((r + 22, r + 12, r)):
            shade = ("#1b2330", "#243044", color)[i]
            self.canvas.create_oval(cx - alpha, cy - alpha, cx + alpha, cy + alpha,
                                    fill=shade, outline="")
        self.canvas.create_text(cx, cy, text="J", fill="white",
                                font=("Segoe UI", 22, "bold"))
        self.root.after(45, self._animate)


if __name__ == "__main__":
    # Quick self-test: open, cycle states, auto-close.
    orb = Orb(on_submit=lambda t: print("submitted:", t))
    states = ["idle", "listening", "thinking", "speaking", "idle"]
    def cycle(i=0):
        orb.set_state(states[i % len(states)])
        orb.set_reply(f"demo state: {states[i % len(states)]}")
        if i < 8:
            orb.root.after(500, lambda: cycle(i + 1))
        else:
            orb.root.destroy()
    orb.root.after(300, cycle)
    orb.run()
    print("UI self-test OK")
