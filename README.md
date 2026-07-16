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
  - **smart-home** via webhooks (configure in `config.py`)
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

**Sci-fi HUD (recommended):**
```powershell
.\.venv\Scripts\python.exe server.py
```
or double-click **`run_jarvis.bat`**. Then click **◧ Brain** (top-right) for the graph.

Other front-ends:
```powershell
.\.venv\Scripts\python.exe main.py        # lightweight tkinter orb
.\.venv\Scripts\python.exe main_text.py   # console only
```

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
| `server.py` | Web HUD backend (serves HUD, `/state`, `/graph`, `/say`) |
| `webui.html` | Sci-fi HUD + second-brain graph front-end |
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
