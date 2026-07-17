<p align="center">
  <img src="docs/hero.svg" alt="AXON — Second Brain System" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/brain-Claude-8A63D2" alt="Claude">
  <img src="https://img.shields.io/badge/UI-Next.js%2016-000000" alt="Next.js 16">
  <img src="https://img.shields.io/badge/agent-Python%203.14-3776AB" alt="Python 3.14">
  <img src="https://img.shields.io/badge/platform-Windows-0078D6" alt="Windows">
  <img src="https://img.shields.io/badge/auth-browser%20login-21d4fd" alt="Browser login">
  <img src="https://img.shields.io/badge/API%20key-not%20needed-2bd576" alt="No API key">
</p>

# AXON — AI Assistant + Second Brain

An Iron-Man-style desktop assistant with a sci-fi HUD, powered by **Claude**.
Talk (or type) to it — it **thinks**, **controls your PC**, **reads any file on any
drive**, and renders everything you own as a **living knowledge graph**. Runs on
your **Claude subscription** via a one-time browser login — **no API key, no extra cost.**

---

## ✨ What it does

- 🧠 **Claude brain** — one persistent conversation, restricted to safe tools
- 🖥️ **Controls your PC** — open apps, web search, exact volume %, media, timers &
  reminders, type into any window, screenshots, lock, Spotify, smart-home webhooks
- 🪟 **Window management** — list, focus, maximize/minimize, snap windows left/right
- 📋 **Clipboard history** — recall and re-copy anything you copied recently
- ✅ **To-do list & daily routines** — remembers to-dos, and runs its own scheduled
  daily instructions ("every morning summarize new files")
- 🗂️ **Knows your whole PC** — indexes every file & folder across all drives
  (~400k+ here); find & open anything, read PDFs/Word docs, or **search inside**
  file contents (not just names)
- 🕐 **"What changed" digest** — ask what files were modified recently
- 👁️ **Reads your screen** — OCR (Windows' built-in engine) reads on-screen text,
  error messages, or any image file — no extra installs
- 🕸️ **Second-brain graph** — interactive force-graph of your files: zoom, pan,
  click a node → AXON tells you about it
- 🎙️ **Talks & listens** — offline text-to-speech; browser mic push-to-talk in any
  language; hands-free **"Hey Axon"** always-listening mode
- 🔔 **Desktop notifications** — timers/reminders/routines ping you even in another tab
- 📜 **Activity log** — a running record of everything AXON has done, on request
- 🔀 **Switch models by voice** — "what models do you have", "switch to opus"
- 🎛️ **Sci-fi HUD** — arc-reactor, live status, top-hub bar-charts, timestamped
  transcript, `LIVE INDEX` counter

## 🧩 Architecture

```mermaid
flowchart LR
  UI["Browser HUD<br/>Next.js + Tailwind"] -->|/api proxy| API["Python API<br/>Starlette + uvicorn"]
  API --> BR["Claude<br/>Agent SDK · subscription"]
  API --> PC["PC tools<br/>apps · volume · files"]
  API --> IX["Whole-PC index<br/>files + folders"]
  API --> GR["Graph builder<br/>/graph"]
  API --> V["Voice<br/>TTS · wake word"]
```

The browser is the screen; a small local Python agent does the real work (a web
page can't touch your files — by design). They talk over a local `/api` proxy.

## 🚀 Install & run

**The easy way — double-click.** Get AXON, then double-click **`AXON.bat`**.
That's it: on first run it auto-installs everything it needs (Python, Node,
Claude Code, dependencies) and launches; after that it just launches. Then
**sign in** in the browser when prompted. No API key — it uses your Claude
subscription.

**Or one line** (installs to your user folder and launches):
```powershell
irm https://raw.githubusercontent.com/ohkrahul/AXON/main/install.ps1 | iex
```

**Get the files** (if not using the one-liner): download the latest
[**Release ZIP**](https://github.com/ohkrahul/AXON/releases/latest) and unzip, or
`git clone https://github.com/ohkrahul/AXON.git`.

> Windows 10/11 + a Claude subscription (Team/Pro). Everything else is installed for you.
> Advanced/manual setup is in [`SETUP.md`](SETUP.md).

## 🗣️ Try saying / typing

`open notepad` · `set volume to 30%` · `find my resume` · `open the Downloads folder` ·
`what's in my Documents` · `read that config file and summarise it` ·
`search my files for "invoice"` · `what changed on my PC today` ·
`read what's on my screen` · `what's in my clipboard history` ·
`add "call the bank" to my to-do list` · `schedule a routine at 09:00 to check my inbox` ·
`snap this window to the left` · `set a 5 minute timer` · `play lo-fi on spotify` ·
`switch to opus` · `what have you been up to` · `clear`

Click **🎧 wake word** in the HUD to go hands-free — say **"Axon"** then your command.

## ⚙️ Configuration — `config.py`

| Setting | Default | Meaning |
|---|---|---|
| `MODEL` | `claude-fable-5` | Model (`AXON_MODEL` to override) |
| `AVAILABLE_MODELS` | fable/opus/sonnet/haiku | Switchable by voice |
| `SPEAK_GREETING` | `True` | Speak the intro on launch |
| `ALLOW_RAW_SHELL` | `False` | `AXON_ALLOW_SHELL=1` gives Claude raw PowerShell |
| `GRAPH_ROOT` | `~` | Folder the graph maps (`AXON_GRAPH_ROOT`) |
| `SMART_HOME_WEBHOOKS` | `{}` | Map actions → webhook URLs |

## 📁 Key files

| File | Role |
|---|---|
| `server.py` | Python API + auth/first-run + all endpoints |
| `web/` | Next.js + Tailwind HUD (the sci-fi UI) |
| `brain.py` | Claude Agent SDK wrapper (runtime model switching) |
| `pc_tools.py` | Curated PC-control + file tools Claude can call |
| `indexer.py` | Whole-PC file/folder catalog + ranked search + recent-changes |
| `graph.py` | Builds the knowledge graph from a folder tree |
| `clipboard_history.py` | Rolling clipboard history |
| `ocr.ps1` | Screen/image text reading via Windows' built-in OCR engine |
| `mouth.py` · `voice_input.py` | Text-to-speech · "Hey Axon" wake word (Windows-side) |
| `preflight.py` | Detects Claude login, guides browser sign-in |
| `setup.ps1` · `SETUP.md` | One-shot setup for a new PC |

## 🔒 Notes & limits
- Restricted tools only (`permission_mode="dontAsk"`); raw shell is opt-in.
- Uses your Claude subscription via Claude Code — **you can't** distribute it as a
  public product where strangers use your login (Anthropic terms); that needs the API.
- On locked-down PCs, Whisper STT is blocked by Smart App Control → OCR and speech
  use Windows' own built-in engines instead (no native binaries to get blocked).
- Calendar/email integration and multi-PC sync aren't built in — they need your own
  OAuth app credentials / a shared cloud service respectively. Point `AXON_NOTES` or
  `AXON_GRAPH_ROOT` at a synced folder (e.g. OneDrive) for a lightweight multi-PC option.
- Risky actions (locking the PC, running PowerShell, rescanning the whole index) get a
  spoken confirmation first — enforced by AXON's persona, not a hard technical gate.

<p align="center"><sub>Created by Rahul Sahu · powered by Claude · Graphify-Labs</sub></p>
