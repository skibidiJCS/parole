# cleanup.py — tidying the transcript

[cleanup.py](../cleanup.py) is pure text processing (no audio, no UI). It's the longest and
most regex-heavy file. parole.py calls it in this order:

```python
remove_repeats(apply_corrections(remove_fillers(text)))
```
plus `join_pieces` to glue together text transcribed on either side of a pause, and
`lowercase_first` (also used by context.py).

---

## Lines 1–30: docstring

Examples of what the module does:

| Input | Output |
|-------|--------|
| `Um, I- I think we should, we should leave.` | `I think we should leave.` |
| `Je je pense que, euh, je pense que c'est bon.` | `Je pense que c'est bon.` |
| `Let's meet on Tuesday, sorry, on Wednesday.` | `Let's meet on Wednesday.` |
| pieces `I think we should.` + `go tomorrow.` | `I think we should... go tomorrow.` |

Key ideas:
- **Fillers** like "um"/"euh" are dropped anywhere; "like", "you know", "genre", "tu vois"
  only between commas, so "I like it" stays. "Like" without commas is dropped only when
  Apple's grammar tagger says it's an interjection.
- **Repeats**: text is split into words, compared in a *normalised* form (lowercase, no
  punctuation). A run of 1–10 words immediately repeated loses its first copy (the second
  copy is kept because it carries on into the sentence; the capital letter is moved onto it).
- **Self-corrections** are recognised by the marker you say ("sorry", "I mean", "no wait",
  "je veux dire"...) set off by punctuation.

## Lines 32–42: imports

```python
import re
from NaturalLanguage import (
    NLTagger,                  # Apple's on-device grammar tagger
    NLTaggerOmitPunctuation,   # option: skip punctuation tokens
    NLTaggerOmitWhitespace,    # option: skip whitespace tokens
    NLTagInterjection,         # the tag for interjections ("oh", "wow", filler "like")
    NLTagVerb,                 # the tag for verbs
    NLTagSchemeLexicalClass,   # tag scheme: "part of speech" (noun, verb, ...)
    NLTokenUnitWord,           # tag word by word
)
```

## Lines 44–59: constants and patterns

```python
MAX_PHRASE = 10
```
Longest phrase (in words) checked for repeats.

```python
KEEP_DOUBLED = {"nous", "vous", "had", "that", "is", "very", "so", "no", "non", "oui", "yes", "ha", "haha", "bye"}
```
Single words that are legitimately doubled ("nous nous sommes", "he had had", "bye bye").

```python
GLUED_STUTTER = re.compile(r"\b(\w{1,2})-(\1)", re.IGNORECASE)
```
A stutter written with a hyphen and no space: "w-what", "th-the".
- `\b` – start of a word.
- `(\w{1,2})` – group 1: one or two letters (the fragment).
- `-` – a hyphen.
- `(\1)` – group 2: the **same** letters again (`\1` is a backreference to group 1; with
  `IGNORECASE`, "W-w" matches too).
Only the fragment, the hyphen and the repeated letters are matched: in "w-what" the match is
`w-w`; "hat" is untouched.

```python
REAL_PREFIXES = {"re", "co", "de", "ex", "un", "in", "bi"}
```
"re-read", "co-op" look like stutters but are real words.

```python
SENTENCE_END = ".!?"
```
Characters that end a sentence. ("..." is treated as a pause, see `ends_sentence`.)

```python
FILLER = re.compile(r"^(?:u+h+|u+h*m+|e+r+m*|h+m+|m+h?m+|m+h+|e+u+h+|h+e+u+|h+u+m+)$")
```
Matches a whole normalised word (`^...$`) that is a filler sound. Each alternative, with `+`
meaning "one or more" and `*` "zero or more":
- `u+h+` – uh, uhh, uuh
- `u+h*m+` – um, umm, uhm
- `e+r+m*` – er, err, erm
- `h+m+` – hm, hmm
- `m+h?m+` – mm, mhm
- `m+h+` – mh, mmh
- `e+u+h+` – euh (French)
- `h+e+u+` – heu (French)
- `h+u+m+` – hum

```python
COMMA_FILLERS = re.compile(r",\s+(?:like|you know|genre|tu vois),(\s+)", re.IGNORECASE)
```
`", like, "`, `", you know, "` etc.: a comma, spaces, the filler, a comma, and spaces captured
as group 1 (kept when replacing).

```python
LEADING_LIKE = re.compile(r"(^|[.!?]\s+)like,\s+(\w)", re.IGNORECASE)
```
"Like," at the start of the text or of a sentence. Group 1 = what came before it (nothing, or
the previous sentence's punctuation + space); group 2 = the first letter of the next word.

```python
QUOTING = {"was", "were", "is", "am", "are", "i'm", "he's", ...}
```
"I was like, okay" – here "like" means "said", so it stays.

```python
LIKE_I_SAID = re.compile(r"\s*(?:i|you|we|they|he|she) (?:said|say|mean|told)\b", re.IGNORECASE)
```
"like I said", "like you mean": also kept.

## Lines 62–64: `ends_sentence`

```python
def ends_sentence(token):
    token = token.rstrip()
    return token[-1:] in SENTENCE_END and not token.endswith(("...", "…"))
```
`True` if the word ends with `.`, `!` or `?` but not with an ellipsis. `endswith` accepts a
tuple of alternatives.

## Lines 67–69: `normalise`

```python
return re.sub(r"[^\w']", "", token.lower()).strip("'")
```
Lowercase, delete everything that isn't a letter/digit/apostrophe, then remove apostrophes at
the ends. `"Should,"` → `"should"`, `"I-"` → `"i"`, `"c'est"` stays `"c'est"`.

## Lines 72–77: `_unglue`

The replacement function for `GLUED_STUTTER`. `re.sub` calls it with each match object and
uses its return value as the replacement.

```python
fragment, start = match.group(1), match.group(2)
if fragment.lower() in REAL_PREFIXES:
    return match.group(0)          # the whole match unchanged: "re-read" stays
return start[0].upper() + start[1:] if fragment[0].isupper() else start
```
Replace `fragment-start` by just `start`, keeping a capital if the fragment had one:
"W-what" → match "W-w" → "W" → "What". "th-the" → "the".

## Lines 80–94: `remove_repeats`

```python
text = GLUED_STUTTER.sub(_unglue, text)
tokens = re.findall(r"\S+\s*", text)
words = [normalise(t) for t in tokens]
```
First fix glued stutters. Then split into tokens: each is a word **with the spaces after it**
(`\S+\s*`), so joining the tokens back gives exactly the original text. `words` holds the
normalised version of each token, at the same index.

```python
i = 0
while i < len(tokens):
    drop = _repeat_length(tokens, words, i)
    if drop:
        capital = tokens[i][:1].isupper()
        del tokens[i : i + drop], words[i : i + drop]
        if capital and tokens:
            tokens[i] = tokens[i][:1].upper() + tokens[i][1:]
        continue
    i += 1
return "".join(tokens).strip()
```
Walk through the words. If `drop` words starting at `i` are the first copy of a repeat,
delete them from both lists (`del a[x:y], b[x:y]` deletes two slices in one statement). The
second copy now sits at index `i`; give it the first copy's capital if needed. `continue`
without `i += 1` re-checks the same position: "the the the" needs two deletions.

## Lines 97–115: `_repeat_length`

```python
if i + 1 < len(tokens) and tokens[i].rstrip().endswith("-"):
    if words[i] and words[i + 1].startswith(words[i]):
        return 1
```
A cut-off word followed by a space: "th- the", "w- what". The token ends in "-" and the next
word starts with the same letters → drop the fragment. ("well-known" has no space, so it's one
token and never matches.)

```python
for n in range(MAX_PHRASE, 0, -1):
    first, second = words[i : i + n], words[i + n : i + 2 * n]
```
Try phrase lengths from 10 down to 1 (`range(10, 0, -1)` = 10, 9, ..., 1). Longest first, so
"we should, we should" is caught as one 2-word repeat rather than something smaller.
`first` = the `n` words from `i`; `second` = the `n` words right after.

```python
    if len(second) == n and first == second and all(first):
```
There must be `n` words left for the second copy, the two must be equal, and `all(first)`
requires every word to be non-empty (a token like "—" normalises to `""`, which is falsy).

```python
        if n == 1 and first[0] in KEEP_DOUBLED:
            continue
        if ends_sentence(tokens[i + n - 1]):
            continue
        return n
return 0
```
Skip legitimate doubles. Skip when the first copy ends a sentence ("C'est vrai. C'est vrai." is
probably on purpose). Otherwise return the number of words to drop.

## Lines 118–139: `remove_fillers`

```python
text = COMMA_FILLERS.sub(r"\1", text)
```
`"it was, like, huge"` → the match `", like, "` is replaced by group 1 (the spaces after it)
→ `"it was huge"`.

```python
text = LEADING_LIKE.sub(lambda m: m.group(1) + m.group(2).upper(), text)
```
`"Like, seriously"` → `"Seriously"`: keep what was before, drop "like, ", capitalise the next
letter.

```python
text = remove_filler_like(text)
```
Remove "like" used as a filler without commas (see below).

```python
kept, capitalize = [], False
for token in re.findall(r"\S+\s*", text):
    if not FILLER.match(normalise(token)):
        if capitalize:
            token, capitalize = token[:1].upper() + token[1:], False
        kept.append(token)
        continue
```
Go through the tokens. A normal word is kept; if the filler just removed had a capital
("Um, I think"), the capital moves onto this word.

For a filler token (it's **not** added to `kept`), fix the punctuation around the gap:
```python
    ending = token.rstrip()[-1:]           # the filler's last character, e.g. "," or "."
    if kept:
        previous = kept[-1].rstrip()       # previous kept word without trailing spaces
        spaces = kept[-1][len(previous) :] # just those trailing spaces
        if ending in SENTENCE_END:
            kept[-1] = previous.rstrip(",;:") + ending + spaces
        elif ending == "," and previous.endswith(","):
            kept[-1] = previous[:-1] + spaces
    capitalize = capitalize or token[:1].isupper()
return "".join(kept).strip()
```
- The filler ended a sentence ("We go, um.") → move its period onto the previous word,
  replacing a comma: "We go."
- Commas on both sides ("It's, uh, fine") → drop one: "It's fine".
- Remember whether the filler was capitalised.

## Lines 142–155: word lists for `join_pieces`

- `OPEN_ENDINGS` – English and French words a sentence can't end on ("the", "and", "to",
  "le", "que", ...). The triple-quoted string is split into a set with `.split()`. If the text
  before a pause ends with one, you were hesitating mid-sentence.
- `LINKING_STARTS` – words that carry a sentence on after a pause ("and", "but", "so",
  "then", "et", "mais", "donc"...).
- `KEEP_CAPITAL` – "I", "I'm", "I'll"... are always capitalised in English.

## Lines 158–171: `remove_filler_like`

```python
for start, end in reversed(_filler_likes(text)):
```
`_filler_likes` returns the positions of filler "like"s. They're processed **from the last to
the first**: removing text near the end doesn't shift the positions of earlier ones.

```python
    before, after = text[:start], text[end:]
    previous = normalise((before.split() or [""])[-1])
```
The text on either side, and the previous word (`(x.split() or [""])[-1]` gives `""` if there
is no previous word, instead of an IndexError).

```python
    if previous == "like" or normalise((after.split() or [""])[0]) == "like":
        continue
    if LIKE_I_SAID.match(after) or (after.startswith(",") and previous in QUOTING):
        continue
```
Leave it alone when next to another "like", in "like I said", or in "I was like, ...".

```python
    after = re.sub(r"^,?\s*", "", after)
    if not before.strip() or ends_sentence(before):
        after = after[:1].upper() + after[1:]
    text = before + after
return text
```
Remove an optional comma and spaces right after "like". If "like" started the text or a
sentence, capitalise the next word. Rebuild the text without "like".

## Lines 174–202: `_filler_likes`

```python
tagger = NLTagger.alloc().initWithTagSchemes_([NLTagSchemeLexicalClass])
tagger.setString_(text)
words = []
```
Create Apple's tagger for parts of speech and give it the text.

```python
def visit(tag, token_range, stop):
    start, end = token_range.location, token_range.location + token_range.length
    words.append((text[start:end], tag, start, end))
```
A nested function the tagger calls once per word. `token_range` is an `NSRange` (a position
and a length). `stop` is an Objective-C "pointer to a stop flag", unused here.

```python
options = NLTaggerOmitWhitespace | NLTaggerOmitPunctuation
tagger.enumerateTagsInRange_unit_scheme_options_usingBlock_(
    (0, len(text)), NLTokenUnitWord, NLTagSchemeLexicalClass, options, visit
)
```
Options are bit flags combined with `|`. Tag the whole text (the tuple `(0, len(text))` is
converted to an NSRange), word by word, calling `visit` for each. This fills `words`.

```python
found = []
for i, (word, tag, start, end) in enumerate(words):
    if word.lower() != "like":
        continue
```
`enumerate` gives the index along with each item. Only "like" interests us. The comment
explains why the word itself is checked: Apple counts positions in UTF-16 units, Python in
characters; an emoji earlier in the text (2 UTF-16 units, 1 Python character) would shift the
positions, and then `text[start:end]` wouldn't be "like" any more, so it's safely skipped.

```python
    previous = words[i - 1][0].lower() if i > 0 else ""
    following, following_tag = words[i + 1][:2] if i + 1 < len(words) else ("", None)
    before_verb = previous == "to" and following_tag == NLTagVerb and not following.endswith("ing")
    if tag == NLTagInterjection or before_verb:
        found.append((start, end))
return found
```
"like" is a filler if the tagger calls it an interjection, or it sits between "to" and a base
verb ("able to like use this"). The `-ing` exception keeps "used to like going".

## Lines 205–213: `lowercase_first`

```python
first = text.split(" ", 1)[0].strip(",.!?;:")
if first in KEEP_CAPITAL or first[1:].isupper() or first in keep:
    return text
return text[:1].lower() + text[1:]
```
`split(" ", 1)` splits at the first space only; `[0]` is the first word. Keep the capital for
"I", for acronyms (`"IBM"[1:]` = `"BM"`, all upper), and for names in `keep`. Otherwise
lowercase the first letter: "Go tomorrow" → "go tomorrow".

## Lines 216–232: `join_pieces`

```python
if not before:
    return after
last_word = normalise(before.split()[-1]) if before.split() else ""
first_word = normalise(after.split()[0]) if after.split() else ""
```
Nothing before → just the new text. Otherwise get the last word before the pause and the
first word after it.

```python
if last_word in OPEN_ENDINGS or first_word in LINKING_STARTS:
    after = lowercase_first(after)
    return before.rstrip(" .,;") + ("... " if hesitation else " ") + after
```
The sentence continues through the pause: remove the period Whisper put at the end of the
first piece, lowercase the second, and join with "... " for a long pause or a plain space.
`"I think we should."` + `"Go tomorrow."` → `"I think we should... go tomorrow."`

```python
if before[-1:].isalnum():
    before += "."
return before + " " + after
```
Otherwise it's a normal sentence break; make sure the first sentence ends with a period.

## Lines 235–263: self-correction patterns

```python
MARKER = (
    r"(?:no,? )?sorry|no,? wait|wait,? no|i mean(?:t)?(?: to say)?|or rather|"
    r"(?:non,? )?pardon|non,? attends|je veux dire|je voulais dire|ou plutôt|"
    r"scratch that|forget that|oublie ça|efface ça"
)
```
The phrases you say to correct yourself. Adjacent string literals in parentheses are joined
into one string. `,?` = optional comma; `i mean(?:t)?(?: to say)?` matches "i mean",
"i meant", "i mean to say", "i meant to say".

```python
MISHEARD_MARKER = r"i'?m at"
```
Whisper often hears "I meant" as "I'm at". Only accepted after another marker.

```python
CORRECTION = re.compile(
    rf"(?P<lead>[,.;…—?!]|\s-)\s*"
    rf"(?P<markers>(?:{MARKER})[,.;!]?\s+(?:(?:{MARKER}|{MISHEARD_MARKER})[,.;!]?\s+)*)(?=\w)",
    re.IGNORECASE,
)
```
`rf"..."` is a raw f-string: backslashes stay as-is **and** `{MARKER}` is replaced by the
string above. The pattern means:
- `(?P<lead>[,.;…—?!]|\s-)` – the punctuation before the marker, named "lead" (or a
  space+hyphen). This is what tells "Tuesday, sorry, Wednesday" apart from "I'm sorry".
- `\s*` – optional spaces.
- `(?P<markers> ... )` – one marker, optional punctuation, spaces; then **zero or more**
  further markers (or "I'm at"), each with optional punctuation and spaces. So "Wait no, I mean"
  is one match.
- `(?=\w)` – must be followed by a word (the correction itself), not consumed.

```python
SCRATCH = {"scratch that", "forget that", "oublie ça", "efface ça"}
WEAK = {"i mean", "i meant", ..., "ou plutôt"}
LOOK_BACK = 6
NEW_CLAUSE = set("""i i'm i'll ... ça""".split())
PREPOSITIONS = set("in on at up out over under near next this that these those".split())
SENTENCE_START = re.compile(r"(?:^|(?<=[.!?])\s+)(?=\S)")
CLAUSE_START = re.compile(r"(?:^|(?<=[.!?,;:])\s+)(?=\S)")
```
- `SCRATCH` – markers that delete the whole previous sentence.
- `WEAK` – markers often used as plain talk ("It's good, I mean, it works"); only acted on
  when the correction clearly restates a word.
- `LOOK_BACK` – how many words back a restated word may be.
- `NEW_CLAUSE` – pronouns etc. that start a new clause ("Sorry, I missed your call" is an
  apology, not a swap).
- `SENTENCE_START` / `CLAUSE_START` – match positions where a sentence (or clause) begins:
  either the start of the text, or after `.!?` (or also `,;:` for clauses) plus spaces,
  right before a non-space character.

## Lines 266–293: `apply_corrections`

```python
position = 0
while match := CORRECTION.search(text, position):
```
Find the next correction marker at or after `position`. The walrus `:=` assigns the match and
the loop stops when `search` returns `None`.

```python
    head, tail = text[: match.start()], text[match.end() :]
```
`head` = everything before the lead punctuation; `tail` = the correction and everything after.

```python
    found = re.findall(f"{MARKER}|{MISHEARD_MARKER}", match.group("markers"), re.IGNORECASE)
    markers = {" ".join(m.lower().replace(",", "").replace("'", "").split()) for m in found}
```
List the individual markers in the matched group and normalise each (lowercase, no commas or
apostrophes, single spaces): `"No, wait"` → `"no wait"`, `"I'm at"` → `"im at"`.

```python
    lead = match.group("lead")
    cut = _correction_start(head, tail, markers, after_sentence=lead in ".…?!")
    if cut is None:
        position = match.end()
        continue
```
Ask where in `head` the corrected words start. `None` = it wasn't a correction; continue
searching after this match.

```python
    if cut == 0 or head[:cut].rstrip()[-1:] in ".!?":
        tail = tail[:1].upper() + tail[1:]
```
If the correction now starts a sentence, capitalise it.

```python
    if lead in "?!" and not markers & SCRATCH:
        tail = re.sub(r"\.(?=\s|$)", lead, tail, count=1)
```
"on Friday? Wait no, Wednesday." is still a question: replace the first sentence-ending
period of the tail with the `?`/`!`. `count=1` replaces only one.

```python
    text = head[:cut] + tail
    position = cut
return text
```
Keep `head` up to the cut, then the correction. Continue searching from the cut (chained
corrections).

## Lines 296–328: `_correction_start`

Decides how much of `head` the correction replaces.

```python
sentences = [m.end() for m in SENTENCE_START.finditer(head)]  # each sentence's first letter
if not sentences:
    return None
if markers & SCRATCH:
    return sentences[-1]
```
Positions of the first letter of each sentence in `head`. If `head` is empty, there's nothing
to correct. "Scratch that" cuts at the start of the last sentence.

Why `m.end()` and not `m.start()`: for every sentence except the first, `SENTENCE_START`
matches the *spaces* after the period, so the match **starts** at the space and **ends** right
before the first letter (the `(?=\S)` lookahead takes up no room). This used to be `m.start()`,
which made "scratch that" lose the space:
`"I went home. Then I left, scratch that, I stayed."` came out as `"I went home.I stayed."`;
now it gives `"I went home. I stayed."`.

```python
clause = [m.start() for m in CLAUSE_START.finditer(head)][-1]
words = list(re.finditer(r"\S+", head[clause:]))
if not words:
    return None
```
Where the last clause of `head` starts, and its words (as match objects, so we know their
positions relative to `clause`).

```python
first_word = tail.split()[0].strip(".,;:!?")
first = normalise(first_word)
pronoun = after_sentence and first in NEW_CLAUSE - {"on"}
```
The first word of the correction. `pronoun` is `True` when the marker followed a sentence end
and the correction starts with a pronoun: "It was fine. I meant it." is a new sentence.
(`NEW_CLAUSE - {"on"}` removes French "on", because English "on" is common in corrections.)

```python
for word in reversed([] if pronoun else words[-LOOK_BACK:]):
    if normalise(word.group()) == first:
        return clause + word.start()
```
Look back up to 6 words, nearest first. If the correction starts with a word you just said,
restart from there: "meet on Tuesday, sorry, on Wednesday" → cut at the first "on".

```python
last = words[-1]
addressed = re.match(r"\S+,", tail)
if first not in NEW_CLAUSE and not addressed and clause + last.start() not in sentences and _alike(last.group(), first_word):
    return clause + last.start()
```
No restated word. If the last word and the correction are "the same kind of word" (two days,
two numbers, two names...), swap just that word — even across a sentence end. Not if the
correction is addressing someone ("Sorry, Mark, I forgot") or the last word is the first word
of a sentence (`clause + last.start() not in sentences`), so "We left. Friday? Sorry,
Saturday." is left alone.

```python
if markers & WEAK or after_sentence or first in NEW_CLAUSE:
    return None
if first in OPEN_ENDINGS or first in PREPOSITIONS:
    return None
if normalise(words[-1].group()) in OPEN_ENDINGS:
    return None
return clause + words[-1].start()
```
Cases where guessing is unsafe → leave the text alone:
- a weak marker, after a sentence end, or a new clause ("It's good, I mean, it works");
- the correction starts with "the", "in"... (can't tell how much it replaces);
- the last word is "to", "the"... ("I went to, sorry, the shop" is a hesitation).
Otherwise swap the last word: "Tuesday, sorry, Wednesday" → "Wednesday".

## Lines 331–345: `DAYS`, `MONTHS`, `_alike`

```python
def _alike(old, new):
    old, new = old.strip(".,;:!?"), new.strip(".,;:!?")
    for kind in (DAYS, MONTHS):
        if old.lower() in kind and new.lower() in kind:
            return True
    if any(c.isdigit() for c in old) and any(c.isdigit() for c in new):
        return True
    return old[:1].isupper() and new[:1].isupper()
```
Two words are alike if both are days (English or French), both months, both contain digits,
or both start with a capital (names: "Marc" / "Julie").
