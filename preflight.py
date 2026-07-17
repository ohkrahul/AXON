"""First-run helpers: is the Claude Code CLI installed and logged in?

AXON runs on your Claude *subscription* (Team/Pro) via Claude Code — no API key
needed. The only setup on a new PC is a one-time **browser login**. These helpers
let the app detect that and guide the user through it.

check_login() distinguishes "genuinely not signed in" from "signed in but the
probe failed for another reason" (slow/busy machine, network blip, a usage
limit) — a plain True/False here would misreport a usage-limit response as
"please sign in", which is confusing since re-logging in wouldn't fix that.
"""
from __future__ import annotations

import shutil
import subprocess

_LIMIT_HINTS = ("usage limit", "rate limit", "quota", "try again later",
                "too many requests", "429")
_AUTH_HINTS = ("not logged in", "please login", "please run", "/login",
               "authentication", "unauthorized", "please sign in")


def cli_installed() -> bool:
    """True if the `claude` CLI is on PATH."""
    return shutil.which("claude") is not None


def check_login(timeout: int = 45) -> dict:
    """Probe Claude Code with a real (tiny) print-mode call.

    Returns {"ok": bool, "reason": str, "detail": str} where `reason` is one
    of "ok", "not_logged_in", "rate_limited", "timeout", "error" — so the
    caller can tell a real login problem apart from "you're logged in but
    Claude just couldn't answer right now".
    """
    if not cli_installed():
        return {"ok": False, "reason": "no_cli", "detail": "Claude Code CLI not found on PATH."}
    try:
        r = subprocess.run(
            ["cmd", "/c", "claude", "-p", "reply with the single word READY"],
            input="", capture_output=True, text=True, timeout=timeout,
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        combined = f"{out}\n{err}".lower()

        if r.returncode == 0 and out:
            return {"ok": True, "reason": "ok", "detail": out}
        if any(h in combined for h in _LIMIT_HINTS):
            return {"ok": False, "reason": "rate_limited",
                   "detail": out or err or "Claude reported a usage/rate limit."}
        if any(h in combined for h in _AUTH_HINTS):
            return {"ok": False, "reason": "not_logged_in",
                   "detail": out or err or "Not signed in."}
        return {"ok": False, "reason": "error",
               "detail": (out or err or f"exit code {r.returncode}")[:300]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "timeout",
               "detail": f"Claude didn't respond within {timeout}s — the PC "
                         f"may be busy (e.g. still indexing files)."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "error", "detail": str(e)}


def is_logged_in(timeout: int = 45) -> bool:
    """Backward-compatible boolean wrapper around check_login()."""
    return check_login(timeout)["ok"]


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
