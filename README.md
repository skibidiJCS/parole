# Parole

Personal, offline speech-to-text dictation for macOS (Apple Silicon).
Hold **Shift + Right Command**, speak French or English, release, and the text is pasted into the focused app.
Everything runs locally; audio is never written to disk.

Parole lives in the menu bar (mic icon) and is installed as `/Applications/Parole.app`.

## Setup

Requires Python 3.10+ on an Apple Silicon Mac (tested with Python 3.14, macOS 27, M4).

```bash
cd /Users/jiacai/Documents/Parole
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Download the speech model once (~1.6 GB, stored in `~/.cache/huggingface`):

```bash
.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/whisper-large-v3-turbo')"
```

After that, Parole runs fully offline.

## Build Parole.app

```bash
cd /Users/jiacai/Documents/Parole
.venv/bin/python -m pip install py2app
.venv/bin/python setup.py py2app -A
mv dist/Parole.app /Applications/
```

`-A` (alias mode) makes a 192 KB app that runs `parole.py` and the packages straight from this folder and `.venv`.
Code changes apply the next time Parole starts, with no rebuild. Rebuild only if `setup.py` changes
or the project folder moves. A rebuilt app counts as a new app for macOS: grant the permissions again.

## macOS permissions

Permissions belong to the app that runs Parole: **Parole** when you open Parole.app, **Terminal** when you run it from Terminal.
In **System Settings > Privacy & Security** (Accessibility is labelled **Device Control and Data Access** on this Mac):

| Permission       | Why                                          |
|------------------|----------------------------------------------|
| Microphone       | record your voice (macOS asks on first use)  |
| Accessibility    | simulate Cmd+V to paste                      |
| Input Monitoring | see the shortcut while another app is focused |

Quit and reopen Parole (or Terminal) after changing them.

## Run

Open **Parole** from Applications or Spotlight. To start it at login: System Settings > General > Login Items > **+** > Parole.

To run it from Terminal with a live log (transcripts included):

```bash
cd /Users/jiacai/Documents/Parole
.venv/bin/python -u parole.py
```

A mic icon appears in the menu bar (an hourglass while the model loads, ~3 s).
Hold **Shift + Right Command** (either Shift, either order), speak, release. Release both keys so the paste is a plain Cmd+V.

| Icon            | Meaning                                       |
|-----------------|-----------------------------------------------|
| hourglass       | loading the model                             |
| mic             | ready                                         |
| red filled mic  | recording                                     |
| waveform        | transcribing                                  |
| warning triangle| something needs attention (see the menu)     |

The menu shows the status, the last latency and which path produced it (`fast` / `full` / `long`),
**Copy last dictation** (in memory only, useful if a paste failed), the **Fast mode** toggle, and **Quit Parole**.
Parole.app logs timings and errors (no transcripts) to `~/Library/Logs/Parole.log`.
From Terminal, the log includes each transcript; Ctrl+C there also quits.

Your clipboard is restored 200 ms after each paste; anything you copy in the meantime is kept.

## Files

| File             | Role                                                          |
|------------------|---------------------------------------------------------------|
| `parole.py`      | menu bar app: icon/menu, worker thread, dictation flow        |
| `hotkey.py`      | Shift + Right Command hold-to-talk (pynput)                   |
| `recorder.py`    | microphone capture into memory (16 kHz mono)                  |
| `transcriber.py` | Whisper: fast short window, full 30 s window, long fallback   |
| `paster.py`      | clipboard snapshot, Cmd+V, and clipboard restoration          |
| `check_setup.py` | one-off setup and permissions check                           |
| `setup.py`       | py2app build settings for Parole.app                          |

## Latency notes (M4 Air, large-v3-turbo, synthetic `say` voices)

Whisper pads every clip to 30 s, so its encoder costs ~1 s whatever you say.

- `mlx_whisper.transcribe()` with auto-detect: ~2.1 s (runs the encoder twice).
- Encoder once, then language detection + decoding: ~1.1 s ("full" path).
- Fused attention (`mx.fast.scaled_dot_product_attention`) or `mx.compile`: only ~6%, not used.
- **Fast mode** (default): encoder window = clip length + 1 s. Encoder 140-280 ms instead of ~1000 ms.
  Without the long silence the decoder repeats itself, so we decode with timestamps and stop at the
  first segment that's an exact repeat or starts past the window. If the result looks unreliable
  (low confidence, or cut off by the token limit) it falls back to the full window.

| Clip                  | Fast    | Full    | Same text?           |
|-----------------------|---------|---------|----------------------|
| EN 1.7 s              | 233 ms  | 1053 ms | missing one comma    |
| EN 2.9 s              | 300 ms  | 1092 ms | yes                  |
| FR 3.5 s              | 326 ms  | 1097 ms | yes                  |
| FR+EN mixed 3.2 s     | 331 ms  | 1095 ms | yes                  |
| FR 5.8 s              | 462 ms  | 1219 ms | yes                  |
| EN 6.8 s              | 382 ms  | 1133 ms | yes                  |
| EN 7.5 s              | 577 ms  | 1168 ms | yes                  |

Faint noise is normally rejected (9/9 fixed samples), but fast mode once turned random noise into
"Thank you." A real voice-activity detector (Silero VAD, phase 5) should fix that.
Live numbers with a real voice are still to be measured.

Latency in the log = key release → Cmd+V sent; the target app may draw the text slightly later.

## Roadmap

1. ~~Setup~~
2. ~~Hold hotkey, record, transcribe, print~~
3. ~~Paste into the active app~~
4. ~~Menu bar app~~ (with fast mode), confirmed working live on October 31, 2026
5. Live streaming bubble
6. Cleanup with a local LLM (Ollama)
7. Command mode
8. Settings
9. ~~Package as Parole.app~~ (alias mode, in /Applications; launch at login via Login Items), confirmed working October 31, 2026
