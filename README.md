# Parole

Offline dictation for macOS (Apple Silicon). Speak French or English; the text is typed into whatever app you're in. Nothing leaves your Mac.

## Use

- **Hold** Shift + Right Command, speak, release: the text is pasted.
- **Tap** Shift + Right Command to talk hands-free; tap again to stop.

While you speak, a bubble inside the app you're typing in (under the text cursor) shows your words live.
The text is pasted once, when you stop, with a space after a finished sentence so you can keep going. A long pause mid-sentence is written "...", and the sentence keeps going.

The menu bar mic shows the state (red while recording). Its menu has:

- **Copy last dictation**: if a paste didn't land.
- **Edit vocabulary…**: names and jargon, one per line. Add `Jack-eye -> Jiacai` to fix a word that keeps coming out wrong.
- **Fast mode**: on by default. Turn it off for slightly better accuracy (~1 s per dictation instead of ~0.4 s).
- **Clean up fillers, repeats & corrections**: drops "um", "euh", filler "like" ("I need you to like think"), stutters and phrases said twice. Corrects your slips: "on Tuesday, sorry, on Wednesday" becomes "on Wednesday" (also "no wait", "I mean", "I meant", "pardon", "je veux dire", "je voulais dire"), and "scratch that" / "oublie ça" drops the sentence before it.
- **Live preview**: the bubble. Turn it off to save battery; dictation still works the same.
- **Learn from corrections**: fix a misheard word in the text Parole just pasted (say "Jack-eye" to "Jiacai") and leave it for ~10 s. Parole adds `Jack-eye -> Jiacai` to your vocabulary and writes it correctly from then on. Delete the line to undo it.

Parole also reads the text around your cursor (never saved): names in it ("Siobhan", "MLX") get spelled the same way, a dictation in the middle of a sentence starts lowercase, and search boxes get no final period.
Apps that don't share their text (VS Code, many web pages) don't get this or the learning. Password fields are never read.

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
| `bubble.py` | the live-preview bubble |
| `voice.py` | skips silence and splits long recordings (Silero VAD) |
| `transcriber.py` | Whisper large-v3-turbo on the GPU (MLX), with fast mode |
| `cleanup.py` | removes fillers, stutters, repeats and self-corrections; joins sentences across pauses |
| `context.py` | the text around the cursor: names for Whisper, fitting the dictation in |
| `learning.py` | learns replacements from your corrections |
| `ax.py` | asks other apps where their window and text cursor are (Accessibility) |
| `vocabulary.py` | your words and replacements |
| `spacing.py` | a space before a dictation when needed |
| `paster.py` | pastes and restores your clipboard |
