"""Parole, phase 2: hold Right Command, speak, release, see the text printed.

    .venv/bin/python parole.py

Two threads are involved:
  - pynput's listener thread gets key events and starts/stops the mic.
    It must stay fast, or macOS considers the key handler stuck.
  - The main thread waits for finished recordings and transcribes them,
    so a slow transcription never blocks the keyboard.
A queue hands recordings from the first thread to the second.
"""

import queue
import time

import numpy as np
from pynput import keyboard

from recorder import SAMPLE_RATE, Recorder
from transcriber import Transcriber

HOTKEY = keyboard.Key.cmd_r  # Right Command
MIN_SECONDS = 0.3  # shorter presses are treated as accidental
SILENCE_RMS = 0.002  # below this average loudness, nobody spoke

recorder = Recorder()
recordings = queue.Queue()  # items: (audio, time the key was released)
is_recording = False


def on_press(key):
    global is_recording
    # Holding a key makes macOS repeat the press event; only react to the first.
    if key != HOTKEY or is_recording:
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
    if key != HOTKEY or not is_recording:
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
        print("Warning: no Accessibility permission, the hotkey won't be seen in other apps.")
        print("Add your terminal in Settings > Privacy & Security > Accessibility and Input Monitoring.")

    print("Hold Right Command and speak. Ctrl+C to quit.\n")
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
            done = time.perf_counter()

            print(f"[{language}] {text or '(no words recognized)'}")
            print(
                f"  audio {len(audio) / SAMPLE_RATE:.1f}s | "
                f"latency {(done - released_at) * 1000:.0f} ms "
                f"(transcribe {(done - transcribe_start) * 1000:.0f} ms)\n"
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
