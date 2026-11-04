# context.py — the text around the cursor

[context.py](../context.py) reads the text just before and after your cursor (through
ax.py) and uses it three ways:
1. names and terms near the cursor ("Kubernetes", "Jiacai", "Q3") go into Whisper's prompt,
   so it spells them the same way;
2. the dictation is **fitted in**: no capital mid-sentence, no final period if text follows or
   in a one-line field (search box, subject line), a space after it;
3. learning.py watches the same spot later.

Apps that don't share their text (VS Code, many web pages) get none of this, and password
fields are never read.

---

## Lines 15–25: imports and constants

```python
import re
import ax
from cleanup import lowercase_first

BEFORE_CHARS, AFTER_CHARS = 2000, 300   # read up to 2000 characters before, 300 after
MAX_TERMS = 20                           # keep the 20 terms closest to the cursor
SINGLE_LINE = {"AXTextField", "AXSearchField", "AXComboBox"}   # one-line field roles
WORD = re.compile(r"\w[\w'’-]*\w|\w")
TERM_SKIP = {"I", "I'm", "I'll", "I've", "I'd"}
```
`WORD` matches a word: a word character, then any letters/apostrophes (straight `'` or curly
`’`)/hyphens, ending with a word character — or a single word character. So "rock-'n'-roll"
and "don’t" are one word, but a trailing hyphen isn't included.

## Lines 28–34: `class Context`

```python
def __init__(self, field=None, start=0, before="", after="", role=None):
    self.field = field     # the AX element of the text field (None = app doesn't share text)
    self.start = start     # character index where the cursor/selection starts
    self.before, self.after = before, after
    self.role = role       # e.g. "AXTextField"
    self.terms = find_terms(before + " " + after)
```
All arguments have defaults, so `Context()` is a valid "we know nothing" context.

## Lines 37–55: `read`

```python
try:
    field = ax.focused_element()
    if field is None or ax.is_secure(field):
        return Context()
```
No focused element, or it's a password field → empty context.

```python
    text_range, count = ax.selected_range(field), ax.character_count(field)
    if text_range is None or count is None:
        return Context()
    start, length = text_range
```
Where the cursor/selection is, and how long the text is.

```python
    first = max(0, start - BEFORE_CHARS)
    before = ax.text(field, first, start - first)
    end = start + length
    after = ax.text(field, end, min(AFTER_CHARS, count - end))
```
Read up to 2000 characters ending at the cursor, and up to 300 starting after the selection
(`count - end` = characters left until the end of the text). If text is selected, the
selection itself is neither "before" nor "after" (it will be replaced by the paste).

```python
    if before is None or after is None:
        return Context()
    return Context(field, start, before, after, ax.role(field))
except Exception:
    return Context()
```
Any odd answer from an app → carry on without context.

## Lines 58–71: `find_terms`

```python
terms = []
for match in WORD.finditer(text):
    word = match.group()
    mid_sentence = text[: match.start()].rstrip()[-1:] not in ("", ".", "!", "?", "…", "\n", ":", "\"", "“", "«")
```
For each word, look at the last non-space character before it. If there is none, or it's
sentence punctuation, a colon or an opening quote, the word starts a sentence.

> Small quirk: `.rstrip()` also removes newlines, so the `"\n"` in that tuple can never match.
> A capitalised word at the start of a new line therefore counts as "mid-sentence" if the
> previous line didn't end with punctuation. E.g. `"Hello there\nThe plan..."` makes "The" a
> term (tested). Harmless — it only adds a word to Whisper's prompt.

```python
    capital = word[0].isupper() and mid_sentence
    unusual = any(c.isupper() for c in word[1:]) or (any(c.isdigit() for c in word) and any(c.isalpha() for c in word))
    if (capital or unusual) and word not in TERM_SKIP:
        terms.append(word)
```
A word is a term if it's capitalised mid-sentence (a name), or "unusual": a capital after the
first letter ("iPhone", "MLX") or a mix of letters and digits ("Q3"). "I", "I'm"... are
skipped.

```python
return list(dict.fromkeys(reversed(terms)))[:MAX_TERMS]
```
Reverse so the words closest to the cursor (the end of `before`... then `after`) come first,
remove duplicates keeping the first occurrence (`dict.fromkeys` keeps insertion order), and
keep 20.

## Lines 74–87: `fit`

```python
last = context.before.rstrip(" \t")[-1:]
if last and (last.isalnum() or last in ",;"):
    text = lowercase_first(text, keep=set(names) | set(context.terms))
```
The last character before the cursor, ignoring spaces and tabs. If it's a letter, digit,
comma or semicolon, you're mid-sentence: lowercase the dictation's first letter — unless that
first word is one of your vocabulary words or a term near the cursor (a name).

```python
first = context.after.lstrip(" \t")[:1]
carries_on = first and (first.islower() or first in ",.;:!?)")
if (carries_on or context.role in SINGLE_LINE) and text.endswith(".") and not text.endswith(".."):
    text = text[:-1]
return text
```
If the text after the cursor continues the sentence (starts lowercase or with punctuation),
or the field is one line, remove the dictation's final period — but not from an ellipsis
`"..."`.

## Lines 90–97: `space_after`

```python
following = context.after[:1]
return "" if following and not following.isalnum() else " "
```
Add a space after the dictation unless the next character is already a space or punctuation.
(The docstring says "None", but the function returns an empty string `""`, which is what the
caller needs for `text + ...`.)
