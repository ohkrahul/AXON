"""Check whether a microphone is ready for AXON voice input.

Run this after connecting a mic:  python check_mic.py
"""
import subprocess

import voice_input


def capture_endpoints():
    name_key = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
    ps = (
        "$cap='HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\MMDevices\\Audio\\Capture';"
        "foreach($d in Get-ChildItem $cap){"
        "$s=(Get-ItemProperty $d.PSPath).DeviceState;"
        "$p=Join-Path $d.PSPath 'Properties';$n='?';"
        "try{$n=(Get-ItemProperty $p).'" + name_key + "'}catch{};"
        "Write-Output ('0x{0:X8}  {1}' -f $s,$n)}"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


print("Recording devices (state 0x10000001 = ACTIVE, 8 = unplugged, 4 = not present):")
print(capture_endpoints())
print()
if voice_input.mic_available():
    print("RESULT: Microphone is ready. Run `python main.py` and say 'Hey Axon'.")
else:
    print("RESULT: No usable microphone / no default recording device.")
    print("Fix: plug in a mic, then Windows Settings > System > Sound >")
    print("     Input > pick your mic, and set it as default. Re-run this check.")
