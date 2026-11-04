# Parole: a line-by-line walkthrough

This folder explains every Python file in Parole. Read this overview first; it covers
how the pieces fit together and a few Python / macOS ideas that come up in every file.
After that, go through the files in this order (each builds on the ones before it):

| # | File | What it does |
|---|------|--------------|
| 1 | [parole.py](01-parole.md) | The app itself: menu bar, threads, the "record → transcribe → paste" flow |
| 2 | [recorder.py](02-recorder.md) | Opens the microphone and collects audio in memory |
| 3 | [voice.py](03-voice.md) | Finds where speech is in the audio (Silero VAD) and cuts it at pauses |
| 4 | [transcriber.py](04-transcriber.md) | Runs Whisper (speech → text) on the GPU, with a "fast mode" |
| 5 | [cleanup.py](05-cleanup.md) | Removes "um", stutters, repeats; applies "sorry, I mean…" corrections |
| 6 | [hotkey.py](06-hotkey.md) | Detects Shift + Right Command being held / released |
| 7 | [paster.py](07-paster.md) | Puts the text on the clipboard, presses Cmd+V, restores the clipboard |
| 8 | [ax.py](08-ax.md) | Helpers for the macOS Accessibility API (read other apps' text fields) |
| 9 | [context.py](09-context.md) | Reads the text around your cursor and fits the dictation into it |
| 10 | [bubble.py](10-bubble.md) | The floating live-preview bubble |
| 11 | [vocabulary.py](11-vocabulary.md) | Your custom words file and its "heard -> wanted" replacements |
| 12 | [learning.py](12-learning.md) | Watches your edits after a paste and learns replacements |
| 13 | [setup.py](13-setup.md) | Builds `Parole.app` with py2app |
| 14 | [icon/make_icon.py](14-make-icon.md) | Draws the app icon |

---

## 1. The big picture: what happens when you dictate

```
 you hold ⇧ + right ⌘
        │
 hotkey.py ──on_start──► parole.py: start_recording()  → recorder.py opens the mic
        │                                               → queue.put("start")
        │                                                    │
        │                                   worker thread: context.read() (text around cursor)
        │                                   every 0.5 s: refresh_live() → bubble.py shows words
 you release
        │
 hotkey.py ──on_stop───► parole.py: stop_recording()   → recorder.py closes the mic, returns audio
                                                       → queue.put((audio, time))
                                                             │
                                   worker thread: _dictate()
                                     voice.py        cut audio into pieces at pauses
                                     transcriber.py  Whisper turns each piece into text
                                     cleanup.py      remove fillers / corrections / repeats
                                     vocabulary.py   apply your replacements
                                     context.py      fit to the cursor (capital? final period?)
                                     paster.py       clipboard + Cmd+V
                                     learning.py     watch the spot for your corrections
```

## 2. Threads (the most important idea in parole.py)

A **thread** is a separate line of execution running inside the same program, sharing the
same variables. Parole uses several:

1. **Main thread** – owned by AppKit (Apple's UI framework), started by `rumps`. It draws the
   menu bar icon, the menu and the bubble. **macOS only allows UI changes from this thread.**
2. **pynput's listener thread** – receives every key press/release (hotkey.py).
3. **Worker thread** – loads Whisper and does all the slow work (transcribing, pasting).
4. **sounddevice's audio thread** – hands over microphone samples every few milliseconds.
5. **Timer threads** – `threading.Timer` runs a function once after a delay on a new thread
   (hands-free auto-stop, learning checks).

Because threads share variables, two of them changing the same thing at the same moment can
corrupt it. Tools used to coordinate them:

- `threading.Lock()` – `with self.lock:` means "only one thread at a time may run this block".
  The others wait at the `with` line until the first one leaves the block.
- `queue.Queue()` – a thread-safe mailbox. One thread does `put(item)`, another does
  `get()`, which **waits** until an item arrives. This is how the key thread hands recordings
  to the worker.
- `threading.Event()` – a flag that one thread can `set()`/`clear()` and another can
  `wait()` for.
- `AppHelper.callAfter(function, *args)` – from PyObjC: "please run `function(*args)` on the
  main thread soon". This is how non-main threads update the UI safely.

## 3. PyObjC: calling Apple's Objective-C APIs from Python

Many imports come from `AppKit`, `Foundation`, `Quartz`, `ApplicationServices`,
`NaturalLanguage`. These are **PyObjC** bridges: Python wrappers around Apple's Objective-C
frameworks. Three rules explain almost all of the strange-looking calls:

1. **Method names: colons become underscores.** The Objective-C method
   `setString:forType:` is called in Python as `setString_forType_(text, kind)`. Every `_` in
   the name stands for one argument.
2. **Creating objects: `Class.alloc().init...()`.** Objective-C first allocates memory
   (`alloc`), then initialises (`init` or `initWithSomething_`). E.g.
   `NSPasteboardItem.alloc().init()`.
3. **"Out" parameters become return values.** C functions such as
   `AXUIElementCopyAttributeValue(element, name, &value)` write a result into a pointer.
   In PyObjC you pass `None` for that pointer and get a tuple back:
   `error, value = AXUIElementCopyAttributeValue(element, name, None)`.

Names starting with `NS` are AppKit/Foundation classes (NS = NeXTSTEP, historical), `CG`
is Core Graphics (Quartz), `AX` is Accessibility, `NL` is NaturalLanguage, and constants
start with `k` (e.g. `kAXErrorSuccess`).

## 4. Python features you'll see a lot

| Syntax | Meaning |
|--------|---------|
| `"""..."""` right under `def`/`class`/top of file | A **docstring**: documentation, not executed logic |
| `CONSTANT = 0.3` in capitals at module level | Convention for a setting that never changes |
| `_name` (leading underscore) | Convention for "internal, not meant to be used from outside" |
| `a, b = b, a` / `x, y = (1, 2)` | Tuple unpacking: assign several variables at once |
| `text[-1:]` | Slice of the last character; gives `""` (not an error) on an empty string |
| `items[i : i + n]` | Slice from index `i` up to, not including, `i + n` |
| `f"{seconds:.2f}s"` | f-string; `:.2f` formats a float with 2 decimals |
| `[x for x in items if cond]` | List comprehension: build a list in one line |
| `(x for x in items)` | Generator expression: same, but lazy (values produced on demand) |
| `lambda _: self._place()` | A tiny anonymous function; here it takes one argument and ignores it |
| `dict.fromkeys(items)` | Dictionary with `items` as keys; used to **remove duplicates while keeping order** |
| `set_a & set_b` / `set_a \| set_b` | Set intersection / union |
| `while match := pattern.search(...)` | "Walrus" operator: assign and test in one expression |
| `try / except / finally` | `finally` runs no matter what: success, error, or `return` |
| `with something:` | Context manager: runs setup on entry and guaranteed cleanup on exit |
| `@property` | Makes a method readable like an attribute (`self.shortcut.trusted`, no `()`) |
| `if __name__ == "__main__":` | Code that runs only when the file is executed directly, not when imported |

## 5. Regular expressions (`re`)

cleanup.py, transcriber.py and vocabulary.py use many regular expressions. Quick reference:

| Pattern | Matches |
|---------|---------|
| `\w` | A "word" character: letter (including accented), digit or `_` |
| `\s` / `\S` | Whitespace / anything but whitespace |
| `[^\w']` | Any one character that is **not** a word character or `'` |
| `+` `*` `?` | 1 or more / 0 or more / 0 or 1 of the thing before |
| `{1,2}` | Between 1 and 2 of the thing before |
| `(...)` | Capture group (remembered, can be reused as `\1` or `match.group(1)`) |
| `(?:...)` | Group **without** capturing (just for grouping alternatives) |
| `(?P<name>...)` | Named capture group, read back with `match.group("name")` |
| `a\|b` | `a` or `b` |
| `^` / `$` | Start / end of the string |
| `\b` | Word boundary (between a word character and a non-word character) |
| `(?=...)` | Lookahead: "followed by ...", without consuming it |
| `(?<=...)` | Lookbehind: "preceded by ...", without consuming it |
| `re.IGNORECASE` | Case-insensitive matching |
| `r"..."` | Raw string: backslashes are kept as-is, so `\b` reaches the regex engine |

`re.sub(pattern, replacement, text)` replaces matches; `re.findall` returns all matches;
`re.finditer` returns match objects (with `.start()`, `.end()`, `.group()`).

## 6. Audio as numbers

The microphone produces **samples**: numbers between -1.0 and 1.0 describing the air
pressure, 16,000 per second (`SAMPLE_RATE = 16_000`; the `_` is just a digit separator).
So 1 second of audio is a NumPy array of 16,000 `float32` values, and
"sample 24,000" means "1.5 seconds in". Throughout the code, positions in audio are counted
in samples, and converted to seconds by dividing by `SAMPLE_RATE`.
