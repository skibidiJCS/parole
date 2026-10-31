"""Remove stutters and phrases said twice in a row from a transcript.

    "I- I think we should, we should leave."  ->  "I think we should leave."
    "Je je pense que, je pense que c'est bon." ->  "Je pense que c'est bon."

The text is split into words (each keeping its punctuation and the space
after it). Words are compared in a "normalised" form: lowercase, without
punctuation, so "should," matches "should" and "I-" matches "I".
Whenever a run of 1 to MAX_PHRASE words is immediately repeated, the first
copy is dropped. We keep the second copy because it's usually the one that
carries on into the rest of the sentence (with its punctuation); the first
copy's capital letter is moved onto it.

This only catches *exact* repeats. Rephrasing in different words
("I think, I believe…") needs a language model (roadmap phase 6).
"""

import re

MAX_PHRASE = 6  # longest phrase (in words) we look for repeats of
# Words that are legitimately doubled ("nous nous sommes", "he had had").
KEEP_DOUBLED = {"nous", "vous", "had", "that", "is", "very", "so", "no", "non", "oui", "yes", "ha", "haha", "bye"}
# "w-what", "b-but", "th-the": a 1-2 letter fragment glued to the word it starts.
GLUED_STUTTER = re.compile(r"\b(\w{1,2})-(\1)", re.IGNORECASE)
REAL_PREFIXES = {"re", "co", "de", "ex", "un", "in", "bi"}  # "re-read", "co-op" are words
SENTENCE_END = ".!?…"


def normalise(token):
    """Lowercase and strip punctuation, keeping letters (accents too), digits and apostrophes."""
    return re.sub(r"[^\w']", "", token.lower()).strip("'")


def _unglue(match):
    """'W-wh' -> 'Wh': drop the fragment, keep its capital letter."""
    fragment, start = match.group(1), match.group(2)
    if fragment.lower() in REAL_PREFIXES:
        return match.group(0)
    return start[0].upper() + start[1:] if fragment[0].isupper() else start


def remove_repeats(text):
    text = GLUED_STUTTER.sub(_unglue, text)
    tokens = re.findall(r"\S+\s*", text)  # each word with the spaces after it
    words = [normalise(t) for t in tokens]
    i = 0
    while i < len(tokens):
        drop = _repeat_length(tokens, words, i)
        if drop:
            capital = tokens[i][:1].isupper()
            del tokens[i : i + drop], words[i : i + drop]
            if capital and tokens:
                tokens[i] = tokens[i][:1].upper() + tokens[i][1:]
            continue  # look again here: "the the the" needs two passes
        i += 1
    return "".join(tokens).strip()


def _repeat_length(tokens, words, i):
    """How many words starting at i are a stutter or a repeat (0 if none)."""
    # Cut-off word: "th- the", "w- what" (a fragment ending in "-" followed
    # by a word starting the same way). "well-known" has no space, so it's safe.
    if i + 1 < len(tokens) and tokens[i].rstrip().endswith("-"):
        if words[i] and words[i + 1].startswith(words[i]):
            return 1
    # Exact repeat of the next n words, longest first.
    for n in range(MAX_PHRASE, 0, -1):
        first, second = words[i : i + n], words[i + n : i + 2 * n]
        if len(second) == n and first == second and all(first):
            if n == 1 and first[0] in KEEP_DOUBLED:
                continue
            # "C'est vrai. C'est vrai." is two sentences, probably on purpose.
            if tokens[i + n - 1].rstrip()[-1:] in SENTENCE_END:
                continue
            return n
    return 0
