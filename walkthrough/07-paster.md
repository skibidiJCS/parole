# paster.py — pasting the text

[paster.py](../paster.py) types the dictation into the focused app by putting it on the
clipboard and pressing Cmd+V, then puts back whatever was on your clipboard before.

---

## Lines 1–14: docstring and imports

```python
import time
from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString   # clipboard
from ApplicationServices import AXIsProcessTrusted                          # permission check
from Foundation import NSData                                               # raw bytes
from Quartz import (
    CGEventCreateKeyboardEvent,   # create a fake key event
    CGEventPost,                  # send it to the system
    CGEventSetFlags,              # set modifier keys (Command) on it
    kCGEventFlagMaskCommand,      # the "Command is held" flag
    kCGHIDEventTap,               # where to inject: as if from the hardware keyboard
)
```

## Lines 16–17: constants

```python
PASTE_DELAY = 0.2  # seconds to wait so the app has read the clipboard before we restore it
V_KEY = 9          # macOS key code of the physical V key
```
Key codes identify physical keys, not letters. Code 9 is the V position on both QWERTY and
AZERTY, so Cmd+V works on either.

## Lines 20–30: `send_cmd_v`

```python
for is_down in (True, False):
    event = CGEventCreateKeyboardEvent(None, V_KEY, is_down)
    CGEventSetFlags(event, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, event)
```
Two events: V pressed (`True`), then V released (`False`), each with the Command flag set.
`None` = no special event source. The docstring explains why this uses Quartz directly rather
than pynput: pynput would look up the keyboard layout, which macOS only allows on the main
thread, and we paste from the worker thread.

## Lines 33–45: `copy_items`

Before replacing the clipboard, make **independent copies** of everything on it — text,
images, files, all formats.

```python
copies = []
for original in pasteboard.pasteboardItems() or []:
```
A clipboard holds a list of items (usually one); `or []` handles `None` (empty clipboard).

```python
    item = NSPasteboardItem.alloc().init()
    for kind in original.types():
```
A new empty item, then each format ("type") the original offers (e.g. plain text, RTF, PNG).

```python
        data = original.dataForType_(kind)
        if data is None:
            raise RuntimeError("Could not preserve a clipboard format; paste cancelled.")
        if not item.setData_forType_(NSData.dataWithData_(data), kind):
            raise RuntimeError("Could not copy a clipboard format; paste cancelled.")
    copies.append(item)
return copies
```
Read the bytes of that format, copy them (`NSData.dataWithData_` makes a new independent
copy), and store them in the new item. If anything can't be preserved, refuse to paste
rather than lose your clipboard.

## Lines 48–82: `paste_text`

```python
if not text:
    return None
if not AXIsProcessTrusted():
    raise PermissionError("Allow Parole ... in System Settings > Privacy & Security > ... (Accessibility) ...")
```
Nothing to paste → nothing to do. Without Accessibility permission, macOS silently ignores fake
key events, so fail with a helpful message instead.

```python
pasteboard = NSPasteboard.generalPasteboard()
before_clear = pasteboard.changeCount()
saved = copy_items(pasteboard)
if pasteboard.changeCount() != before_clear:
    raise RuntimeError("Clipboard changed; paste cancelled. Please try again.")
```
`changeCount()` is a number macOS increases every time the clipboard's contents change. If it
changed while we were copying, our copy might be a mix of old and new → give up. (The comment
notes that reading the data also forces apps that provide data "lazily" to actually supply it.)

```python
owned_change = pasteboard.clearContents()
```
Empty the clipboard. `clearContents()` returns the new change count.

```python
try:
    written = pasteboard.setString_forType_(text, NSPasteboardTypeString)
    owned_change = pasteboard.changeCount()
    if not written:
        raise RuntimeError("Could not put the dictation on the clipboard.")
    send_cmd_v()
    paste_sent_at = time.perf_counter()
    time.sleep(PASTE_DELAY)
    return paste_sent_at
```
Write the text as plain text, note the change count that belongs to *our* write, press Cmd+V,
note the time (for the latency log), and wait 0.2 s so the app reads the clipboard before we
restore it.

```python
finally:
    if pasteboard.changeCount() == owned_change:
        pasteboard.clearContents()
        if saved and not pasteboard.writeObjects_(saved):
            raise RuntimeError("Could not restore the previous clipboard.")
```
Always runs (success or error). If the count is still ours, nobody copied anything in the
meantime, so restore the saved items. If it changed, **you** copied something during those
0.2 s, and it's left alone. If the clipboard was empty before (`saved` is `[]`), it's just
left empty.
