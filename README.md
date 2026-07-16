# AXON — AI Assistant + Second Brain (powered by Claude)

An Iron-Man-style desktop assistant with a glowing sci-fi HUD, powered by
**Claude** via the Claude Agent SDK (using your Claude subscription — no API key).
Give it a command; it thinks, **controls your PC**, and **speaks back**. It also
visualises a linked notes folder as an interactive **"second brain" graph**.

Part of **Graphify-Labs**. (Originally prototyped as "Jarvis"; renamed AXON — an
axon is the wire between neurons, i.e. the edges between nodes in a graph.)

---

## ✅ What works right now (no microphone required)

Type into the HUD → Claude thinks → it acts on your PC → it talks back.

- **Brain:** Claude (`claude-fable-5` by default) via the Agent SDK + your subscription
- **Voice output:** offline Windows text-to-speech
- **Spoken startup greeting** (toggle with `AXON_GREETING=0`)
- **Sci-fi HUD:** arc-reactor core that glows 🔵 idle · 🟢 listening · 🟠 thinking · 🟣 speaking
- **Second-brain graph:** click **◧ Brain** to explore your notes as a force-directed
  network (search, top hubs, colour-coded filters, click a node to trace its links)
- **PC control:**
  - open apps · open URLs · web search
  - volume up/down/mute **and set an exact %**
  - media play/pause/next/prev · **play/search Spotify**
  - **type text into any focused window**
  - **timers & reminders** (announced aloud)
  - screenshot · lock PC · time/battery status
  - **find & open files/folders** — "find my resume", "open the Downloads folder",
    "what's in Documents" (search uses the Windows index; open/read only, never deletes)
  - **smart-home** via webhooks (configure in `config.py`)
  - **switch its own AI model** on command — "what models do you have", "switch to opus"
- **Safety:** Claude is restricted to the curated tools above (`permission_mode="dontAsk"`).
  Raw PowerShell is off unless `AXON_ALLOW_SHELL=1`.

## 🎤 Voice input — needs a microphone

Hands-free *"Hey Axon"* is **built and ready** (`voice_input.py`) but **inactive on
this PC: no microphone is connected** (only "Stereo Mix" is active). Connect a mic,
set it as the Windows default recording device, run `python check_mic.py`, then
launch normally — it auto-detects and goes live. It uses the OS speech recognizer
(Whisper is blocked by this PC's Smart App Control).

---

## Run it

AXON is a **Next.js front-end + Python back-end**. The Python API holds the
brain/PC-control/voice; the Next.js app (React + Tailwind) is the HUD and calls
the API through a `/api` proxy.

**Next.js + Python combo (recommended):** double-click **`run_axon_web.bat`**
(starts both, opens `http://localhost:3000`), or manually:
```powershell
# terminal 1 — Python API
$env:AXON_API_ONLY="1"; .\.venv\Scripts\python.exe server.py
# terminal 2 — Next.js HUD
cd web ; npm run dev
```

**Built-in HUD (no Node, single process):**
```powershell
.\.venv\Scripts\python.exe server.py        # serves webui.html itself
```

Other front-ends:
```powershell
.\.venv\Scripts\python.exe main.py          # lightweight tkinter orb
.\.venv\Scripts\python.exe main_text.py     # console only
```

Then click **▣ Brain** (top-right) for the second-brain graph.

Try: `open notepad` · `set volume to 30%` · `play lo-fi beats on spotify` ·
`set a 5 minute timer` · `remind me in 10 minutes to stretch` ·
`search the web for the weather` · `take a screenshot`.

## The second brain

Drop markdown notes in the **`notes/`** folder (auto-seeded with a starter set on
first run). Link them with `[[Wiki Links]]`. Add `group: <name>` on a note's first
lines to colour-code it. The graph reads them live via the `/graph` endpoint.
Point it elsewhere with `AXON_NOTES=C:\path\to\your\vault`.

## First-time setup (already done on this machine)

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install -g @anthropic-ai/claude-code   # the CLI the SDK drives
claude        # run once and /login (if not already)
```

## Configuration — `config.py`

| Setting | Default | Meaning |
|---|---|---|
| `ASSISTANT_NAME` / `WAKE_WORD` | Axon / axon | Name + wake word |
| `MODEL` | `claude-fable-5` | Claude model (`AXON_MODEL` to override) |
| `PERSONA` | witty, concise | Personality / system prompt |
| `SPEAK_GREETING` | `True` | Speak the intro on launch (`AXON_GREETING=0` off) |
| `ALLOW_RAW_SHELL` | `False` | `AXON_ALLOW_SHELL=1` gives Claude raw PowerShell |
| `SMART_HOME_WEBHOOKS` | `{}` | Map actions → webhook URLs |
| `NOTES_DIR` | `./notes` | Folder for the second-brain graph (`AXON_NOTES`) |

## Files

| File | Role |
|---|---|
| `server.py` | Python API + built-in HUD (`/state`, `/graph`, `/say`; CORS + `/api` for Next.js) |
| `web/` | Next.js (React + Tailwind) front-end; proxies `/api/*` → Python |
| `run_axon_web.bat` | Launch the Next.js + Python combo together |
| `webui.html` | Built-in single-process HUD (no Node needed) |
| `graph.py` | Parses the notes folder into a node/edge graph |
| `brain.py` | Claude Agent SDK wrapper |
| `pc_tools.py` | Curated PC-control tools Claude can call |
| `mouth.py` | Text-to-speech |
| `voice_input.py` | "Hey Axon" wake word + dictation (needs a mic) |
| `ui.py` / `main.py` | tkinter orb (alternative UI) |
| `main_text.py` | console version |
| `check_mic.py` | Mic readiness check |
| `config.py` | All settings |

## Notes on this PC
- No microphone → voice input inactive until one is connected.
- Smart App Control blocks Whisper's native libs → OS recognizer used for STT.
- Uses your Claude subscription via the logged-in `claude` CLI.
