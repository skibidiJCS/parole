# vocabulary.py — your custom words

[vocabulary.py](../vocabulary.py) manages
`~/Library/Application Support/Parole/vocabulary.txt`, a plain text file with two kinds of
lines:

```
Kubernetes            a word to expect
Jack-eye -> Jiacai    a replacement
```

Words (including the right side of replacements) become Whisper's **prompt** — text Whisper
reads as if it had been said just before, which nudges it towards those spellings. Because
that's only a hint, replacements are also applied to the result afterwards as a guaranteed
fix. learning.py adds lines to this file.

---

## Lines 19–35: imports and constants

```python
import os, re, threading

PATH = os.path.expanduser("~/Library/Application Support/Parole/vocabulary.txt")
ARROW = "->"
TEMPLATE = """\
# Parole vocabulary: ...
Parole
"""
LEARNED_HEADER = "# Learned from your corrections (delete a line to undo it):"
```
`TEMPLATE` is the file's initial content: instructions as `#` comments, then one word,
"Parole". The `\` right after the opening `"""` prevents the string from starting with a
newline.

## Lines 38–41: `heard_pattern`

```python
parts = re.split(r"[\s-]+", heard.strip())
return re.compile(r"\b" + r"[\s-]*".join(re.escape(part) for part in parts) + r"\b", re.IGNORECASE)
```
Build a regex for a misheard phrase where spaces and hyphens between its parts are optional.
`"Jack-eye"` → parts `["Jack", "eye"]` → pattern `\bJack[\s-]*eye\b`, which matches
"Jack-eye", "Jack eye", "Jackeye", "jack eye"... `re.escape` protects any special characters
(like `.` or `+`) in the words. `\b` at both ends: whole words only.

## Lines 44–50: `__init__`

```python
self.path = path
self._modified = None       # the file's modification time when we last read it
self._words = []            # words for the prompt
self._replacements = []     # (compiled pattern, replacement text) pairs
self._lock = threading.Lock()  # the worker and the learner's timer thread both use this
```

## Lines 52–57: `ensure_file`

```python
if not os.path.exists(self.path):
    os.makedirs(os.path.dirname(self.path), exist_ok=True)
    with open(self.path, "w") as file:
        file.write(TEMPLATE)
```
Create the folder (and any missing parents; `exist_ok=True` = no error if it exists) and the
file with the template, only the first time. `with open(...)` closes the file automatically.

## Lines 59–64: `prompt`

```python
with self._lock:
    self._refresh()
    words = list(dict.fromkeys(self._words + list(extra)))
return ", ".join(words) + "." if words else ""
```
Re-read the file if it changed, combine its words with `extra` (the terms near the cursor),
remove duplicates keeping order, and join: `"Parole, Kubernetes, Jiacai."`.

## Lines 66–70: `words`

Returns a copy (`list(...)`) of the words, so the caller can't change the internal list.

## Lines 72–79: `fix`

```python
with self._lock:
    self._refresh()
    replacements = self._replacements
for pattern, wanted in replacements:
    text = pattern.sub(wanted, text)
return text
```
Get the current replacements under the lock, then apply each to the text outside the lock
(`_refresh` builds a *new* list rather than modifying the old one, so this is safe).

## Lines 81–97: `learn`

```python
with self._lock:
    self._refresh()
    if any(pattern.fullmatch(heard) for pattern, _ in self._replacements):
        return False
```
If an existing replacement already matches this whole phrase, don't add a duplicate.

```python
    self.ensure_file()
    with open(self.path) as file:
        content = file.read()
    with open(self.path, "a") as file:
        if content and not content.endswith("\n"):
            file.write("\n")
        if LEARNED_HEADER not in content:
            file.write("\n" + LEARNED_HEADER + "\n")
        file.write(f"{heard} {ARROW} {wanted}\n")
    self._modified = None
    return True
```
Read the file, then open it in **append** mode (`"a"`: writes go to the end). Make sure we
start on a new line, add the "Learned..." header the first time, then the new line
`Jack-eye -> Jiacai`. Setting `_modified = None` forces a re-read next time.

## Lines 99–124: `_refresh`

```python
try:
    modified = os.path.getmtime(self.path)
except FileNotFoundError:
    self._words, self._replacements = [], []
    return
if modified == self._modified:
    return
```
`getmtime` = the time the file was last saved. If the file was deleted, use no words. If it
hasn't changed since the last read, keep what we have. This is how edits apply to the next
dictation without restarting.

```python
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
self._words = words
self._replacements = replacements
self._modified = modified
```
Go through the file line by line. Skip blank lines and comments. A line with `->` is split at
the first arrow (`split(ARROW, 1)`) into the two sides, both stripped; the right side also
becomes a prompt word. Any other line is a word. Finally store the results and the timestamp.
