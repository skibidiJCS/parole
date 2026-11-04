# parole.py — the app itself

[parole.py](../parole.py) is the entry point. It builds the menu bar app, starts the threads,
reacts to the shortcut, and runs the "transcribe → tidy → paste" pipeline. Every other
module is used from here.

---

## Lines 1–18: module docstring

Describes how to run Parole (`open /Applications/Parole.app`, or
`.venv/bin/python -u parole.py` in Terminal; `-u` means "unbuffered output", so log lines
appear immediately) and the three main threads (see the overview, section 2).

## Lines 20–48: imports

```python
import os            # file paths (expanduser for "~")
import queue         # the thread-safe mailbox between the key thread and the worker
import subprocess    # to run the "open" command (Edit vocabulary…)
import sys           # sys.stdout, to redirect printing to a log file
import threading     # Thread, Lock, Timer
import time          # timing measurements and timestamps in the log
```

- **Line 27** `import rumps` – a small library that makes macOS menu bar apps easy. It runs
  the AppKit main loop for us.
- **Line 28** `AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt` – asks macOS
  "does this app have the Accessibility permission?", optionally showing the system prompt.
- **Lines 29–36** AppKit classes:
  - `NSApplication` – the running application object.
  - `NSApplicationActivationPolicyAccessory` – a constant meaning "no Dock icon, never
    becomes the active app".
  - `NSColor` – colours (used to tint the icon red while recording).
  - `NSImage` – images (the menu bar icon).
  - `NSPasteboard`, `NSPasteboardTypeString` – the clipboard and its "plain text" format.
- **Line 37** `AppHelper` – from PyObjC; provides `callAfter` (run on the main thread).
- **Lines 39–48** Parole's own modules. `import context` imports the module (used as
  `context.read()`); the `from X import Y` lines import individual names.

## Lines 50–58: settings

```python
MIN_SECONDS = 0.3      # recordings shorter than this are treated as accidental presses
TAP_SECONDS = 0.3      # a press shorter than this = a "tap" = hands-free mode
MAX_HANDS_FREE = 10 * 60   # 600 s: hands-free stops on its own after 10 minutes
LIVE_INTERVAL = 0.5    # the live preview refreshes every half second
MAX_PENDING = 20       # live preview: after 20 s of speech with no pause, commit it anyway
HESITATION = 1.0       # a mid-sentence pause of ≥ 1 s is written as "..."
MISSED_SPEECH = 0.8    # if ≥ 0.8 s of speech is missing from Whisper's text, retry that part
READY = "Ready: hold ⇧ + right ⌘ and speak"     # status line text
LOG_PATH = os.path.expanduser("~/Library/Logs/Parole.log")  # "~" → /Users/jiacai
```

## Lines 60–68: `ICONS`

A dictionary from app state to an **SF Symbol** name (Apple's built-in icon set). E.g. in the
`"recording"` state the menu bar shows the `mic.fill` symbol.

## Lines 71–72: `log`

```python
def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)
```

Prints e.g. `14:03:22 Model ready in 3.1s`. `time.strftime("%H:%M:%S")` formats the current
time as hours:minutes:seconds. `flush=True` writes it out immediately instead of waiting in a
buffer. (When running as an app, `print` goes to the log file — see `main()`.)

## Lines 75–83: `check_audio`

```python
def check_audio(audio):
    seconds = len(audio) / SAMPLE_RATE          # number of samples ÷ 16000 = duration
    if seconds < MIN_SECONDS:
        return f"too short ({seconds:.2f}s), hold the keys while you speak"
    if not audio.any():                         # .any() is True if any sample is non-zero
        return "the mic only gives silence; allow Microphone access in Privacy & Security"
    return None
```

Returns `None` when the audio is usable, otherwise a reason string. The `audio.any()` check
exists because when microphone permission is denied, macOS doesn't raise an error — it just
delivers zeros.

## Lines 86–112: `transcribe_speech` (module-level function)

Turns audio of any length into text. Whisper reads at most 30 s at once and works better on
one sentence at a time, so the audio is cut at pauses first.

```python
text, first_language = before, None
```
`before` is text already transcribed (the live preview's finished part); new pieces are
appended to it. `first_language` will hold the language of the first new piece.

```python
pieces = [(start, end, True) for start, end in voice.speech_pieces(audio)]
```
`voice.speech_pieces` returns `(start_sample, end_sample)` pairs. Each is turned into a
3-tuple whose third element, `check`, says "after transcribing, check whether Whisper
skipped speech". It starts `True` for every piece.

```python
previous_end = 0
```
Where the previous piece ended (in samples). Used to measure the pause between pieces.

```python
while pieces:
    start, end, check = pieces.pop(0)
```
Process pieces one by one, taking them off the front of the list (`pop(0)`).

```python
    piece, language, covered = transcriber.transcribe(audio[start:end], prompt)
```
Run Whisper on just this slice of audio. Returns the text, the detected language, and
`covered`: a list of `(start_seconds, end_seconds)` of the parts of the slice the text came
from.

```python
    cuts = missed_speech(voice, audio[start:end], covered) if check and piece else []
```
If we're allowed to check this piece and it produced some text, ask `missed_speech` where
Whisper skipped speech. A conditional expression: `X if condition else Y`.

```python
    if cuts:
        bounds = [start] + [start + cut for cut in cuts] + [end]
        pieces[:0] = [(a, b, False) for a, b in zip(bounds, bounds[1:])]
        continue
```
If speech was skipped, split this piece at the cut points and put the sub-pieces **at the
front** of the list (`pieces[:0] = ...` inserts at position 0), then go round the loop again.
- `cuts` are positions relative to the slice, so `start + cut` makes them absolute.
- `zip(bounds, bounds[1:])` pairs each bound with the next: `[0, 5, 9]` → `(0, 5), (5, 9)`.
- The sub-pieces get `check=False`, so they are never split again (prevents an endless loop).
- The text from this first attempt is thrown away; the sub-pieces are transcribed instead.

```python
    if piece:
        pause = (start - previous_end) / SAMPLE_RATE + 2 * PADDING
        text = join_pieces(text, piece, hesitation=pause >= HESITATION)
        first_language = first_language or language
    previous_end = end
```
- `pause` is the silence between the previous piece and this one, in seconds. Each piece was
  widened by `PADDING` (0.2 s) on both sides in voice.py, so the real silence is the gap
  between the padded pieces **plus** both paddings.
- `join_pieces` (cleanup.py) glues the new text on; if the pause was ≥ 1 s it may write "...".
- `first_language or language`: keep the first non-`None` language found.
- `previous_end = end` is updated even if the piece produced no text.

```python
return text, first_language
```

## Lines 115–129: `missed_speech`

Finds stretches of the piece that Whisper's text doesn't cover but that contain speech.

```python
edges = [0] + [int(t * SAMPLE_RATE) for span in covered for t in span] + [len(audio)]
```
Flattens `covered` into a list of sample positions with 0 in front and the end at the back.
The nested comprehension `for span in covered for t in span` reads like two nested `for`
loops. Example: covered `[(0.5, 2.0), (3.0, 4.0)]` on a 6 s clip →
`[0, 8000, 32000, 48000, 64000, 96000]`.

```python
for gap_start, gap_end in zip(edges[::2], edges[1::2]):
```
`edges[::2]` takes every second element starting at 0 (`0, 32000, 64000`), `edges[1::2]`
every second element starting at 1 (`8000, 48000, 96000`). Zipping them gives the
**uncovered** stretches: before the first covered span, between spans, and after the last.

```python
    if gap_end - gap_start < MISSED_SPEECH * SAMPLE_RATE:
        continue
```
Skip gaps shorter than 0.8 s; they can't hold 0.8 s of speech.

```python
    speech = sum(span["end"] - span["start"] for span in voice.spans(audio[gap_start:gap_end]))
```
Run the voice detector on just the gap and add up how many samples of speech it found.

```python
    if speech > MISSED_SPEECH * SAMPLE_RATE:
        cuts += [edge for edge in (gap_start, gap_end) if 0 < edge < len(audio)]
return sorted(set(cuts))
```
If the gap holds more than 0.8 s of speech, cut at both of its edges — except edges at the
very start or end of the clip, where a cut is meaningless. `sorted(set(cuts))` removes
duplicates and sorts.

## Lines 132–142: `class LivePreview`

A small object holding the state of the live preview during one recording.

```python
self.done_samples = 0   # audio before this sample is transcribed for good...
self.done = ""          # ...into this text
self.language = None    # language of the first finished piece
self.preview = ""       # done + the current unfinished piece (re-transcribed every refresh)

def text(self):
    return self.preview or self.done
```
`text()` returns the preview if there is one, otherwise the finished text (`or` returns the
first truthy value; an empty string is falsy).

## Lines 145–195: `class Parole(rumps.App)` and `__init__`

`Parole` **inherits** from `rumps.App`, so it is a menu bar app and gets all of rumps'
behaviour.

- **Line 147** `super().__init__("Parole", quit_button=None)` – calls `rumps.App`'s own
  constructor: the app's name is "Parole", and rumps should **not** add its default Quit
  item (we add our own at line 171 so we can close the mic first).
- **Line 148** `log_transcripts` – whether the log may contain your dictated text (only when
  running from Terminal; see `main()`).
- **Lines 150–159** menu items. `rumps.MenuItem("text", callback=function)` makes a clickable
  item that calls `function(item)` when clicked. Items without a callback are greyed out and
  used as status lines. `.state = True` shows a checkmark: the four toggles start "on".
- **Lines 160–172** `self.menu = [...]` sets the menu's contents in order. `None` in the list
  becomes a separator line.
- **Line 174** `self.recorder = Recorder()` – the microphone object (recorder.py).
- **Line 175** `self.recordings = queue.Queue()` – the mailbox to the worker thread. It
  receives either the string `"start"` or a tuple `(audio, released_at)`.
- **Lines 176–180** recording state:
  - `is_recording` – the mic is on.
  - `hands_free` – tap mode: recording continues after the keys are released.
  - `ignore_release` – set when a press **stops** hands-free mode, so that the release of
    that same press doesn't do anything.
  - `pressed_at` – when the shortcut was pressed (to tell a tap from a hold).
  - `auto_stop` – a `threading.Timer` that ends a forgotten hands-free recording.
- **Line 183** `self.lock = threading.Lock()` – the key thread, the auto-stop timer and the
  Quit button all change the recording state; the lock makes them take turns.
- **Line 184** `last_text` – the last dictation, for "Copy last dictation". Memory only.
- **Line 185** `Transcriber()` – Whisper wrapper (not loaded yet; the worker loads it).
- **Line 186** `self.voice = None` – the voice detector; the worker creates it.
- **Lines 187–188** `Vocabulary()` and `ensure_file()` – create
  `~/Library/Application Support/Parole/vocabulary.txt` if it doesn't exist.
- **Line 189** `Bubble()` – the live-preview panel (built lazily on first show).
- **Line 190** `self.live = None` – a `LivePreview` while recording with the preview on.
- **Line 191** `context.Context()` – an empty context (text around the cursor).
- **Line 192** `Learner(self.vocabulary, on_learned=self.learned)` – learns corrections; calls
  `self.learned(heard, wanted)` when it learns one. Note `self.learned` without `()`: we pass
  the method itself, to be called later.
- **Lines 193–195** `Shortcut(...)` – the hotkey detector; we hand it three of our methods to
  call on press, release and cancel.

## Lines 197–202: `run`

```python
NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
threading.Thread(target=self.work, daemon=True).start()
super().run()
```
1. Make the app "accessory": no Dock icon, and it never steals focus from the app you're
   typing into.
2. Start the worker thread running `self.work`. `daemon=True` means the thread won't keep
   the program alive: when the main thread ends, it's killed too.
3. `super().run()` is rumps' `run`: it starts the AppKit **event loop** on the main thread.
   This call doesn't return until the app quits.

## Lines 206–220: `show` and `_show` (updating the menu bar)

```python
def show(self, state, status=None, last=None):
    AppHelper.callAfter(self._show, state, status, last)
```
Any thread may call `show`. It asks the main thread to run `_show` with the same arguments.

```python
def _show(self, state, status, last):
    button = self._nsapp.nsstatusitem.button()
```
Reaches into rumps' internals (`_nsapp.nsstatusitem`) to get the real macOS status-bar item
and its button (the clickable icon in the menu bar).

```python
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(ICONS[state], f"Parole: {state}")
    image.setTemplate_(True)
    button.setImage_(image)
    button.setTitle_("")
```
Load the SF Symbol for this state (the second argument is a description for VoiceOver).
"Template" images are drawn by macOS in the menu bar's own colour (black in light mode, white
in dark mode). `setTitle_("")` removes the text "Parole" so only the icon shows.

```python
    red = state in ("recording", "hands_free")
    button.setContentTintColor_(NSColor.systemRedColor() if red else None)
```
Tint the icon red while recording; `None` restores the normal colour.

```python
    if status:
        self.status_item.title = status
    if last:
        self.last_item.title = last
```
Update the two greyed-out status lines in the menu, only if new text was given.

## Lines 224–258: menu callbacks (run on the main thread)

rumps calls each with the clicked `MenuItem` as argument (`item`, or `_` when unused — `_`
is the usual name for "a parameter I don't need").

- **`toggle_fast`** – flips the checkmark (`not item.state`) and tells the transcriber.
  `bool(...)` turns rumps' `1/0` state into `True/False`.
- **`toggle_repeats`, `toggle_live`, `toggle_learn`** – only flip the checkmark and log. The
  rest of the code reads the checkmark directly when it needs it (e.g.
  `self.repeats_item.state` in `tidy`).
- **`copy_last`** – puts the last dictation on the clipboard: get the system clipboard
  (`generalPasteboard`), empty it, write the string as plain text.
- **`edit_vocabulary`** – `subprocess.Popen` starts a program without waiting for it.
  `open -t file` is the macOS command "open this file in the default text editor".
- **`quit`** – stop the key listener, cancel the auto-stop timer if there is one, close the
  mic (inside `try` in case it fails), then `rumps.quit_application()` ends the event loop.

## Lines 261–336: shortcut callbacks (run on pynput's thread)

The comment at 261–264 explains the two modes: **hold** = push-to-talk; **tap** = hands-free
(tap again to stop). These methods must be quick: macOS considers the key handler stuck if it
blocks.

### `start_recording` (lines 266–283) — the shortcut was pressed

```python
with self.lock:
    if self.hands_free:
        self.hands_free = False
        self.ignore_release = True
        self.finish_recording()
        return
```
If hands-free recording is running, this press **stops** it: finish the recording, and mark
that the coming release of these keys should be ignored. `return` inside `with` still
releases the lock.

```python
    try:
        self.recorder.start()
    except Exception as error:
        log(f"Could not open the microphone: {error}")
        self.show("error", "Microphone unavailable; check Privacy & Security > Microphone")
        return
```
Open the mic; on failure log it, show the error icon, stop.

```python
    self.is_recording = True
    self.pressed_at = time.perf_counter()
    self.recordings.put("start")
self.show("recording", "Recording…")
```
`time.perf_counter()` is a high-precision clock for measuring durations (its absolute value
means nothing, only differences do). `put("start")` wakes the worker so it can read the
context and start the live preview. The icon update happens after the lock is released.

### `stop_recording` (lines 285–299) — the shortcut was released

```python
with self.lock:
    if self.ignore_release:
        self.ignore_release = False
        return
```
This is the release of the press that stopped hands-free: do nothing (just reset the flag).

```python
    if not self.is_recording:
        return
```
Nothing to stop (e.g. the mic failed to open, or it was cancelled).

```python
    if time.perf_counter() - self.pressed_at < TAP_SECONDS:
        self.hands_free = True
        self.auto_stop = threading.Timer(MAX_HANDS_FREE, self.stop_forgotten)
        self.auto_stop.daemon = True
        self.auto_stop.start()
        self.show("hands_free", "Hands-free: tap ⇧ + right ⌘ again to stop")
        return
    self.finish_recording()
```
Held for less than 0.3 s → it was a tap: switch to hands-free and keep recording. A timer
will call `stop_forgotten` after 10 minutes. Otherwise it was a hold: finish now.

### `cancel_recording` (lines 301–311) — another key was pressed during the shortcut

E.g. Shift+Cmd+4 (screenshot) also presses Shift and Right Command. In push-to-talk mode,
throw the audio away (`recorder.stop()` returns it; we ignore the return value) and go back
to idle. In hands-free mode it does nothing (you may be typing while dictating hands-free).

### `stop_forgotten` (lines 313–319) — timer thread

After 10 minutes of hands-free recording, finish it (if still hands-free). `//` is integer
division: `600 // 60 = 10`.

### `finish_recording` (lines 321–336) — called with the lock already held

```python
if self.auto_stop:
    self.auto_stop.cancel()
    self.auto_stop = None
released_at = time.perf_counter()
```
Cancel the auto-stop timer; note when the recording ended (for the latency measurement).

```python
try:
    audio = self.recorder.stop()
except Exception as error:
    log(...); self.show("error", "Recording failed; try again")
    return
finally:
    self.is_recording = False
```
Close the mic and get the audio. The `finally` block runs whether `stop()` worked or failed
(even though the `except` branch has a `return`), so `is_recording` is always reset.

```python
self.show("transcribing", "Transcribing…")
self.recordings.put((audio, released_at))
```
Hand the audio to the worker as a tuple.

## Lines 338–340: `learned`

Called by the Learner when it learns a correction. Logs it (the actual words only if
`log_transcripts`), then shows "Learned: X → Y" in the menu. `AppHelper.callAfter(setattr,
self.last_item, "title", "...")` means: on the main thread, run
`setattr(self.last_item, "title", "...")`, which is the same as
`self.last_item.title = "..."`. (`setattr` is used because you can't pass an assignment as a
function.)

## Lines 344–389: `work` — the worker thread's main function

```python
self.show("loading")
log("Loading the Whisper model...")
start = time.perf_counter()
try:
    self.transcriber.warm_up()
    self.voice = VoiceDetector()
except Exception as error:
    log(...); self.show("error", "..."); return
log(f"Model ready in {time.perf_counter() - start:.1f}s")
```
Load Whisper and the voice detector here (MLX wants the model used from the thread that
loaded it). If loading fails, show the error and end the thread.

```python
self.shortcut.start()
if self.shortcut.trusted:
    self.show("idle", READY)
else:
    log(...); self.show("error", "Allow Accessibility + Input Monitoring, then reopen Parole")
    AppHelper.callAfter(AXIsProcessTrustedWithOptions, {kAXTrustedCheckOptionPrompt: True})
```
Only start listening to keys once we can transcribe. If Accessibility isn't granted, ask
macOS (on the main thread) to show its permission prompt; the dictionary
`{kAXTrustedCheckOptionPrompt: True}` is the "please show the prompt" option.

```python
while True:
    try:
        item = self.recordings.get(timeout=LIVE_INTERVAL if self.live else None)
    except queue.Empty:
        item = "refresh"
```
The loop runs forever. `get()` waits for the next item:
- while a live preview is running, it waits at most 0.5 s; if nothing arrives, `get` raises
  `queue.Empty`, which we turn into `"refresh"`;
- otherwise `timeout=None` means wait forever (no CPU used while idle).

```python
    try:
        if item == "start":
            self.context = context.read()
            if self.live_item.state:
                self.live = LivePreview()
                AppHelper.callAfter(self.bubble.show, "Listening…")
        elif item == "refresh":
            self.refresh_live()
        else:
            self.dictate(*item)
```
- `"start"`: read the text around the cursor (its names go into Whisper's prompt) and, if
  live preview is on, create the preview state and show the bubble.
- `"refresh"`: update the live preview.
- otherwise it's `(audio, released_at)`; `*item` unpacks the tuple into two arguments, so this
  is `self.dictate(audio, released_at)`.

```python
    except Exception as error:
        log(...); self.show("error", f"Error: {error}")
        self.live = None
        AppHelper.callAfter(self.bubble.hide)
```
Any unexpected error is caught so one bad dictation never kills the worker thread; the
preview is reset and the bubble hidden.

## Lines 391–393: `transcribe_speech` (method)

```python
prompt = self.vocabulary.prompt(extra=self.context.terms)
return transcribe_speech(self.transcriber, self.voice, audio, prompt, before)
```
Builds Whisper's prompt from your vocabulary words plus names found near the cursor, then
calls the module-level `transcribe_speech` (same name, different thing: the one inside the
class is reached as `self.transcribe_speech`, the one at module level as plain
`transcribe_speech`).

## Lines 395–399: `tidy`

```python
if self.repeats_item.state:
    text = remove_repeats(apply_corrections(remove_fillers(text)))
return self.vocabulary.fix(text)
```
If the clean-up toggle is on, apply three clean-ups, innermost first: remove fillers → apply
self-corrections → remove repeats. Vocabulary replacements are always applied.

## Lines 401–422: `refresh_live`

```python
live = self.live
if not self.is_recording:
    self.live = None
    AppHelper.callAfter(self.bubble.hide)
    return
```
If the recording ended without a dictation (cancelled, mic failed), stop the preview.

```python
rest = self.recorder.snapshot()[live.done_samples :]
spans = self.voice.spans(rest) if len(rest) > SAMPLE_RATE // 2 else []
if not spans:
    return
```
Take the audio recorded so far and keep only the part not yet transcribed for good. Run voice
detection on it if it's longer than half a second (`SAMPLE_RATE // 2` = 8000 samples). No
speech yet → nothing to update.

```python
speech_end = spans[-1]["end"]
if len(rest) - speech_end > PAUSE * SAMPLE_RATE or speech_end > MAX_PENDING * SAMPLE_RATE:
```
`speech_end` is where the last speech ends. Two reasons to commit text "for good":
- the silence after the last speech is longer than `PAUSE` (1 s): you finished a sentence;
- more than 20 s of speech is waiting without a pause.

```python
    end = min(len(rest), speech_end + int(PADDING * SAMPLE_RATE))
    live.done, language = self.transcribe_speech(rest[:end], live.done)
    live.language = live.language or language
    live.done_samples += end
    live.preview = ""
```
Transcribe up to just after the speech (plus 0.2 s padding), append it to `live.done`, and
move `done_samples` forward so this audio is never transcribed again. This is why the end of
a long dictation is fast: most of it is already done.

```python
else:
    live.preview, _ = self.transcribe_speech(rest, live.done)
AppHelper.callAfter(self.bubble.show, self.tidy(live.text()) or "Listening…")
```
No pause yet: transcribe the pending audio as a temporary preview (redone next refresh;
`_` discards the language). Then show the tidied text in the bubble.

## Lines 424–428: `dictate`

```python
try:
    self._dictate(audio, released_at)
finally:
    AppHelper.callAfter(self.bubble.hide)
```
A wrapper whose only job is to guarantee the bubble is hidden, however `_dictate` ends.

## Lines 430–483: `_dictate` — the full pipeline for one recording

```python
live, self.live = self.live, None
```
Take the preview state into a local variable and clear the attribute in one statement (the
right side is evaluated first, then assigned). Clearing it stops the refresh timeout.

```python
problem = check_audio(audio)
if problem:
    log(f"Skipped: {problem}"); self.show("idle", f"Skipped: {problem}"); return
```
Too short or silent → skip.

```python
transcribe_start = time.perf_counter()
done_samples, done, done_language = (live.done_samples, live.done, live.language) if live else (0, "", None)
text, language = self.transcribe_speech(audio[done_samples:], done)
language = done_language or language
```
Reuse what the live preview already finished (or start from nothing if there was no
preview), and transcribe only the remaining audio.

```python
if not text:
    log(...); self.show("idle", "Skipped: no speech detected"); return
text = self.tidy(text)
if text[-1:].isalnum():
    text += "."
transcribed_at = time.perf_counter()
if not text:
    log("Nothing recognized"); self.show(...); return
```
Skip if nothing was said. Tidy. If the text ends in a letter/digit, add a period.
`text[-1:]` is safe on an empty string (gives `""`, and `"".isalnum()` is `False`). The second
`if not text` catches text that became empty after tidying (e.g. you only said "um").

```python
self.last_text = text
log(f"[{language}] {text if self.log_transcripts else f'{len(text)} characters'}")
```
Remember it for "Copy last dictation" and log it (only the length when running as an app).
Note the nested f-string inside the conditional expression.

```python
try:
    if not self.shortcut.released.wait(timeout=2):
        raise RuntimeError("release Shift and Right Command, then try again")
```
Wait (up to 2 s) until you've let go of all shortcut keys. A held Shift would turn our Cmd+V
into Cmd+Shift+V. `Event.wait` returns `False` if the timeout ran out.

```python
    here = context.read()
    text = context.fit(text, here, names=self.vocabulary.words())
    self.last_text = text
```
Read the context **again** (you may have clicked elsewhere while speaking) and fit the text:
lowercase first letter mid-sentence, drop the period before following text, etc.

```python
    self.learner.finish()
    pasted = text + context.space_after(here)
    paste_sent_at = paste_text(pasted)
    if self.learn_item.state:
        self.learner.watch(here, text)
```
- Give the learner a last look at the previous dictation before this new one changes the text.
- Add a trailing space if needed (dictations never start with a space; the previous one left
  one after itself).
- Paste. `paste_text` returns the moment Cmd+V was sent.
- If learning is on, start watching this spot for your corrections.

```python
except Exception as error:
    log(f"Paste failed: {error}")
    self.show("error", "Paste failed; use Copy last dictation", last=f"Last: {text[:40]}")
    return
```
If anything failed, the text is still available through "Copy last dictation". `text[:40]` =
first 40 characters.

```python
total_ms = (paste_sent_at - released_at) * 1000
log(f"  audio ...s, ...s done live, last ...s at release | latency ... ms (transcribe ... ms via fast, paste ... ms)")
self.show("idle", READY, last=f"Last: {total_ms:.0f} ms ({self.transcriber.last_path}, {language})")
```
Timing report: total latency from key release to paste, broken into parts. The adjacent
f-strings inside `log(...)` are automatically joined into one string by Python.
`:.0f` = no decimals.

## Lines 486–496: `main` and the entry point

```python
def main():
    in_terminal = sys.stdout is not None and sys.stdout.isatty()
```
`isatty()` is `True` when output goes to a terminal window. When launched as `Parole.app`
there's no terminal (and `sys.stdout` may even be `None`).

```python
    if not in_terminal:
        sys.stdout = sys.stderr = open(LOG_PATH, "a", buffering=1)
```
Redirect both normal output and errors to the log file. `"a"` = append (don't erase old
logs); `buffering=1` = line buffered (each line is written as soon as it's complete).

```python
    Parole(log_transcripts=in_terminal).run()

if __name__ == "__main__":
    main()
```
Create the app (log your words only in Terminal, for privacy) and run it. The last two lines
run `main()` only when this file is executed directly.
