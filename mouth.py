"""Voice output (text-to-speech).

Two backends, tried in order:
  1. pyttsx3  — in-process, uses Windows SAPI voices (installed via pip).
  2. System.Speech via PowerShell — ZERO dependencies, always available on
     Windows. Guarantees AXON can talk even before anything is pip-installed.

Both are offline and free.
"""
from __future__ import annotations

import subprocess

import config

_BACKEND: str | None = None  # decided lazily on first use


def _detect_backend() -> str:
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    try:
        import pyttsx3  # noqa: F401
        _BACKEND = "pyttsx3"
    except Exception:  # noqa: BLE001
        _BACKEND = "powershell"
    return _BACKEND


def _speak_pyttsx3(text: str) -> None:
    import pyttsx3
    # Fresh engine per utterance sidesteps pyttsx3's well-known
    # "second runAndWait hangs" bug on Windows.
    engine = pyttsx3.init()
    engine.setProperty("rate", config.TTS_RATE)
    engine.setProperty("volume", config.TTS_VOLUME)
    if config.TTS_VOICE_HINT:
        for v in engine.getProperty("voices"):
            if config.TTS_VOICE_HINT.lower() in v.name.lower():
                engine.setProperty("voice", v.id)
                break
    engine.say(text)
    engine.runAndWait()
    engine.stop()


def _speak_powershell(text: str) -> None:
    safe = text.replace("'", "''")           # escape single quotes for PS
    # Map words-per-minute (~120-260) onto System.Speech's -10..10 rate scale.
    rate = max(-10, min(10, round((config.TTS_RATE - 190) / 12)))
    vol = int(max(0, min(100, config.TTS_VOLUME * 100)))
    voice_line = ""
    if config.TTS_VOICE_HINT:
        voice_line = f"$s.SelectVoice((($s.GetInstalledVoices()|%{{$_.VoiceInfo.Name}})|?{{$_ -like '*{config.TTS_VOICE_HINT}*'}}|select -First 1));"
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Rate={rate};$s.Volume={vol};"
        f"{voice_line}"
        f"$s.Speak('{safe}');"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=False,
    )


def speak(text: str) -> None:
    """Say `text` out loud (blocks until finished)."""
    text = (text or "").strip()
    if not text:
        return
    backend = _detect_backend()
    try:
        if backend == "pyttsx3":
            _speak_pyttsx3(text)
        else:
            _speak_powershell(text)
    except Exception as e:  # noqa: BLE001
        # Last-ditch: at least show it so the pipeline isn't a black hole.
        print(f"[TTS failed: {e}] {text}")


if __name__ == "__main__":
    print(f"TTS backend: {_detect_backend()}")
    speak("Hello. Axon voice check. If you can hear this, text to speech is working.")
