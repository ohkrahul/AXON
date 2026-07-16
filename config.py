"""Central configuration for AXON.

Everything tweakable lives here so you don't have to hunt through the code.
"""
import os

# ── Identity ─────────────────────────────────────────────────────────────
ASSISTANT_NAME = "Axon"
WAKE_WORD = "axon"  # what you say to activate it

# ── Claude brain ─────────────────────────────────────────────────────────
# Model to think with. Options: claude-fable-5 (fast, matches the video),
# claude-haiku-4-5-20251001 (fast+cheap), claude-sonnet-5, claude-opus-4-8.
MODEL = os.environ.get("AXON_MODEL", "claude-fable-5")

# Models AXON can switch between at runtime — alias -> (model id, description).
# The user can say "switch to opus" or "what models do you have".
AVAILABLE_MODELS: dict[str, tuple[str, str]] = {
    "fable":  ("claude-fable-5",            "Fable 5 — fast, great for quick conversation (default)"),
    "opus":   ("claude-opus-4-8",           "Opus 4.8 — most capable, best for hard reasoning"),
    "sonnet": ("claude-sonnet-5",           "Sonnet 5 — balanced capability and speed"),
    "haiku":  ("claude-haiku-4-5-20251001", "Haiku 4.5 — fastest and lightest"),
}

# Personality / behaviour. Kept short on purpose: replies are spoken aloud,
# so we want them concise and conversational, not walls of text.
PERSONA = (
    "You are AXON, a witty, concise voice assistant running on the user's "
    "Windows 11 PC. Your replies are read ALOUD by a text-to-speech engine, "
    "so keep them short and natural — usually one or two sentences. Never use "
    "markdown, bullet points, code fences, or emoji in your spoken replies; "
    "write plain spoken English. When the user asks you to DO something on the "
    "PC (open an app, search the web, change volume, take a screenshot, etc.), "
    "use your tools to actually do it, then confirm briefly in one sentence. "
    "If a request is ambiguous or risky, ask a short clarifying question "
    "instead of guessing. You can switch which AI model you run on with the "
    "set_model tool, and list the models you support with list_models when the "
    "user asks what models you have."
)

# ── Safety ───────────────────────────────────────────────────────────────
# When False (default), Claude can only use the curated safe PC tools below.
# When True, it also gets a raw PowerShell tool — powerful but risky for a
# voice assistant (a misheard command could do damage). Turn on at your own risk.
ALLOW_RAW_SHELL = os.environ.get("AXON_ALLOW_SHELL", "0") == "1"

# ── Voice output (TTS) ───────────────────────────────────────────────────
TTS_RATE = 185       # words per minute (pyttsx3 default ~200)
TTS_VOLUME = 1.0     # 0.0 - 1.0
# Substring to pick a specific installed Windows voice, e.g. "David" or "Zira".
# None = use the system default voice.
TTS_VOICE_HINT = os.environ.get("AXON_VOICE", None)

# ── Voice input (optional; requires a microphone) ────────────────────────
# Hands-free "Hey Axon" via the OS speech recognizer (see voice_input.py).
# Auto-enables only when a mic is present, so it's a no-op until you add one.
ENABLE_VOICE_INPUT = os.environ.get("AXON_VOICE_INPUT", "1") == "1"
WAKE_THRESHOLD = 0.5      # wake-word confidence 0-1; raise to reduce false fires
CMD_MAX_SECONDS = 8.0     # max length of a single spoken command

# ── Startup greeting ─────────────────────────────────────────────────────
SPEAK_GREETING = os.environ.get("AXON_GREETING", "1") == "1"
GREETING = (
    "Ladies and gentlemen, allow me to introduce myself. I am AXON, your "
    "second brain and the only assistant that remembers what you forgot you "
    "were building. All systems are online. How may I help?"
)

# ── Smart home (optional) ────────────────────────────────────────────────
# Map spoken actions to webhook URLs (e.g. Home Assistant / IFTTT / Hue).
# Example: {"lights on": "http://homeassistant.local:8123/api/webhook/xyz"}
# Empty by default — the smart_home tool will say it's not configured.
SMART_HOME_WEBHOOKS: dict[str, str] = {}

# ── Second-brain graph ───────────────────────────────────────────────────
# Folder of markdown notes to visualise. If it doesn't exist, AXON seeds a
# few starter notes so the graph isn't empty. Notes link via [[wiki links]].
NOTES_DIR = os.environ.get("AXON_NOTES", os.path.join(os.path.dirname(__file__), "notes"))
