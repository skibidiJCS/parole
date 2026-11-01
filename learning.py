"""Learn from your corrections.

After a paste, Parole remembers the text just around it (see context.py).
For the next two minutes it looks at that spot every CHECK_EVERY seconds.
When you've changed a word or two of the dictation and then left it alone
for a check, each change that looks like a mishearing is saved to your
vocabulary as a replacement:

    pasted "I met Jack-eye today."  you fix it to  "I met Jiacai today."
    -> vocabulary.txt gets "Jack-eye -> Jiacai", applied to every dictation

What counts as a mishearing (anything else is just you editing):
  - at most MAX_WORDS words swapped for at most MAX_WORDS words;
  - the two still look alike (misheard words share letters; "car" -> "vehicle"
    is a rewrite) and aren't just a plural or a verb ending ("test" -> "tests");
  - not only common short words ("then" -> "than" is right in one sentence and
    wrong in the next);
  - the rest of the dictation is still there (otherwise you rewrote it).
Learned lines sit at the end of the vocabulary file: delete one to undo it.
"""

import threading
import time
import unicodedata
from difflib import SequenceMatcher

import ax
from cleanup import LINKING_STARTS, OPEN_ENDINGS

CHECK_EVERY = 10  # seconds between looks at the spot
WATCH_FOR = 120  # seconds after the paste
ANCHOR = 40  # characters before/after the dictation used to find it again
MAX_WORDS = 3
MIN_LIKENESS = 0.4  # how alike the letters must be ("jackeye" / "jiacai": 0.46)
MIN_KEPT = 0.5  # share of the dictation's words still there
PUNCTUATION = ".,;:!?…\"'“”«»()[]"
COMMON = OPEN_ENDINGS | LINKING_STARTS | set(
    """then than there here hear its it's it your you're too two were where our hour are know no new knew one won
    right write see sea buy bye four not now how what this these those
    ça sa se ce ces ses où mes c'est s'est sont son pas plus""".split()
)


def words(text):
    return [w.strip(PUNCTUATION) for w in text.split() if w.strip(PUNCTUATION)]


def compact(phrase, accents=True):
    """"Jack-eye" -> "jackeye": lowercase, without spaces, hyphens or apostrophes."""
    text = "".join(c for c in phrase.lower() if c.isalnum())
    if not accents:  # "été" -> "ete", so a fixed accent still looks alike
        text = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    return text


def is_mishearing(heard, wanted):
    a, b = compact(heard), compact(wanted)
    if a == b or len(a) < 3:  # only capitals, spaces or hyphens changed; or too short to tell
        return False
    if a.startswith(b) or b.startswith(a):  # "test" -> "tests", "decide" -> "decided"
        return False
    if all(word.lower() in COMMON for word in heard.split()):
        return False
    return SequenceMatcher(None, compact(heard, False), compact(wanted, False)).ratio() >= MIN_LIKENESS


def corrections(pasted, edited):
    """The (heard, wanted) mishearings you fixed when `pasted` became `edited`."""
    old, new = words(pasted), words(edited)
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    kept = sum(block.size for block in matcher.get_matching_blocks())
    if len(old) > MAX_WORDS and kept < MIN_KEPT * len(old):
        return []  # rewritten, not corrected
    found = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op != "replace" or i2 - i1 > MAX_WORDS or j2 - j1 > MAX_WORDS:
            continue
        if i2 - i1 == j2 - j1:  # word for word: "ete tres" -> "été très" is two fixes
            pairs = list(zip(old[i1:i2], new[j1:j2]))
        else:  # "cube and eighties" -> "Kubernetes" is one
            pairs = [(" ".join(old[i1:i2]), " ".join(new[j1:j2]))]
        found += [(heard, wanted) for heard, wanted in pairs if is_mishearing(heard, wanted)]
    return found


class Spot:
    """Where a dictation went, and what it says now as far as we know."""

    def __init__(self, context, pasted):
        self.field, self.start = context.field, context.start
        self.prefix, self.suffix = context.before[-ANCHOR:], context.after[:ANCHOR]
        self.known = pasted.strip()  # what we last learned from (first: the paste itself)
        self.seen = None  # what the previous check found
        self.until = time.monotonic() + WATCH_FOR

    def read(self):
        """The dictation as it is in the field now, or None if we can't find it."""
        count = ax.character_count(self.field)
        if count is None:
            return None
        first = max(0, self.start - len(self.prefix) - 500)  # some slack for edits before it
        last = min(count, self.start + 4 * len(self.known) + len(self.suffix) + 500)
        text = ax.text(self.field, first, last - first)
        if text is None:
            return None
        begin = text.find(self.prefix)
        if begin < 0:
            return None
        begin += len(self.prefix)
        end = text.find(self.suffix, begin) if self.suffix else len(text)
        return text[begin:end].strip() if end >= 0 else None


class Learner:
    def __init__(self, vocabulary, on_learned):
        self.vocabulary, self.on_learned = vocabulary, on_learned
        self.lock = threading.Lock()  # the timer thread and the worker both use the spot
        self.spot, self.timer = None, None

    def watch(self, context, pasted):
        """Start watching a dictation that was just pasted."""
        with self.lock:
            self._stop()
            if context.field is not None:
                self.spot = Spot(context, pasted)
                self._schedule()

    def finish(self):
        """A last look at the previous dictation, before the next one is pasted."""
        with self.lock:
            if self.spot is not None:
                self._check(final=True)
            self._stop()

    def _schedule(self):
        self.timer = threading.Timer(CHECK_EVERY, self._tick)
        self.timer.daemon = True
        self.timer.start()

    def _stop(self):
        if self.timer is not None:
            self.timer.cancel()
        self.spot, self.timer = None, None

    def _tick(self):
        with self.lock:
            if self.spot is None:
                return
            self._check()
            if self.spot is not None and time.monotonic() < self.spot.until:
                self._schedule()
            else:
                self._stop()

    def _check(self, final=False):
        spot = self.spot
        try:
            now = spot.read()
        except Exception:
            now = None  # the field is gone, or the app answered something odd
        if now is None or now == spot.known:
            spot.seen = now
            return
        if final or now == spot.seen:  # changed, then left alone: you're done fixing it
            for heard, wanted in corrections(spot.known, now):
                if self.vocabulary.learn(heard, wanted):
                    self.on_learned(heard, wanted)
            spot.known = now
        spot.seen = now
