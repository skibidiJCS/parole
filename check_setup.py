"""Phase 1 sanity check for Parole.

Run it from the terminal app you'll use to launch Parole:

    .venv/bin/python check_setup.py

It checks, in order:
  1. The Python packages import correctly.
  2. macOS lets this terminal listen to keys / send keystrokes (Accessibility).
  3. The microphone works (records 2 seconds into memory, never to disk).
  4. The Whisper model loads and transcribes what you just said.
"""

import os
import sys
import time

# The model is already in ~/.cache/huggingface, so never contact the internet.
os.environ["HF_HUB_OFFLINE"] = "1"

MODEL = "mlx-community/whisper-large-v3-turbo"
SAMPLE_RATE = 16_000  # Whisper expects 16 kHz mono audio


def check_imports():
    print("1. Packages")
    import mlx.core as mx
    import mlx_whisper  # noqa: F401
    import pynput  # noqa: F401
    import rumps  # noqa: F401
    import sounddevice  # noqa: F401

    print(f"   OK  (MLX default device: {mx.default_device()})")


def check_accessibility():
    print("2. Accessibility permission")
    # AXIsProcessTrusted() asks macOS: "may this process control the computer?"
    # pynput needs it to see the hotkey globally and to simulate Cmd+V.
    from ApplicationServices import AXIsProcessTrusted

    if AXIsProcessTrusted():
        print("   OK")
    else:
        print("   MISSING: add your terminal app in System Settings > Privacy & Security > Accessibility")
        print("            (and Input Monitoring), then quit and reopen the terminal.")


def check_microphone():
    print("3. Microphone")
    import numpy as np
    import sounddevice as sd

    device = sd.query_devices(kind="input")
    print(f"   Default input: {device['name']}")
    print("   Say something for 2 seconds... (e.g. 'Bonjour, this is a test')")
    audio = sd.rec(int(2 * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()  # block until the recording is finished
    audio = audio.flatten()  # (n, 1) -> (n,)

    peak = float(np.abs(audio).max())
    if peak < 0.001:
        print("   SILENT: no sound captured. Check System Settings > Privacy & Security > Microphone")
        print("           and enable your terminal app.")
        return None
    print(f"   OK  (peak level {peak:.3f})")
    return audio


def check_model(audio):
    print("4. Whisper model")
    import numpy as np
    import mlx_whisper

    # First call loads the weights into memory (slow); later calls reuse them.
    start = time.perf_counter()
    mlx_whisper.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), path_or_hf_repo=MODEL)
    print(f"   Loaded + warmed up in {time.perf_counter() - start:.1f}s")

    if audio is None:
        return
    start = time.perf_counter()
    result = mlx_whisper.transcribe(audio, path_or_hf_repo=MODEL)  # language=None -> auto-detect
    elapsed = (time.perf_counter() - start) * 1000
    print(f"   Heard [{result['language']}]: {result['text'].strip()!r}")
    print(f"   Transcription took {elapsed:.0f} ms")


if __name__ == "__main__":
    skip_mic = "--no-mic" in sys.argv
    check_imports()
    check_accessibility()
    audio = None if skip_mic else check_microphone()
    check_model(audio)
    print("\nDone.")
