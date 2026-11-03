"""Context: the text around the cursor in the app you're dictating into.

Read through Accessibility (see ax.py) when you start speaking and again
just before pasting. It's used three ways:
  - names and terms near the cursor ("Kubernetes", "Jiacai", "Q3") are
    added to Whisper's prompt, so it spells them the way the text does;
  - the dictation is fitted in: no capital when you're mid-sentence, no
    final period when the text after the cursor carries on, or in a
    one-line field like a search box or a subject line; a space after it,
    so you can keep typing or dictating;
  - learning.py looks at the same spot later to learn your corrections.
Apps that don't share their text (VS Code, many web pages) get none of this,
and password fields are never read. The text stays in memory, never logged.
"""

import re

import ax
from cleanup import lowercase_first

BEFORE_CHARS, AFTER_CHARS = 2000, 300  # how much text around the cursor we look at
MAX_TERMS = 20  # the ones closest to the cursor
SINGLE_LINE = {"AXTextField", "AXSearchField", "AXComboBox"}
WORD = re.compile(r"\w[\w'’-]*\w|\w")
TERM_SKIP = {"I", "I'm", "I'll", "I've", "I'd"}


class Context:
    def __init__(self, field=None, start=0, before="", after="", role=None):
        self.field = field  # the text field, or None if the app doesn't share its text
        self.start = start  # where the cursor (or selection) starts
        self.before, self.after = before, after  # text just before / after the cursor or selection
        self.role = role
        self.terms = find_terms(before + " " + after)


def read():
    """The context at the cursor right now (an empty Context if the app doesn't say)."""
    try:
        field = ax.focused_element()
        if field is None or ax.is_secure(field):
            return Context()
        text_range, count = ax.selected_range(field), ax.character_count(field)
        if text_range is None or count is None:
            return Context()
        start, length = text_range
        first = max(0, start - BEFORE_CHARS)
        before = ax.text(field, first, start - first)
        end = start + length
        after = ax.text(field, end, min(AFTER_CHARS, count - end))
        if before is None or after is None:
            return Context()
        return Context(field, start, before, after, ax.role(field))
    except Exception:
        return Context()  # an app answered something odd: do without


def find_terms(text):
    """Names, acronyms and codes in the text: "Jiacai", "MLX", "iPhone", "Q3".

    A capital counts only mid-sentence: "The" starting a sentence isn't a name.
    """
    terms = []
    for match in WORD.finditer(text):
        word = match.group()
        mid_sentence = text[: match.start()].rstrip()[-1:] not in ("", ".", "!", "?", "…", "\n", ":", "\"", "“", "«")
        capital = word[0].isupper() and mid_sentence
        unusual = any(c.isupper() for c in word[1:]) or (any(c.isdigit() for c in word) and any(c.isalpha() for c in word))
        if (capital or unusual) and word not in TERM_SKIP:
            terms.append(word)
    return list(dict.fromkeys(reversed(terms)))[:MAX_TERMS]  # closest to the cursor first, no duplicates


def fit(text, context, names=()):
    """Fit a dictation into the text around the cursor.

    Mid-sentence, the first word loses its capital unless it's a known name
    (`names`, or a term near the cursor): we can't tell "Marc" from "Bought" otherwise.
    """
    last = context.before.rstrip(" \t")[-1:]
    if last and (last.isalnum() or last in ",;"):  # "and then" + "Go home" -> "go home"
        text = lowercase_first(text, keep=set(names) | set(context.terms))
    first = context.after.lstrip(" \t")[:1]
    carries_on = first and (first.islower() or first in ",.;:!?)")
    if (carries_on or context.role in SINGLE_LINE) and text.endswith(".") and not text.endswith(".."):
        text = text[:-1]
    return text


def space_after(context):
    """" " to follow the dictation, so the next one (typed or dictated) starts cleanly.

    Dictations never start with a space, so this one is what separates them.
    None if a space or punctuation already follows the cursor: "word| next", "word|.".
    """
    following = context.after[:1]
    return "" if following and not following.isalnum() else " "
