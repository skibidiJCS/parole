# Parole: project brief and handoff

You are continuing work on **Parole**, a personal speech-to-text dictation app for my Mac.
Phases 1 and 2 are written. Read this whole brief, then the files in this folder
(`README.md`, `parole.py`, `recorder.py`, `transcriber.py`, `check_setup.py`) before changing anything.

## How to work with me

- This is a learning project. Explain what each part does as you build it.
- Keep the code simple and readable: small modules, clear comments that explain *why*, no clever abstractions.
- Work in small, testable steps. **After each step, tell me exactly how to test it and wait for my confirmation before moving on.**
- Measure and print latency (key released → text pasted) so we can optimize with real numbers.
- Handle errors gracefully: no mic permission, empty audio, very short presses, missing permissions.
- Keep `README.md` up to date (setup, how to run, file roles, latency notes).
- Use git: commit after each phase I confirm works.
- At the end of each step, tell me plainly what *I* need to do (permissions, commands to run, what I should see).

## My setup

- MacBook Air M4, 13", 16 GB RAM, macOS 27.0.1, Apple Silicon (arm64)
- Python 3.14.2 from python.org (`/Library/Frameworks/Python.framework/Versions/3.14`). No Homebrew, no `uv`, no ffmpeg.
- git 2.54 (Apple Git)
- Disk is tight: ~25 GB free (88% used)
- Personal use only: no App Store, no distribution
- I speak French and English, sometimes mixed in one sentence

## What Parole does (the goal)

- Lives in the macOS menu bar (mic icon), no main window.
- Hold a hotkey (default **Right Option**) → speak → release → the transcribed text is pasted into whatever app has focus (Notes, Chrome, Messages, VS Code, ...).
- Runs 100% locally and offline. No cloud APIs. **Audio is never saved to disk.**
- Light on battery and RAM: near-zero CPU when idle, short GPU bursts while transcribing.

## Tech stack

- Python in a virtual environment (`.venv/`)
- Speech-to-text: `mlx-whisper` with `mlx-community/whisper-large-v3-turbo`, language auto-detected
- Audio: `sounddevice`, 16 kHz mono float32
- Hotkey: `pynput`
- Text insertion: copy to clipboard + simulate Cmd+V, then restore the previous clipboard
- Menu bar UI: `rumps`
- Later: Silero VAD (streaming), Ollama + a small local LLM (Llama 3.2 3B or Qwen) for cleanup, `py2app` for packaging

## Build plan

1. ~~Setup: venv, dependencies, model download, permissions~~ (done, committed)
2. ~~MVP: hold hotkey → record → release → transcribe → print, model kept in memory~~ (written; **not yet tested by me with a real mic and key press, not committed**)
3. Paste the text into the active app via clipboard + Cmd+V, then restore the clipboard
4. Menu bar app (rumps): icon shows idle / recording / transcribing; Quit item
5. Live streaming: words appear in a small floating bubble while I speak (re-transcribe the growing buffer, keep stable words, VAD to detect pauses). Target under 500 ms latency.
6. Cleanup mode: optional Ollama pass that removes fillers ("um", "euh") and fixes punctuation and capitalization without changing meaning; toggle in the menu
7. Command mode: e.g. "make this an email", "translate to French"
8. Settings: hotkey, model size, language, cleanup on/off, custom vocabulary (Whisper initial prompt), recent dictation history (in memory only)
9. Package as `Parole.app` with py2app, launching at login

## What has been done so far

### Phase 1: setup (commit `e29e455`)

- `.venv/` created with `python3 -m venv .venv` (Python 3.14.2).
- Installed (pinned in `requirements.txt`): `mlx-whisper==0.4.3`, `sounddevice==0.5.6`, `numpy==2.5.4`, `pynput==1.8.2`, `rumps==0.4.0`.
  `mlx-whisper` also pulls in `torch`, `numba`, `scipy`, `tiktoken`, `huggingface_hub`, and pyobjc frameworks (Cocoa, Quartz, ApplicationServices); these come with `rumps`/`pynput`.
- Model downloaded once with `huggingface_hub.snapshot_download('mlx-community/whisper-large-v3-turbo')` to `~/.cache/huggingface/hub/` (1.6 GB `weights.safetensors`).
- Code sets `HF_HUB_OFFLINE=1` before importing mlx_whisper, so it never contacts the internet.
- `check_setup.py` checks: package imports and MLX device (GPU), Accessibility via `AXIsProcessTrusted()`, mic (records 2 s in memory and checks the peak level), model load + warm-up, then transcribes the 2 s. `--no-mic` skips the mic test.
- `.gitignore`: `.venv/`, `__pycache__/`, `*.pyc`, `.DS_Store`, `build/`, `dist/`.
- `README.md`: setup, permissions table, how to run, file roles, latency notes, roadmap.

### Phase 2: MVP (written, uncommitted)

- **`recorder.py`**: `Recorder` opens a `sounddevice.InputStream` (16 kHz, mono, float32) on `start()`, and its callback appends a copy of each block to a list. `stop()` closes the stream and returns one flat float32 array. The mic is only open while the key is held (no orange dot, no CPU when idle). Exports `SAMPLE_RATE`.
- **`transcriber.py`**: `Transcriber.warm_up()` loads the model with `mlx_whisper.load_models.load_model(..., dtype=mx.float16)` and runs it on 1 s of silence. For clips ≤ 30 s, `transcribe()` does: mel spectrogram (`log_mel_spectrogram(pad_or_trim(mx.array(audio)))`) → **encoder once** → `model.detect_language(features)` → `decode(model, features, DecodingOptions(language=..., without_timestamps=True))`. Both `detect_language` and `decode` skip the encoder when given already-encoded features. Clips over 30 s fall back to `mlx_whisper.transcribe(..., condition_on_previous_text=False)`. Hallucinated output is dropped using Whisper's rule (`no_speech_prob > 0.6 and avg_logprob < -1.0`), and `clean()` treats punctuation-only output (e.g. `"."` on noise) as empty. Returns `(text, language)`.
- **`parole.py`**: `HOTKEY = keyboard.Key.alt_r`. Two threads: pynput's listener thread starts and stops the recorder (it ignores key-repeat presses and must stay fast), and puts `(audio, released_at)` on a `queue.Queue`. The main thread blocks on the queue, runs `check_audio()`, transcribes, and prints `[lang] text` plus `audio Xs | latency N ms (transcribe N ms)`. `check_audio()` rejects clips under `MIN_SECONDS = 0.3`, all-zero audio (what macOS returns when mic access is denied), and RMS below `SILENCE_RMS = 0.002`. It warns at startup if `listener.IS_TRUSTED` is false. Ctrl+C quits.

### Measurements (M4 Air, large-v3-turbo, fp16)

- Model load + warm-up: 2.7–5 s (once, at startup)
- Encoder: **~990 ms per run**, whatever the clip length, because Whisper always pads to 30 s
- `mlx_whisper.transcribe()` with auto-detect: ~2.1 s for a 3.3 s clip (it runs the encoder twice)
- Custom path (encoder once): **~1.1 s** for 3–4 s clips, same text
- 33 s clip (fallback path): ~3.9 s
- Synthetic tests passed: English (`say -v Samantha`) and French (`say -v Thomas`) transcribed exactly. Mixed FR/EN detected as `fr`; the English word came out phonetically, but that's the French TTS voice's accent. The short, all-zero, quiet and noise cases are all rejected correctly. The pynput listener starts without crashing on Python 3.14.

How to make synthetic test audio (16 kHz int16 WAV, readable with Python's `wave` module, no ffmpeg needed):
`say -v Thomas -o fr.wav --data-format=LEI16@16000 "Bonjour, je teste ma dictée."`
Keep such test files outside the project, or in a gitignored folder.

## Current status and immediate next steps

1. **Project location.** The project may still be in a temporary folder. If so, move it to a permanent one (e.g. `~/Code/parole`) and continue from there.
   After moving, `.venv/bin/python` still works, but scripts like `.venv/bin/pip` break (their shebangs hold the old absolute path). Use `.venv/bin/python -m pip ...`, or recreate the venv with `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt` (the model cache in `~/.cache/huggingface` is unaffected).
2. **Permissions.** These belong to the app that launches Python (use Terminal.app). In System Settings → Privacy & Security: add Terminal to **Accessibility** and **Input Monitoring**, allow **Microphone** when prompted, then quit Terminal (Cmd+Q) and reopen it.
3. **Test phase 2 with me** (in Terminal, from the project folder):
   - `.venv/bin/python check_setup.py`: expect four OKs and the spoken words.
   - `.venv/bin/python parole.py`: wait for "Model ready", hold Right Option in any app, speak, release; the text and latency print in Terminal. Also check that a quick tap prints "too short" and holding without speaking prints "nothing heard".
4. Once I confirm it works, **commit phase 2**, then start **phase 3**.

## Notes for upcoming phases

- **Phase 3 (paste):** save the clipboard with `AppKit.NSPasteboard` (pyobjc-framework-Cocoa is installed). Save all item types, not just text, so restoring doesn't lose images or files. Set the text, send Cmd+V with `pynput.keyboard.Controller`, wait briefly (~100–200 ms) so the target app reads the clipboard, then restore. Include paste time in the latency printout. Needs Accessibility.
- **Phase 4 (menu bar):** `rumps` must own the main thread, so the transcription loop moves to a worker thread. Load *and* use the MLX model in that same worker thread. Update the icon/title from the worker safely (e.g. a rumps timer polling state). Show a clear message if permissions are missing.
- **Phase 5 (streaming, < 500 ms):** at ~1 s per encoder run, the 500 ms target can't be met by speeding up a single final pass. Options to weigh with me: (a) transcribe the growing buffer during speech so little is left after release; (b) shrink the encoder window below 30 s (slice the positional embedding / "audio_ctx" trick; risks quality); (c) a smaller model for the live bubble and large-v3-turbo for the final text. Silero VAD can use the already-installed torch or an ONNX build. Mind battery: don't re-run the encoder continuously.
- **Phase 6:** Ollama runs as a separate local server; check it's running and degrade gracefully (paste the raw text) if it isn't. Watch disk space.
- **Phase 8:** custom vocabulary → `DecodingOptions(prompt=...)` on the custom path, `initial_prompt` on the fallback path.
- **Phase 9:** with py2app, permissions attach to `Parole.app` itself and must be granted again. Use `LSUIElement` for menu-bar-only. Launch at login via a LaunchAgent or Login Items.
