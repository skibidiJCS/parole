"""Decide whether a dictation needs a space in front of it.

Without this, two dictations in a row are glued together:
"Hello there.How are you?"

First choice: ask the focused text field, through the Accessibility API
(the same permission Parole uses to paste), which character sits just
before the cursor. Add a space after a letter or punctuation; not at the
start of a field, after a space or newline, or after an opening bracket.

Some apps (VS Code, some web pages) don't answer. Then we fall back to:
"did the previous dictation go into this same app less than a minute ago?"
"""

import time

from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCopyParameterizedAttributeValue,
    AXUIElementCreateSystemWide,
    AXUIElementSetMessagingTimeout,
    AXValueCreate,
    AXValueGetValue,
    kAXErrorSuccess,
    kAXFocusedUIElementAttribute,
    kAXSelectedTextRangeAttribute,
    kAXStringForRangeParameterizedAttribute,
    kAXValueAttribute,
    kAXValueCFRangeType,
)

NO_SPACE_AFTER = "([{«“‘/-"  # characters that a following word sticks to
RECENT_SECONDS = 60  # fallback: how long the previous dictation counts as "just before"
AX_TIMEOUT = 0.1  # seconds; never let a slow app delay the paste for long


def _attribute(element, name):
    error, value = AXUIElementCopyAttributeValue(element, name, None)
    return value if error == kAXErrorSuccess else None


def char_before_cursor():
    """The character before the cursor in the focused field.

    Returns "" at the start of the field, or None if the app doesn't say.
    """
    system = AXUIElementCreateSystemWide()
    AXUIElementSetMessagingTimeout(system, AX_TIMEOUT)
    field = _attribute(system, kAXFocusedUIElementAttribute)
    return None if field is None else char_before_selection(field)


def char_before_selection(field):
    """The character before the cursor (or selection) in an Accessibility text element."""
    selection = _attribute(field, kAXSelectedTextRangeAttribute)
    if selection is None:
        return None
    ok, (start, _length) = AXValueGetValue(selection, kAXValueCFRangeType, None)
    if not ok:
        return None
    if start == 0:
        return ""
    # Ask for just that one character, so huge documents aren't copied over.
    one_char = AXValueCreate(kAXValueCFRangeType, (start - 1, 1))
    error, text = AXUIElementCopyParameterizedAttributeValue(
        field, kAXStringForRangeParameterizedAttribute, one_char, None
    )
    if error == kAXErrorSuccess and text:
        return str(text)
    # Some fields only expose their whole text.
    value = _attribute(field, kAXValueAttribute)
    if isinstance(value, str) and start <= len(value):
        return value[start - 1]
    return None


def wants_space(before):
    """Space rule for a known character before the cursor."""
    return before != "" and not before.isspace() and before not in NO_SPACE_AFTER


def frontmost_app():
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.processIdentifier() if app else None


class Spacer:
    def __init__(self):
        self._last_app = None
        self._last_time = 0.0

    def prefix(self):
        """Return " " if the next dictation should start with a space, else ""."""
        try:
            before = char_before_cursor()
        except Exception:
            before = None  # an app answered something unexpected; use the fallback
        if before is not None:
            return " " if wants_space(before) else ""
        recent = time.monotonic() - self._last_time < RECENT_SECONDS
        return " " if recent and frontmost_app() == self._last_app else ""

    def pasted(self):
        """Remember where and when the dictation went, for the fallback."""
        self._last_app = frontmost_app()
        self._last_time = time.monotonic()
