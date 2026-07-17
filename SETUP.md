# Running AXON on another PC (no VS Code)

AXON does **not** need VS Code. Its only link to Claude is the **`claude` CLI**,
which signs in through your **browser** (claude.ai) using your subscription. If a
PC has the Claude CLI + a browser, AXON runs there.

## What the new PC needs
- **Windows 10/11** (the PC-control, file-index and drive tools are Windows-specific)
- **Python 3.11+** — https://python.org (tick *Add Python to PATH*)
- **Node.js 18+** — https://nodejs.org
- **A browser** (Edge/Chrome) — used once to log Claude in
- Your **Claude subscription** account

> Not required: VS Code, an Anthropic API key, a microphone.

## One-time setup
```powershell
# 1. Get the code
git clone https://github.com/ohkrahul/AXON.git
cd AXON

# 2. Run the setup (installs Claude CLI, Python & web deps)
#    Easiest: double-click setup.bat
#    Or in PowerShell:
powershell -ExecutionPolicy Bypass -File .\setup.ps1

# 3. Log Claude in (opens your browser)
claude          # then type:  /login   and sign in
```
> **"setup.ps1 cannot be loaded / is not digitally signed"?** Windows blocks
> downloaded scripts by default. Use `setup.bat` (double-click) or the
> `-ExecutionPolicy Bypass` command above — both are safe and run it once.

`git clone` not available? Just copy the AXON folder over (skip `.venv`,
`node_modules`, and the `web\.next` — `setup.ps1` rebuilds them).

## Run it
```powershell
.\run_axon_web.bat
```
Opens the HUD at http://localhost:3000 (Python API on :8765).

## How the login works (the "browser + CLI" part)
1. The Python app uses the **Claude Agent SDK**, which spawns the **`claude` CLI**.
2. The first time, `claude` `/login` opens **claude.ai in your browser** to authorize.
3. After that, the login is cached on that PC — no browser needed again, and the
   app talks to Claude through the CLI with your subscription.

## Nice differences you may get on another PC
- **Microphone present?** Hands-free *"Hey Axon"* auto-enables (`python check_mic.py` to verify).
- **No Smart App Control?** You could optionally switch STT to Whisper for higher accuracy.
- The **whole-PC file index** rebuilds itself for that machine's drives on first launch.

## Alternative: no subscription CLI
If a machine has no Claude login, set an API key instead and AXON still works:
```powershell
setx ANTHROPIC_API_KEY "sk-ant-..."
```
(The Agent SDK uses the key when no CLI login is present.)
