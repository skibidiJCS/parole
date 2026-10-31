"""The Shift + Right Command hold-to-talk shortcut.

pynput calls our handlers from its own thread for every key event. We keep a
set of the relevant keys currently held and report two moments:
  - on_start: the moment Right Command and a Shift are both down (either order)
  - on_stop:  the moment either part is let go
Key-repeat events while holding are ignored. `released` is set once *all*
shortcut keys are up; pasting waits for it, because a still-held Shift would
turn Cmd+V into Cmd+Shift+V.
"""

import threading

from ApplicationServices import AXIsProcessTrusted
from pynput import keyboard
from pynput._util.darwin import keycode_context

HOTKEY = keyboard.Key.cmd_r  # Right Command
SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
SHORTCUT_KEYS = SHIFT_KEYS | {HOTKEY}


class _Listener(keyboard.Listener):
    """pynput's macOS listener, but it reads the keyboard layout on the main thread.

    pynput reads the current keyboard layout (to turn key codes into letters)
    at the start of its own thread. Once an AppKit app like our menu bar owns
    the main thread, macOS crashes the process if that happens off the main
    thread. So we read it here, in __init__ (called on the main thread), and
    skip pynput's own _run() wrapper that would read it again.
    Relies on pynput 1.8.2 internals; recheck if pynput is upgraded.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        with keycode_context() as context:
            self._layout = context

    def _run(self):
        self._context = self._layout
        super(keyboard.Listener, self)._run()  # the event loop, without the layout lookup


class Shortcut:
    def __init__(self, on_start, on_stop):
        self.on_start = on_start
        self.on_stop = on_stop
        self.held = set()
        self.active = False
        self.released = threading.Event()
        self.released.set()
        self._listener = _Listener(on_press=self._on_press, on_release=self._on_release)

    @property
    def trusted(self):
        """False if macOS hasn't granted Accessibility to the process.

        Asks macOS directly: pynput's own IS_TRUSTED is only filled in once
        its thread is running, so right after start() it still reads False.
        """
        return AXIsProcessTrusted()

    def start(self):
        self._listener.start()

    def stop(self):
        self._listener.stop()

    def _complete(self):
        return HOTKEY in self.held and bool(self.held & SHIFT_KEYS)

    def _on_press(self, key):
        if key not in SHORTCUT_KEYS:
            return
        self.held.add(key)
        self.released.clear()
        if self._complete() and not self.active:
            self.active = True
            self.on_start()

    def _on_release(self, key):
        self.held.discard(key)
        if not self.held & SHORTCUT_KEYS:
            self.released.set()
        if self.active and not self._complete():
            self.active = False
            self.on_stop()
