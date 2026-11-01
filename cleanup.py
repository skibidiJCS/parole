"""Tidy a transcript: filler words, stutters, repeats, and pauses.

    "Um, I- I think we should, we should leave."  ->  "I think we should leave."
    "Je je pense que, euh, je pense que c'est bon." ->  "Je pense que c'est bon."
    pieces "I think we should." + "go tomorrow."    ->  "I think we should... go tomorrow."

Fillers ("um", "euh"...) are dropped wherever they are; "like", "you know",
"genre", "tu vois" only when they sit between commas, so "I like it" stays.

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

MAX_PHRASE = 10  # longest phrase (in words) we look for repeats of
# Words that are legitimately doubled ("nous nous sommes", "he had had").
KEEP_DOUBLED = {"nous", "vous", "had", "that", "is", "very", "so", "no", "non", "oui", "yes", "ha", "haha", "bye"}
# "w-what", "b-but", "th-the": a 1-2 letter fragment glued to the word it starts.
GLUED_STUTTER = re.compile(r"\b(\w{1,2})-(\1)", re.IGNORECASE)
REAL_PREFIXES = {"re", "co", "de", "ex", "un", "in", "bi"}  # "re-read", "co-op" are words
SENTENCE_END = ".!?"  # "..." / "…" is a pause, not the end of a sentence

# Sounds that are never words: uh, uhm, um, umm, er, erm, hmm, mm, mmh, mhm, euh, heu, hum.
FILLER = re.compile(r"^(?:u+h+|u+h*m+|e+r+m*|h+m+|m+h?m+|m+h+|e+u+h+|h+e+u+|h+u+m+)$")
# Real words used as fillers when set off by commas: "it was, like, huge".
COMMA_FILLERS = re.compile(r",\s+(?:like|you know|genre|tu vois),(\s+)", re.IGNORECASE)
LEADING_LIKE = re.compile(r"(^|[.!?]\s+)like,\s+(\w)", re.IGNORECASE)


def ends_sentence(token):
    token = token.rstrip()
    return token[-1:] in SENTENCE_END and not token.endswith(("...", "…"))


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
            # "C'est vrai. C'est vrai." is two sentences, probably on purpose
            # (but "we should... we should go" is a hesitation, not two sentences).
            if ends_sentence(tokens[i + n - 1]):
                continue
            return n
    return 0


def remove_fillers(text):
    """Drop "um", "euh"... and comma-wrapped "like", "you know", "genre", "tu vois"."""
    text = COMMA_FILLERS.sub(r"\1", text)
    text = LEADING_LIKE.sub(lambda m: m.group(1) + m.group(2).upper(), text)
    kept, capitalize = [], False
    for token in re.findall(r"\S+\s*", text):
        if not FILLER.match(normalise(token)):
            if capitalize:  # the filler started the sentence: its capital moves on
                token, capitalize = token[:1].upper() + token[1:], False
            kept.append(token)
            continue
        ending = token.rstrip()[-1:]
        if kept:
            previous = kept[-1].rstrip()
            spaces = kept[-1][len(previous) :]
            if ending in SENTENCE_END:  # "We go, um." -> "We go."
                kept[-1] = previous.rstrip(",;:") + ending + spaces
            elif ending == "," and previous.endswith(","):  # "It's, uh, fine" -> "It's fine"
                kept[-1] = previous[:-1] + spaces
        capitalize = capitalize or token[:1].isupper()
    return "".join(kept).strip()


# Words a sentence can't end on: if the text before a pause ends with one,
# you were hesitating mid-sentence ("I think we should... go tomorrow").
OPEN_ENDINGS = set("""
a an the and or but because if which who whose to of for with from by at as than when where while into
is are was were be been am will would should could must might have has had my your his our their its
we i you he she they i'm we're you're they're very just every each
le la les un une des du de et ou mais donc car que qui à au aux en dans sur pour par avec sans chez vers
est sont était étaient suis es ai as avons avez ont va vais vas allons allez vont je tu il elle on nous
vous ils elles mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs ce cet cette ces c'est
très ne se me te d' l' qu' j'
""".split())  # not "so", "that", "this", "in", "pas", "plus"...: sentences often end on those
# Words that carry a sentence on after a pause ("I went home... and then...").
LINKING_STARTS = set("and but or so because then which that et mais ou donc parce puis alors qui que".split())
KEEP_CAPITAL = {"I", "I'm", "I'll", "I've", "I'd"}


def lowercase_first(text, keep=()):
    """"Go tomorrow" -> "go tomorrow", for text that carries on a sentence.

    Keeps "I", acronyms ("IBM") and the names in `keep`.
    """
    first = text.split(" ", 1)[0].strip(",.!?;:")
    if first in KEEP_CAPITAL or first[1:].isupper() or first in keep:
        return text
    return text[:1].lower() + text[1:]


def join_pieces(before, after, hesitation=True):
    """Join text transcribed before and after a pause (Whisper did them separately).

    A pause in the middle of a sentence doesn't end it: the sentence goes on,
    with "..." if the pause was a long one (`hesitation`). A pause after a
    complete sentence stays a normal sentence break.
    """
    if not before:
        return after
    last_word = normalise(before.split()[-1]) if before.split() else ""
    first_word = normalise(after.split()[0]) if after.split() else ""
    if last_word in OPEN_ENDINGS or first_word in LINKING_STARTS:
        after = lowercase_first(after)
        return before.rstrip(" .,;") + ("... " if hesitation else " ") + after
    if before[-1:].isalnum():
        before += "."  # Whisper sometimes leaves the last sentence open
    return before + " " + after
