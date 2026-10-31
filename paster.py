"""Paste dictation with Cmd+V, then restore every previous clipboard format."""

import time

from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
from ApplicationServices import AXIsProcessTrusted
from Foundation import NSData
from pynput import keyboard

PASTE_DELAY = 0.2  # Give the focused app time to read the temporary clipboard.


def copy_items(pasteboard):
    """Make independent copies before clearing the clipboard, including images/files."""
    copies = []
    for original in pasteboard.pasteboardItems() or []:
        item = NSPasteboardItem.alloc().init()
        for kind in original.types():
            data = original.dataForType_(kind)
            if data is None:
                raise RuntimeError("Could not preserve a clipboard format; paste cancelled.")
            if not item.setData_forType_(NSData.dataWithData_(data), kind):
                raise RuntimeError("Could not copy a clipboard format; paste cancelled.")
        copies.append(item)
    return copies


def paste_text(text):
    """Return the Cmd+V timestamp; preserve a newer copy made by the user."""
    if not text:
        return None
    if not AXIsProcessTrusted():
        raise PermissionError(
            "Enable Terminal in System Settings > Privacy & Security > "
            "Device Control and Data Access (Accessibility), then quit Terminal "
            "with Cmd+Q and reopen it."
        )

    pasteboard = NSPasteboard.generalPasteboard()
    before_clear = pasteboard.changeCount()
    saved = copy_items(pasteboard)
    # If the clipboard changed while reading it, leave it alone.
    # copy_items has already materialized any lazily provided data.
    controller = keyboard.Controller()
    if pasteboard.changeCount() != before_clear:
        raise RuntimeError("Clipboard changed; paste cancelled. Please try again.")

    owned_change = pasteboard.clearContents()
    try:
        written = pasteboard.setString_forType_(text, NSPasteboardTypeString)
        owned_change = pasteboard.changeCount()
        if not written:
            raise RuntimeError("Could not put the dictation on the clipboard.")
        with controller.pressed(keyboard.Key.cmd):
            controller.tap('v')
        paste_sent_at = time.perf_counter()
        time.sleep(PASTE_DELAY)
        return paste_sent_at
    finally:
        # Don't erase something the user copied while the paste was happening.
        if pasteboard.changeCount() == owned_change:
            pasteboard.clearContents()
            if saved and not pasteboard.writeObjects_(saved):
                raise RuntimeError("Could not restore the previous clipboard.")
