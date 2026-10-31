# Parole

Offline dictation for macOS (Apple Silicon). Speak French or English; the text is typed into whatever app you're in. Nothing leaves your Mac.

## Use

- **Hold** Shift + Right Command, speak, release: the text is pasted.
- **Tap** Shift + Right Command to talk hands-free; tap again to stop.

The menu bar mic shows the state (red while recording). Its menu has:

- **Copy last dictation**: if a paste didn't land.
- **Edit vocabulary…**: names and jargon, one per line. Add `Jack-eye -> Jiacai` to fix a word that keeps coming out wrong.
- **Fast mode**: on by default. Turn it off for slightly better accuracy (~1 s per dictation instead of ~0.4 s).
- **Remove repeats**: drops stutters and phrases said twice in a row.

## Install

```bash
git clone https://github.com/skibidiJCS/parole.git ~/Documents/Parole && cd ~/Documents/Parole
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt py2app
.venv/bin/hf download mlx-community/whisper-large-v3-turbo   # 1.6 GB, once
.venv/bin/python setup.py py2app -A && mv dist/Parole.app /Applications/
open /Applications/Parole.app
```

In **System Settings > Privacy & Security**, allow Parole under **Accessibility** and **Input Monitoring**, then reopen it. Click **Allow** when it asks for the microphone.
To start it at login, go to System Settings > General > Login Items and add Parole.

The app runs the code from this folder (`-A`), so don't move the folder. Code changes apply when you reopen Parole.
To see a live log, run `.venv/bin/python -u parole.py` instead of the app.

## Files

| File | Role |
|---|---|
| `parole.py` | menu bar app and dictation flow |
| `hotkey.py` | Shift + Right Command (hold or tap) |
| `recorder.py` | microphone, in memory only |
| `voice.py` | skips silence and splits long recordings (Silero VAD) |
| `transcriber.py` | Whisper large-v3-turbo on the GPU (MLX), with fast mode |
| `cleanup.py` | removes stutters and repeats |
| `vocabulary.py` | your words and replacements |
| `spacing.py` | spaces between consecutive dictations |
| `paster.py` | pastes and restores your clipboard |
