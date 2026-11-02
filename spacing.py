"""Decide whether a dictation needs a space in front of it.

Without this, two dictations in a row are glued together:
"Hello there.How are you?"

First choice: ask the focused text field (via Accessibility, see ax.py)
which character sits just before the cursor. Add a space after a letter or
punctuation; not at the start of a field, after a space or newline, or after
an opening bracket.

Some apps (VS Code, some web pages) don't answer. Then we fall back to:
"did the previous dictation go into this same app less than a minute ago,
without a space after it?" (context.space_after usually adds one already.)
"""

import time

from AppKit import NSWorkspace

import ax

NO_SPACE_AFTER = "([{«“‘/-"  # characters that a following word sticks to
RECENT_SECONDS = 60  # fallback: how long the previous dictation counts as "just before"


def char_before_cursor():
    """The character before the cursor in the focused field.

    Returns "" at the start of the field, or None if the app doesn't say.
    """
    field = ax.focused_element()
    text_range = ax.selected_range(field) if field is not None else None
    if text_range is None:
        return None
    start = text_range[0]
    return "" if start == 0 else ax.text(field, start - 1, 1)


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
        self._ended_with_space = False

    def prefix(self):
        """Return " " if the next dictation should start with a space, else ""."""
        try:
            before = char_before_cursor()
        except Exception:
            before = None  # an app answered something unexpected; use the fallback
        if before is not None:
            return " " if wants_space(before) else ""
        recent = time.monotonic() - self._last_time < RECENT_SECONDS
        return " " if recent and frontmost_app() == self._last_app and not self._ended_with_space else ""

    def pasted(self, text):
        """Remember where and when the dictation went, for the fallback."""
        self._last_app = frontmost_app()
        self._last_time = time.monotonic()
        self._ended_with_space = text[-1:].isspace()
