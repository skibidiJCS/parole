# hotkey.py — the Shift + Right Command shortcut

[hotkey.py](../hotkey.py) watches the keyboard (through the `pynput` library) and tells
parole.py when the shortcut starts, stops, or turns out to be part of another shortcut.

---

## Lines 1–12: docstring

pynput calls our handlers from **its own thread** for every key event. We keep a set of the
shortcut keys currently held and report:
- `on_start` – Right Command and a Shift are both down (in either order);
- `on_stop` – either one is let go;
- `on_cancel` – another key was pressed while holding them (e.g. Shift+Cmd+4).

Holding a key makes macOS send repeated "press" events; those are ignored. `released` is a
flag set once *all* shortcut keys are up; pasting waits for it.

## Lines 14–22: imports and constants

```python
import threading
from ApplicationServices import AXIsProcessTrusted   # "do we have Accessibility permission?"
from pynput import keyboard                          # keyboard listener
from pynput._util.darwin import keycode_context      # pynput internal: reads the keyboard layout

HOTKEY = keyboard.Key.cmd_r                          # Right Command
SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
SHORTCUT_KEYS = SHIFT_KEYS | {HOTKEY}                # union: all four keys
```
pynput may report Shift as `shift`, `shift_l` or `shift_r`, so all three count.

## Lines 25–43: `class _Listener(keyboard.Listener)`

A small subclass of pynput's listener, to work around a crash.

The problem (docstring): pynput reads the current keyboard layout (to turn key codes into
letters) at the start of its own thread. Once an AppKit app owns the main thread, macOS kills
the process if that is done off the main thread.

```python
def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    with keycode_context() as context:
        self._layout = context
```
`*args, **kwargs` accept any positional and keyword arguments and pass them on unchanged to
pynput's own constructor. `__init__` runs where the object is created — on the main thread
(parole.py creates `Shortcut` in `Parole.__init__`) — so the layout is read there, safely, and
stored.

```python
def _run(self):
    self._context = self._layout
    super(keyboard.Listener, self)._run()
```
`_run` is what pynput executes on its thread. pynput's version would read the layout again;
ours puts the saved one where pynput expects it (`self._context`) and then calls the `_run` of
the class **above** `keyboard.Listener` in the inheritance chain. `super(SomeClass, self)`
means "start looking for the method after `SomeClass`", so pynput's own layout-reading `_run`
is skipped and only the event loop runs. The docstring warns this depends on pynput 1.8.2
internals.

## Lines 46–55: `Shortcut.__init__`

```python
def __init__(self, on_start, on_stop, on_cancel=lambda: None):
```
The three callbacks. `on_cancel` defaults to a function that does nothing.

```python
    self.held = set()               # shortcut keys currently down
    self.active = False             # True between on_start and on_stop/on_cancel
    self.released = threading.Event()
    self.released.set()             # at first, no keys are held
    self._listener = _Listener(on_press=self._on_press, on_release=self._on_release)
```

## Lines 57–64: `trusted`

```python
@property
def trusted(self):
    return AXIsProcessTrusted()
```
`@property` lets callers write `self.shortcut.trusted` without parentheses. Asks macOS directly
whether Accessibility is granted (pynput's own flag isn't ready right after start).

## Lines 66–70: `start`, `stop`

Start / stop pynput's listener thread.

## Lines 72–73: `_complete`

```python
return HOTKEY in self.held and bool(self.held & SHIFT_KEYS)
```
`True` when Right Command is held **and** at least one Shift is (`&` = set intersection; an
empty set is falsy).

## Lines 75–85: `_on_press`

```python
def _on_press(self, key):
    if key not in SHORTCUT_KEYS:
        if self.active:
            self.active = False
            self.on_cancel()
        return
```
Another key: if the shortcut was active, it was part of a different combination → cancel.

```python
    self.held.add(key)
    self.released.clear()
    if self._complete() and not self.active:
        self.active = True
        self.on_start()
```
A shortcut key: add it to the set (adding a key already there does nothing, which is how key
repeat is ignored), mark "keys are held", and if both parts are now down and we hadn't
started yet, start.

## Lines 87–93: `_on_release`

```python
def _on_release(self, key):
    self.held.discard(key)               # remove it (discard doesn't fail if absent)
    if not self.held & SHORTCUT_KEYS:
        self.released.set()              # nothing held any more
    if self.active and not self._complete():
        self.active = False
        self.on_stop()                   # one part let go: stop
```
