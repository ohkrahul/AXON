"""Hands-free voice input via the OS recognizer (System.Speech).

REQUIRES a microphone set as the Windows default recording device.

Why not Whisper? This PC's Smart App Control blocks the community-built native
libraries faster-whisper / ctranslate2 / PyAV ship, so they can't load. The
Microsoft Speech Recognizer is signed by Microsoft, always available, and fully
offline — so it's what we use here.

Why not sounddevice/openWakeWord? PortAudio only exposes this machine's mic via
WDM-KS, which delivered no audio in testing. System.Speech uses the Windows
audio stack directly and sidesteps that.

STATUS: written and ready, but UNTESTED on this machine because no microphone is
currently connected (only 'Stereo Mix' is active). Connect a mic, set it as the
default recording device, and main.py will detect and use this automatically.
"""
from __future__ import annotations

import subprocess
import textwrap
from typing import Optional

import config

_PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]

_w = config.WAKE_WORD.lower()
WAKE_WORDS = [_w, f"hey {_w}", f"okay {_w}", f"ok {_w}"]


def mic_available(timeout: int = 25) -> bool:
    """True if the OS recognizer can open the default recording device."""
    ps = ("Add-Type -AssemblyName System.Speech;"
          "try{$r=New-Object System.Speech.Recognition.SpeechRecognitionEngine;"
          "$r.SetInputToDefaultAudioDevice();[Console]::Out.Write('OK');$r.Dispose()}"
          "catch{[Console]::Out.Write('NO')}")
    try:
        r = subprocess.run(_PS + [ps], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() == "OK"
    except Exception:  # noqa: BLE001
        return False


# One full cycle: block until the wake word, then capture one spoken command.
_CYCLE_PS = textwrap.dedent(r"""
    Add-Type -AssemblyName System.Speech
    $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
    $rec.SetInputToDefaultAudioDevice()

    # Phase 1 — wait for the wake word (constrained grammar = reliable).
    $choices = New-Object System.Speech.Recognition.Choices
    $choices.Add([string[]]@(<WAKE>))
    $gb = New-Object System.Speech.Recognition.GrammarBuilder
    $gb.Append($choices)
    $rec.LoadGrammar((New-Object System.Speech.Recognition.Grammar($gb)))
    $woke = $false
    while (-not $woke) {
        $res = $rec.Recognize()
        if ($null -ne $res -and $res.Confidence -ge <CONF>) { $woke = $true }
    }
    [Console]::Error.WriteLine('WAKE')

    # Phase 2 — capture one free-form command (dictation) with a timeout.
    $rec.UnloadAllGrammars()
    $rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
    $res = $rec.Recognize([TimeSpan]::FromSeconds(<CMDMAX>))
    if ($null -ne $res) { [Console]::Out.Write($res.Text) }
    $rec.Dispose()
""")


class VoiceSession:
    """Runs wake+command cycles; kill() interrupts a blocked cycle on shutdown."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._stopping = False

    def next_command(self) -> Optional[str]:
        """Block until 'Hey Axon' + a command; return the command text."""
        if self._stopping:
            return None
        wake = ",".join("'" + w + "'" for w in WAKE_WORDS)
        ps = (_CYCLE_PS.replace("<WAKE>", wake)
                       .replace("<CONF>", str(config.WAKE_THRESHOLD))
                       .replace("<CMDMAX>", str(config.CMD_MAX_SECONDS)))
        self._proc = subprocess.Popen(
            _PS + [ps], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, _err = self._proc.communicate()
        self._proc = None
        text = (out or "").strip()
        return text or None

    def kill(self) -> None:
        self._stopping = True
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass
