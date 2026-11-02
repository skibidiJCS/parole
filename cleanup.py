"""Tidy a transcript: filler words, stutters, repeats, self-corrections, and pauses.

    "Um, I- I think we should, we should leave."  ->  "I think we should leave."
    "Je je pense que, euh, je pense que c'est bon." ->  "Je pense que c'est bon."
    "Let's meet on Tuesday, sorry, on Wednesday."  ->  "Let's meet on Wednesday."
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

Self-corrections are found by what you say to fix a slip: "sorry", "I mean",
"I meant", "no wait", "pardon", "je veux dire", "je voulais dire"... set off by punctuation, so "I'm sorry"
is left alone. What you say next replaces what you said just before it; see
apply_corrections for how much. "Scratch that" / "oublie ça" drops the
whole sentence before it.
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


# What you say to correct yourself. Whisper puts punctuation before it
# ("Tuesday, sorry, Wednesday"), which is what tells it apart from "I'm sorry".
MARKER = (
    r"(?:no,? )?sorry|no,? wait|wait,? no|i mean(?:t)?(?: to say)?|or rather|"
    r"(?:non,? )?pardon|non,? attends|je veux dire|je voulais dire|ou plutôt|"
    r"scratch that|forget that|oublie ça|efface ça"
)
# Whisper often hears "sorry, I meant" as "sorry, I'm at": only counted after another marker.
MISHEARD_MARKER = r"i'?m at"
# One or more markers in a row ("Wait no, I mean Wednesday"), after punctuation.
CORRECTION = re.compile(
    rf"(?P<lead>[,.;…—?!]|\s-)\s*"
    rf"(?P<markers>(?:{MARKER})[,.;!]?\s+(?:(?:{MARKER}|{MISHEARD_MARKER})[,.;!]?\s+)*)(?=\w)",
    re.IGNORECASE,
)
SCRATCH = {"scratch that", "forget that", "oublie ça", "efface ça"}
# Weak markers are often just talk ("It's good, I mean, it works"): only act
# when what follows clearly restates something you just said.
WEAK = {"i mean", "i meant", "i mean to say", "i meant to say", "im at", "or rather", "je veux dire", "je voulais dire", "ou plutôt"}
LOOK_BACK = 6  # words; how far back the restated word can be
# A correction starting like a new clause ("Hey, sorry, I missed your call")
# is an apology, not a one-word swap.
NEW_CLAUSE = set("""
i i'm i'll i've i'd we we're you you're he she it it's they they're that's there's this
je j'ai j'suis tu il elle on nous vous ils elles c'est ça
""".split())
PREPOSITIONS = set("in on at up out over under near next this that these those".split())  # beyond OPEN_ENDINGS
SENTENCE_START = re.compile(r"(?:^|(?<=[.!?])\s+)(?=\S)")
CLAUSE_START = re.compile(r"(?:^|(?<=[.!?,;:])\s+)(?=\S)")


def apply_corrections(text):
    """Replace what you corrected with the correction.

    How far back the correction reaches:
      - if it starts with a word you said shortly before (in the same clause),
        it restarts from there: "meet on Tuesday, sorry, on Wednesday" -> "meet on Wednesday";
      - otherwise it replaces just the last word: "meet Tuesday, sorry, Wednesday" -> "meet Wednesday",
        even across a sentence end when both are the same kind of word (days, months,
        numbers, names): "on Friday? Wait no, I mean Wednesday." -> "on Wednesday?";
      - "scratch that" drops the sentence before it.
    """
    position = 0
    while match := CORRECTION.search(text, position):
        head, tail = text[: match.start()], text[match.end() :]
        found = re.findall(f"{MARKER}|{MISHEARD_MARKER}", match.group("markers"), re.IGNORECASE)
        markers = {" ".join(m.lower().replace(",", "").replace("'", "").split()) for m in found}
        lead = match.group("lead")
        cut = _correction_start(head, tail, markers, after_sentence=lead in ".…?!")
        if cut is None:  # not a correction after all
            position = match.end()
            continue
        if cut == 0 or head[:cut].rstrip()[-1:] in ".!?":  # the correction now starts a sentence
            tail = tail[:1].upper() + tail[1:]
        if lead in "?!" and not markers & SCRATCH:  # "on Friday? Wait no, Wednesday." is still a question
            tail = re.sub(r"\.(?=\s|$)", lead, tail, count=1)
        text = head[:cut] + tail
        position = cut
    return text


def _correction_start(head, tail, markers, after_sentence):
    """Where in `head` the corrected words start, or None to leave the text alone."""
    sentences = [m.start() for m in SENTENCE_START.finditer(head)]
    if not sentences:
        return None  # "Sorry, I'm late": nothing before it to correct
    if markers & SCRATCH:
        return sentences[-1]
    # Words of the clause just before the marker; if the marker opens a new
    # sentence ("Tuesday. Sorry, Wednesday."), that previous sentence's last clause.
    clause = [m.start() for m in CLAUSE_START.finditer(head)][-1]
    words = list(re.finditer(r"\S+", head[clause:]))
    if not words:
        return None
    first_word = tail.split()[0].strip(".,;:!?")
    first = normalise(first_word)
    # A pronoun restated after a sentence end is a new sentence: "It was fine. I meant it."
    # ("on" is also English: "Tuesday. Sorry, on Wednesday." restarts at "on".)
    pronoun = after_sentence and first in NEW_CLAUSE - {"on"}
    for word in reversed([] if pronoun else words[-LOOK_BACK:]):
        if normalise(word.group()) == first:
            return clause + word.start()  # "on Tuesday, sorry, on Wednesday": restart at "on"
    # No restated word: only a one-word swap is safe to guess.
    last = words[-1]
    addressed = re.match(r"\S+,", tail)  # "Friday. Sorry, Mark, I forgot": talking to Mark
    if first not in NEW_CLAUSE and not addressed and clause + last.start() not in sentences and _alike(last.group(), first_word):
        return clause + last.start()  # like for like: "on Friday? Wait no, I mean Wednesday."
    if markers & WEAK or after_sentence or first in NEW_CLAUSE:
        return None  # "It's good, I mean, it works"; "I'm late. Sorry, I'll hurry"
    if first in OPEN_ENDINGS or first in PREPOSITIONS:
        return None  # "on the desktop, sorry, in Downloads": can't tell how much "in ..." replaces
    if normalise(words[-1].group()) in OPEN_ENDINGS:
        return None  # "I went to, sorry, the shop" is a hesitation, not a slip
    return clause + words[-1].start()  # "Tuesday, sorry, Wednesday": swap the last word


DAYS = set("""monday tuesday wednesday thursday friday saturday sunday today tomorrow tonight yesterday
lundi mardi mercredi jeudi vendredi samedi dimanche aujourd'hui demain hier""".split())
MONTHS = set("""january february march april may june july august september october november december
janvier février mars avril mai juin juillet août septembre octobre novembre décembre""".split())


def _alike(old, new):
    """Same kind of word: days ("vendredi" / "mercredi"), months, numbers, or names ("Marc" / "Julie")."""
    old, new = old.strip(".,;:!?"), new.strip(".,;:!?")
    for kind in (DAYS, MONTHS):
        if old.lower() in kind and new.lower() in kind:
            return True
    if any(c.isdigit() for c in old) and any(c.isdigit() for c in new):
        return True
    return old[:1].isupper() and new[:1].isupper()
