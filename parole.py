"""Parole, phase 3: hold Shift + Right Command, speak, release, paste into the focused app.

    .venv/bin/python parole.py

Two threads are involved:
  - pynput's listener thread gets key events and starts/stops the mic.
    It must stay fast, or macOS considers the key handler stuck.
  - The main thread waits for finished recordings and transcribes them,
    so a slow transcription never blocks the keyboard.
A queue hands recordings from the first thread to the second.
"""

import queue
import threading
import time

import numpy as np
from pynput import keyboard

from paster import paste_text
from recorder import SAMPLE_RATE, Recorder
from transcriber import Transcriber

HOTKEY = keyboard.Key.cmd_r  # Right Command
SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
held_keys = set()
hotkey_released = threading.Event()
hotkey_released.set()
MIN_SECONDS = 0.3  # shorter presses are treated as accidental
SILENCE_RMS = 0.002  # below this average loudness, nobody spoke

recorder = Recorder()
recordings = queue.Queue()  # items: (audio, time the key was released)
is_recording = False


def on_press(key):
    global is_recording
    if key != HOTKEY and key not in SHIFT_KEYS:
        return
    held_keys.add(key)
    hotkey_released.clear()
    # Holding a key makes macOS repeat the press event; only react to the first.
    if HOTKEY not in held_keys or not (held_keys & SHIFT_KEYS) or is_recording:
        return
    try:
        recorder.start()
    except Exception as error:
        print(f"Could not open the microphone: {error}")
        return
    is_recording = True
    print("Recording...", flush=True)


def on_release(key):
    global is_recording
    held_keys.discard(key)
    if HOTKEY not in held_keys and not (held_keys & SHIFT_KEYS):
        hotkey_released.set()
    # Either half of the shortcut ending stops the recording.
    if not is_recording or (HOTKEY in held_keys and held_keys & SHIFT_KEYS):
        return
    released_at = time.perf_counter()
    try:
        audio = recorder.stop()
    except Exception as error:
        print(f"Could not finish recording: {error}", flush=True)
        return
    finally:
        is_recording = False
    recordings.put((audio, released_at))


def check_audio(audio):
    """Return None if the audio is worth transcribing, else the reason it isn't."""
    seconds = len(audio) / SAMPLE_RATE
    if seconds < MIN_SECONDS:
        return f"too short ({seconds:.2f}s), hold the key while you speak"
    if not audio.any():
        # macOS hands out pure zeros instead of an error when access is denied.
        return "the mic only gives silence: allow your terminal in Settings > Privacy & Security > Microphone"
    if np.sqrt(np.mean(audio**2)) < SILENCE_RMS:
        return "nothing heard (too quiet)"
    return None


def main():
    print("Loading the Whisper model...")
    transcriber = Transcriber()
    start = time.perf_counter()
    try:
        transcriber.warm_up()
    except Exception as error:
        print(f"Could not load the offline model: {error}")
        print("Run check_setup.py to check the installation and model cache.")
        return
    print(f"Model ready in {time.perf_counter() - start:.1f}s")

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    if not listener.IS_TRUSTED:
        print("Warning: Accessibility is not granted. Automatic pasting is unavailable.")
        print("Enable Terminal in Settings > Privacy & Security > Device Control and Data Access (Accessibility).")
        print("Also enable Input Monitoring, then quit Terminal with Cmd+Q and reopen it.")

    print("Hold Shift + Right Command and speak. Release either key to stop. Ctrl+C to quit.\n")
    try:
        while True:
            audio, released_at = recordings.get()  # waits, using no CPU
            problem = check_audio(audio)
            if problem:
                print(f"Skipped: {problem}\n")
                continue

            transcribe_start = time.perf_counter()
            try:
                text, language = transcriber.transcribe(audio)
            except Exception as error:
                print(f"Could not transcribe this recording: {error}\n")
                continue
            transcribed_at = time.perf_counter()

            print(f"[{language}] {text or '(no words recognized)'}")
            if not text:
                continue
            try:
                # A physically held Shift would turn Cmd+V into Cmd+Shift+V.
                if not hotkey_released.wait(timeout=2):
                    raise RuntimeError("Release Shift and Right Command, then try again.")
                paste_sent_at = paste_text(text)
            except Exception as error:
                print(f"Paste failed: {error}")
                print("The transcription is printed above; you can copy it manually.\n")
                continue
            print(
                f"  audio {len(audio) / SAMPLE_RATE:.1f}s | "
                f"latency {(paste_sent_at - released_at) * 1000:.0f} ms "
                f"(transcribe {(transcribed_at - transcribe_start) * 1000:.0f} ms, "
                f"paste {(paste_sent_at - transcribed_at) * 1000:.0f} ms)\n"
            )
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        listener.stop()
        # Ctrl+C can arrive while the hotkey is still held. Close the mic too.
        try:
            recorder.stop()
        except Exception as error:
            print(f"Could not close the microphone: {error}")


if __name__ == "__main__":
    main()
