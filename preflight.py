"""First-run helpers: is the Claude Code CLI installed and logged in?

AXON runs on your Claude *subscription* (Team/Pro) via Claude Code — no API key
needed. The only setup on a new PC is a one-time **browser login**. These helpers
let the app detect that and guide the user through it.
"""
from __future__ import annotations

import shutil
import subprocess


def cli_installed() -> bool:
    """True if the `claude` CLI is on PATH."""
    return shutil.which("claude") is not None


def is_logged_in(timeout: int = 30) -> bool:
    """True if Claude Code is signed in (a print-mode probe returns a reply)."""
    if not cli_installed():
        return False
    try:
        r = subprocess.run(
            ["cmd", "/c", "claude", "-p", "reply with the single word READY"],
            input="", capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return False


def launch_login() -> bool:
    """Open an interactive Claude window so the user can sign in (browser).

    A console window appears running `claude`; the user types /login and completes
    the browser sign-in with their Claude Team account.
    """
    try:
        subprocess.Popen(["cmd", "/c", "start",
                          "AXON - Sign in to Claude (type: /login)",
                          "cmd", "/k", "claude"])
        return True
    except Exception:  # noqa: BLE001
        return False
