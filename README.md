# Parole

Personal, offline speech-to-text dictation for macOS (Apple Silicon).
Hold a hotkey, speak French or English, release, and the text is pasted into the focused app.
Everything runs locally; audio is never written to disk.

Project folder: `/Users/jiacai/Documents/Parole`.
Current version pastes into the focused app and also prints the transcription in Terminal.
Automatic pasting across apps was confirmed by the user on October 31, 2026; the menu bar is an upcoming phase.

## Setup

Requires Python 3.10+ on an Apple Silicon Mac (tested with Python 3.14, macOS 27, M4).

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Download the speech model once (~1.6 GB, stored in `~/.cache/huggingface`):

```bash
.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/whisper-large-v3-turbo')"
```

After that, Parole runs fully offline.

## macOS permissions

Permissions belong to the app that *launches* Python: Terminal, iTerm or VS Code.
Grant them to whichever one you use, in **System Settings > Privacy & Security**:
On this Mac, the Accessibility permission is labelled **Device Control and Data Access**.

| Permission       | Why                                     |
|------------------|-----------------------------------------|
| Microphone       | record your voice                       |
| Accessibility    | simulate Cmd+V to paste                 |
| Input Monitoring | see the hotkey while another app is focused |

Microphone is requested automatically the first time you record. The other two you add yourself with the **+** button.
Quit and reopen the terminal afterwards: macOS only applies them on restart.

## Check the setup

```bash
.venv/bin/python check_setup.py
```

It verifies the packages, the Accessibility permission, records 2 seconds from the mic (in memory) and transcribes them.

## Run

```bash
cd /Users/jiacai/Documents/Parole
.venv/bin/python parole.py
```

Hold **Shift + Right Command**, speak, then release either key to stop. Either Shift key works.
Release both keys before pasting. Text is pasted into the focused app, and text plus latency are printed in Terminal.
Ctrl+C to quit.

First live test: after `Model ready`, focus a blank TextEdit document, hold Shift + Right Command, say a sentence, and release both keys.
Allow Terminal microphone access if macOS asks; retry the recording after granting it.
A quick tap should print `too short`; a quiet recording should print `nothing heard`.
Live microphone and Right Command recording confirmed by the user on October 31, 2026.
Two live dictations took 1151 ms and 1199 ms from key release to text ready.
The user subsequently confirmed Shift + Right Command recording and automatic pasting across apps.
Clipboard restoration and error handling passed automated checks.
Phase 3 test: copy some text first, dictate in TextEdit, then press Cmd+V afterward.
The dictation should appear automatically; Cmd+V afterward should paste your original copied text.
If pasting reports a permission error, enable Terminal under Device Control and Data Access,
quit Terminal completely with Cmd+Q, reopen it, and run Parole again.

## Files

| File             | Role                                                   |
|------------------|--------------------------------------------------------|
| `parole.py`      | hotkey listener + main loop                            |
| `paster.py`      | clipboard snapshot, Cmd+V, and clipboard restoration    |
| `recorder.py`    | microphone capture into memory (16 kHz mono)           |
| `transcriber.py` | Whisper: encode once, detect language, decode          |
| `check_setup.py` | one-off setup and permissions check                    |

## Latency notes (M4 Air, large-v3-turbo)

Whisper pads every clip to 30 s, so the encoder costs ~1 s whatever you say.
`mlx_whisper.transcribe()` ran it twice with language auto-detect (~2.1 s);
calling encoder → language detection → decoder ourselves brings it to ~1.1 s.
Retested after relocation: synthetic English 1148 ms, French 1154 ms; both transcribed correctly.
These measure transcription only, not live microphone capture or pasting.

Paste latency measures key release to sending Cmd+V; target apps may display it slightly later.
Clipboard restoration happens after a 200 ms wait. Every item and data format is preserved;
a newer copy made during that wait is left alone. Slow apps may need a longer wait.

## Roadmap

1. ~~Setup~~
2. ~~Hold hotkey, record, transcribe, print~~
3. ~~Paste into the active app~~
4. Menu bar app
5. Live streaming bubble
6. Cleanup with a local LLM (Ollama)
7. Command mode
8. Settings
9. Package as Parole.app
