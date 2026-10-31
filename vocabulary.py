"""Custom vocabulary: names, jargon and acronyms Whisper should spell your way.

The words live in a plain text file you edit (menu > Edit vocabulary…).
They're joined into a short "prompt": text Whisper reads as if it had been
said just before your dictation, which makes it reuse those spellings.
It's a hint, not a rule: it helps most with words Whisper half-recognises.
"""

import os

PATH = os.path.expanduser("~/Library/Application Support/Parole/vocabulary.txt")
TEMPLATE = """\
# Parole vocabulary: names, jargon and acronyms, one per line,
# written exactly as you want them to appear.
# Lines starting with # are ignored. Changes apply to your next dictation.
# Keep it to a few dozen entries: Whisper only reads the last ~200 tokens.
Parole
"""


class Vocabulary:
    def __init__(self, path=PATH):
        self.path = path
        self._modified = None  # file timestamp when we last read it
        self._prompt = ""

    def ensure_file(self):
        """Create the file with instructions the first time."""
        if not os.path.exists(self.path):
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as file:
                file.write(TEMPLATE)

    def prompt(self):
        """Return the Whisper prompt for the file as it is now ("" if empty).

        Re-reads the file only when it has been saved since last time, so
        edits apply immediately without restarting Parole.
        """
        try:
            modified = os.path.getmtime(self.path)
        except FileNotFoundError:
            return ""
        if modified != self._modified:
            with open(self.path) as file:
                words = [line.strip() for line in file if line.strip() and not line.lstrip().startswith("#")]
            self._prompt = ", ".join(words) + "." if words else ""
            self._modified = modified
        return self._prompt
