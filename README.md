# Parole

Personal, offline speech-to-text dictation for macOS (Apple Silicon).
Hold a hotkey, speak French or English, release, and the text is pasted into the focused app.
Everything runs locally; audio is never written to disk.

## Setup

Requires Python 3.10+ on an Apple Silicon Mac (tested with Python 3.14, macOS 27, M4).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Download the speech model once (~1.6 GB, stored in `~/.cache/huggingface`):

```bash
.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/whisper-large-v3-turbo')"
```

After that, Parole runs fully offline.

## macOS permissions

Permissions belong to the app that *launches* Python: Terminal, iTerm or VS Code.
Grant them to whichever one you use, in **System Settings > Privacy & Security**:

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

## Roadmap

1. ~~Setup~~
2. Hold hotkey, record, transcribe, print
3. Paste into the active app
4. Menu bar app
5. Live streaming bubble
6. Cleanup with a local LLM (Ollama)
7. Command mode
8. Settings
9. Package as Parole.app
