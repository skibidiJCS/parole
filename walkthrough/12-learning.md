# learning.py — learning from your corrections

[learning.py](../learning.py) watches the spot where a dictation was pasted for two minutes.
If you fix a word or two (and then leave it alone), each fix that looks like a **mishearing**
is saved to the vocabulary as a replacement:

```
pasted "I met Jack-eye today."  →  you fix it to  "I met Jiacai today."
vocabulary.txt gets "Jack-eye -> Jiacai"
```

What counts as a mishearing (anything else is just you editing): at most 3 words swapped for
at most 3 words; the two still look alike; not just a plural/verb ending; not only common
short words ("then" → "than"); and the rest of the dictation is still there.

---

## Lines 22–41: imports and constants

```python
import threading, time, unicodedata
from difflib import SequenceMatcher        # standard library: compares sequences
import ax
from cleanup import LINKING_STARTS, OPEN_ENDINGS

CHECK_EVERY = 10    # look at the spot every 10 s
WATCH_FOR = 120     # for 2 minutes after the paste
ANCHOR = 40         # characters before/after the dictation used to find it again
MAX_WORDS = 3
MIN_LIKENESS = 0.4  # minimum letter similarity (0 = nothing in common, 1 = identical)
MIN_KEPT = 0.5      # at least half the dictation's words must still be there
PUNCTUATION = ".,;:!?…\"'“”«»()[]"
COMMON = OPEN_ENDINGS | LINKING_STARTS | set("""then than there ...""".split())
```
`COMMON` is a big set of short, frequent words (the two sets from cleanup.py plus homophones
like then/than, its/it's, ça/sa). Changing only these is grammar, not a mishearing.

## Lines 44–45: `words`

```python
return [w.strip(PUNCTUATION) for w in text.split() if w.strip(PUNCTUATION)]
```
Split into words with surrounding punctuation removed, dropping tokens that were only
punctuation.

## Lines 48–53: `compact`

```python
text = "".join(c for c in phrase.lower() if c.isalnum())
if not accents:
    text = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
return text
```
Lowercase, keep only letters and digits: `"Jack-eye"` → `"jackeye"`. With `accents=False`,
remove accents too: **NFD** normalisation splits `"é"` into `"e"` + a separate "combining
accent" character, and `unicodedata.combining(c)` is non-zero for those, so they're dropped:
`"été"` → `"ete"`.

## Lines 56–64: `is_mishearing`

```python
a, b = compact(heard), compact(wanted)
if a == b or len(a) < 3:
    return False
```
Only capitals/spaces/hyphens changed, or too short to judge → no.

```python
if a.startswith(b) or b.startswith(a):
    return False
```
One is the start of the other ("test"/"tests", "decide"/"decided") → a grammar fix.

```python
if all(word.lower() in COMMON for word in heard.split()):
    return False
```
Every original word is a common word → no.

```python
return SequenceMatcher(None, compact(heard, False), compact(wanted, False)).ratio() >= MIN_LIKENESS
```
`SequenceMatcher(...).ratio()` measures how similar two strings are (2 × matching characters ÷
total characters). Compared without accents. `"jackeye"` vs `"jiacai"` ≈ 0.46 → yes;
`"car"` vs `"vehicle"` is low → a rewrite, not a mishearing. The `None` first argument means
"no characters are junk".

## Lines 67–83: `corrections`

```python
old, new = words(pasted), words(edited)
matcher = SequenceMatcher(None, old, new, autojunk=False)
```
This time `SequenceMatcher` compares **lists of words**. `autojunk=False` turns off a
heuristic that ignores very frequent items in long sequences.

```python
kept = sum(block.size for block in matcher.get_matching_blocks())
if len(old) > MAX_WORDS and kept < MIN_KEPT * len(old):
    return []
```
`get_matching_blocks()` lists the runs of words that are the same in both; summing their sizes
gives how many words survived. If less than half did (and the dictation was more than 3 words),
you rewrote it → learn nothing.

```python
found = []
for op, i1, i2, j1, j2 in matcher.get_opcodes():
    if op != "replace" or i2 - i1 > MAX_WORDS or j2 - j1 > MAX_WORDS:
        continue
```
`get_opcodes()` describes how to turn `old` into `new` as steps
`(operation, i1, i2, j1, j2)`: `"equal"`, `"insert"`, `"delete"` or `"replace"` —
"replace `old[i1:i2]` with `new[j1:j2]`". Only small replacements are interesting.

```python
    if i2 - i1 == j2 - j1:
        pairs = list(zip(old[i1:i2], new[j1:j2]))
    else:
        pairs = [(" ".join(old[i1:i2]), " ".join(new[j1:j2]))]
    found += [(heard, wanted) for heard, wanted in pairs if is_mishearing(heard, wanted)]
return found
```
Same number of words on both sides → treat as word-for-word fixes ("ete tres" → "été très" is
two). Different numbers → one phrase fix ("cube and eighties" → "Kubernetes"). Keep only pairs
that look like mishearings.

## Lines 86–111: `class Spot`

Remembers where a dictation went.

```python
def __init__(self, context, pasted):
    self.field, self.start = context.field, context.start
    self.prefix, self.suffix = context.before[-ANCHOR:], context.after[:ANCHOR]
    self.known = pasted.strip()
    self.seen = None
    self.until = time.monotonic() + WATCH_FOR
```
- The field and cursor position at paste time.
- `prefix` / `suffix`: the 40 characters just before and after — used to find the dictation
  again even if text moved.
- `known`: the version we last learned from (at first, the paste itself).
- `seen`: what the previous check found.
- `until`: when to stop watching. `time.monotonic()` is a clock that never jumps backwards
  (unaffected by changing the system time) — right for deadlines.

```python
def read(self):
    count = ax.character_count(self.field)
    if count is None:
        return None
    first = max(0, self.start - len(self.prefix) - 500)
    last = min(count, self.start + 4 * len(self.known) + len(self.suffix) + 500)
    text = ax.text(self.field, first, last - first)
    if text is None:
        return None
```
Read a region around the original spot, with 500 characters of slack on each side (you may
have typed before it) and room for the dictation to grow up to 4× in length.

```python
    begin = text.find(self.prefix)
    if begin < 0:
        return None
    begin += len(self.prefix)
    end = text.find(self.suffix, begin) if self.suffix else len(text)
    return text[begin:end].strip() if end >= 0 else None
```
Find the prefix; the dictation starts right after it. Find the suffix after that; the
dictation ends there (or at the end of the region if there was no suffix). `find` returns −1
when not found, in which case we can't locate the dictation → `None`.

## Lines 114–169: `class Learner`

```python
def __init__(self, vocabulary, on_learned):
    self.vocabulary, self.on_learned = vocabulary, on_learned
    self.lock = threading.Lock()
    self.spot, self.timer = None, None
```
The lock is needed because the timer thread and the worker thread both use `self.spot`.

### `watch` (lines 120–126)
```python
with self.lock:
    self._stop()
    if context.field is not None:
        self.spot = Spot(context, pasted)
        self._schedule()
```
Stop watching the previous dictation; if the app shares its text, start watching the new one.

### `finish` (lines 128–133)
Called just before the next paste: one last check (`final=True`), then stop. Without this,
fixes made in the last 10 seconds before the next dictation would be missed.

### `_schedule` (lines 135–138)
Start a 10-second `threading.Timer` that will call `_tick` (daemon, so it doesn't keep the app
alive).

### `_stop` (lines 140–143)
Cancel the timer if any and forget the spot.

### `_tick` (lines 145–153)
```python
with self.lock:
    if self.spot is None:
        return
    self._check()
    if self.spot is not None and time.monotonic() < self.spot.until:
        self._schedule()
    else:
        self._stop()
```
Runs on the timer thread every 10 s: check, then schedule the next check until the 2 minutes
are up. (The first `if` handles a timer that fired just as `_stop` was being called.)

### `_check` (lines 155–169)
```python
spot = self.spot
try:
    now = spot.read()
except Exception:
    now = None
if now is None or now == spot.known:
    spot.seen = now
    return
```
Read the dictation as it is now. Can't find it, or unchanged → nothing to learn.

```python
if final or now == spot.seen:
    for heard, wanted in corrections(spot.known, now):
        if self.vocabulary.learn(heard, wanted):
            self.on_learned(heard, wanted)
    spot.known = now
spot.seen = now
```
Only learn when the text **changed and then stayed the same** for a whole check (you finished
fixing it) — or on the final check. Then compare what we knew with what's there now, save each
mishearing, and notify parole.py for each new one. `known = now`, so the same fix isn't
learned twice and later fixes are compared against this version.
