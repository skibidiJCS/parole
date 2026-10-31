"""Custom vocabulary: names, jargon and acronyms Whisper should spell your way.

The words live in a plain text file you edit (menu > Edit vocabulary…).
Two kinds of lines:

    Kubernetes            a word to expect
    Jack-eye -> Jiacai    a replacement: whenever the transcript says
                          "Jack-eye" (or "Jack eye", "jackeye"...), write "Jiacai"

Words (including the right side of replacements) are joined into a short
"prompt": text Whisper reads as if it had been said just before your
dictation, which makes it reuse those spellings. That's only a hint, so the
replacements are applied afterwards as a guaranteed fix for words Whisper
keeps hearing the same wrong way.
"""

import os
import re

PATH = os.path.expanduser("~/Library/Application Support/Parole/vocabulary.txt")
ARROW = "->"
TEMPLATE = """\
# Parole vocabulary: names, jargon and acronyms, one per line,
# written exactly as you want them to appear.
# If Whisper keeps writing a word the same wrong way, add a replacement:
#     Jack-eye -> Jiacai
# (it also catches "Jack eye", "Jackeye" and any capitalisation).
# Lines starting with # are ignored. Changes apply to your next dictation.
# Keep it to a few dozen entries: Whisper only reads the last ~200 tokens.
Parole
"""


def heard_pattern(heard):
    """Regex for a misheard phrase; spaces and hyphens between its parts are optional."""
    parts = re.split(r"[\s-]+", heard.strip())
    return re.compile(r"\b" + r"[\s-]*".join(re.escape(part) for part in parts) + r"\b", re.IGNORECASE)


class Vocabulary:
    def __init__(self, path=PATH):
        self.path = path
        self._modified = None  # file timestamp when we last read it
        self._prompt = ""
        self._replacements = []  # (compiled pattern, replacement text)

    def ensure_file(self):
        """Create the file with instructions the first time."""
        if not os.path.exists(self.path):
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as file:
                file.write(TEMPLATE)

    def prompt(self):
        """Return the Whisper prompt for the file as it is now ("" if empty)."""
        self._refresh()
        return self._prompt

    def fix(self, text):
        """Apply the replacements to a transcript."""
        self._refresh()
        for pattern, wanted in self._replacements:
            text = pattern.sub(wanted, text)
        return text

    def _refresh(self):
        # Re-read only when the file has been saved since last time, so edits
        # apply immediately without restarting Parole.
        try:
            modified = os.path.getmtime(self.path)
        except FileNotFoundError:
            self._prompt, self._replacements = "", []
            return
        if modified == self._modified:
            return
        words, replacements = [], []
        with open(self.path) as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ARROW in line:
                    heard, wanted = (part.strip() for part in line.split(ARROW, 1))
                    if heard and wanted:
                        replacements.append((heard_pattern(heard), wanted))
                        words.append(wanted)
                else:
                    words.append(line)
        words = list(dict.fromkeys(words))  # drop duplicates, keep order
        self._prompt = ", ".join(words) + "." if words else ""
        self._replacements = replacements
        self._modified = modified
