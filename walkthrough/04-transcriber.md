# transcriber.py — Whisper on the Apple GPU

[transcriber.py](../transcriber.py) turns up to 30 s of audio into text with OpenAI's
**Whisper** model (the `large-v3-turbo` version), running on the Apple Silicon GPU through
**MLX** (Apple's machine-learning library) and the `mlx_whisper` package.

---

## Lines 1–31: docstring — how Whisper works

Whisper has two halves:
- the **encoder** "listens": it turns audio into a grid of numbers describing the sound
  (expensive);
- the **decoder** "writes": it reads that grid and produces text one **token** at a time
  (~10 ms each). A token is a word or a piece of a word, stored as an integer ID.

Whisper was trained on 30-second windows: normally every clip is padded with silence to 30 s,
so the encoder costs ~1 s whatever you said. **Fast mode** gives the encoder a shorter
window (clip length + 1 s, minimum 10 s), which is 3–6× faster. The catch: without the long
silence, the decoder doesn't realise the speech ended and **repeats** it. So we ask for
timestamps, split the output into segments, and stop at the first repeat or the first
timestamp past the end of the window. If fast mode is unsure, it retries with the full 30 s
window.

The code calls encoder and decoder directly instead of `mlx_whisper.transcribe()`, which would
run the encoder twice and keep a second copy of the model.

## Lines 33–48: imports

```python
import math                          # math.ceil (round up)
import os                            # os.environ (environment variables)
import re                            # regular expressions
from contextlib import contextmanager  # decorator to write "with" blocks as functions

os.environ["HF_HUB_OFFLINE"] = "1"
```
The model files are already in `~/.cache/huggingface`. Setting this environment variable tells
the Hugging Face library never to go online. It must be set **before** the libraries below are
imported, because they read it at import time. That's why the next imports carry
`# noqa: E402`: it tells linters (style checkers like flake8) to ignore the rule "imports must
be at the top of the file" for these lines.

```python
import mlx.core as mx                       # MLX arrays (like NumPy, but on the GPU)
import numpy as np
from mlx_whisper.audio import log_mel_spectrogram, pad_or_trim   # audio → spectrogram
from mlx_whisper.decoding import DecodingOptions, decode          # the decoder
from mlx_whisper.load_models import load_model                    # load weights
from mlx_whisper.tokenizer import get_tokenizer                   # tokens ↔ text
from recorder import SAMPLE_RATE
```

## Lines 50–58: settings

```python
MODEL = "mlx-community/whisper-large-v3-turbo"   # Hugging Face model name
FULL_WINDOW = 30         # seconds Whisper was trained on
MIN_WINDOW = 10          # fast mode never uses less (shorter = more mistakes, measured)
LANGUAGES = ("en", "fr") # only these two are considered during language detection
MEL_FRAMES_PER_SECOND = 100   # the spectrogram has 100 columns per second
SECONDS_PER_TIMESTAMP = 0.02  # timestamp tokens go in steps of 20 ms
FAST_MIN_LOGPROB = -1.2  # below this average confidence, fast mode's result isn't trusted
```
**Log-probability**: for each token, the model gives a probability (0–1); its logarithm is
negative (0 = certain, −1.6 = quite unsure). The average over all tokens measures confidence.

## Lines 61–67: `__init__`

```python
self.model_name = model
self.model = None        # loaded in warm_up
self.tokenizer = None    # loaded in warm_up
self.fast = True         # the "Fast mode" menu toggle
self.last_path = None    # "fast" or "full": which path produced the last text (for the log)
```

## Lines 69–75: `warm_up`

```python
self.model = load_model(self.model_name, dtype=mx.float16)
```
Load the weights into memory (~3 s) as 16-bit floats (half precision: half the memory, faster
on the GPU).

```python
self.tokenizer = get_tokenizer(self.model.is_multilingual, num_languages=self.model.num_languages)
```
Create the tokenizer matching this model (multilingual, with its number of languages).

```python
self.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))
```
Transcribe 1 s of silence. MLX compiles GPU code the first time it's used, so this makes the
first real dictation fast. Fast mode finds nothing in silence and falls back to the full
window, so **both** code paths get warmed up.

## Lines 77–96: `transcribe`

```python
prompt = prompt or None
```
An empty string becomes `None` ("no prompt"), which is what `DecodingOptions` expects.

```python
mel = log_mel_spectrogram(pad_or_trim(mx.array(audio)), n_mels=self.model.dims.n_mels)
```
Read inside-out:
1. `mx.array(audio)` – convert the NumPy array to an MLX array.
2. `pad_or_trim(...)` – pad with zeros (or cut) to exactly 30 s = 480,000 samples.
3. `log_mel_spectrogram(..., n_mels=128)` – a "picture" of the sound: 3000 time columns
   (100 per second) × 128 frequency bands, with loudness on a log scale. This is what Whisper's
   encoder takes as input.

```python
if self.fast:
    window = min(FULL_WINDOW, max(MIN_WINDOW, math.ceil(len(audio) / SAMPLE_RATE) + 1))
```
Window = clip length rounded up to whole seconds, plus 1 s, clamped between 10 and 30.
E.g. 3.2 s → `ceil(3.2) + 1 = 5` → raised to 10. 14.5 s → 16.

```python
    text, language, covered = self._transcribe_short(mel, window, prompt)
    if text:
        self.last_path = "fast"
        return text, language, covered
self.last_path = "full"
return self._transcribe_full(mel, prompt)
```
If fast mode produced trusted text, use it. Otherwise (or if fast mode is off) use the full
30 s window.

## Lines 98–104: `_encode`

```python
frames = window * MEL_FRAMES_PER_SECOND
features = self.model.encoder(mel[None, :frames].astype(mx.float16))
```
- `mel[None, :frames]` – `None` in an index adds a new first dimension (a "batch" of 1),
  and `:frames` keeps only the first `window` seconds of columns. Shape `(1, frames, 128)`.
- `.astype(mx.float16)` to match the model's precision.
- The encoder outputs the "features" grid. (It halves the time resolution: 50 per second.)

```python
_, language_probs = self.model.detect_language(features)
return features, max(LANGUAGES, key=language_probs[0].get)
```
`detect_language` returns tokens (ignored with `_`) and a list with one dictionary per batch
item, mapping language codes to probabilities: `{"en": 0.91, "fr": 0.07, "de": ...}`.
`max(LANGUAGES, key=d.get)` picks whichever of `"en"`/`"fr"` has the highest probability
(`d.get("en")` is used as the score for `"en"`, and so on).

## Lines 106–116: `_transcribe_full`

```python
features, language = self._encode(mel, FULL_WINDOW)
options = DecodingOptions(language=language, without_timestamps=False, prompt=prompt)
result = decode(self.model, features, options)[0]
```
Encode the full 30 s, then decode with the detected language, **with** timestamps, and with
the vocabulary prompt. `decode` returns one result per batch item; `[0]` takes ours.

```python
if result.no_speech_prob > 0.6 and result.avg_logprob < -1.0:
    return "", language, []
```
Whisper's own rule against "hallucinations" in noise: if it thinks there's probably no speech
**and** it's unsure of the text, return nothing.

```python
segments, covered, _ = self._segments_within(result.tokens, FULL_WINDOW, prompt)
text, _ = first_copy(" ".join(segments))
return clean(text), language, covered
```
Split into segments, join them with spaces, cut any loop, clean.

## Lines 118–136: `_transcribe_short` (fast mode)

```python
sample_len = window * 6 + 12
```
The maximum number of tokens the decoder may produce: ~6 per second of audio plus 12 for
timestamps. A looping decoder therefore stops quickly.

```python
with self._encoder_window(window * MEL_FRAMES_PER_SECOND // 2):
    features, language = self._encode(mel, window)
    options = DecodingOptions(language=language, without_timestamps=False,
                              sample_len=sample_len, prompt=prompt)
    result = decode(self.model, features, options)[0]
```
Inside the `with` block, the model temporarily accepts a shorter window (see
`_encoder_window`). `window * 100 // 2` = number of encoder output positions (50 per second).

```python
if not result.avg_logprob >= FAST_MIN_LOGPROB:
    return "", language, []
```
Too unsure → let the full window decide. Written as `not (x >= limit)` instead of
`x < limit` on purpose: if `avg_logprob` is NaN ("not a number"), every comparison is
`False`, so `not (NaN >= limit)` is `True` and the result is rejected, whereas `NaN < limit`
would be `False` and let it through.

```python
segments, covered, stopped = self._segments_within(result.tokens, window, prompt)
text, looped = first_copy(" ".join(segments))
if not (stopped or looped) and len(result.tokens) >= sample_len:
    return "", language, []
return clean(text), language, covered
```
If the decoder used up the whole token budget **without** us detecting a repeat, the speech
was probably cut off → reject. Otherwise return the cleaned text.

## Lines 138–154: `_encoder_window`

```python
@contextmanager
def _encoder_window(self, n_features):
```
`@contextmanager` turns a generator function into something usable with `with`. The code
before `yield` runs when the `with` block starts; the code after (here in `finally`) runs when
it ends — even if an error happens inside.

```python
encoder, dims = self.model.encoder, self.model.dims
full_embedding, full_ctx = encoder._positional_embedding, dims.n_audio_ctx
encoder._positional_embedding = full_embedding[:n_features]
dims.n_audio_ctx = n_features
```
The encoder adds a fixed "position" vector to each of its 1500 time steps (it tells the model
"this is step 37"). With a shorter input we keep only the first `n_features` of these vectors.
`n_audio_ctx` is also set because mlx_whisper uses it to recognise that its input is already
encoded. The originals are saved first.

```python
try:
    yield
finally:
    encoder._positional_embedding = full_embedding
    dims.n_audio_ctx = full_ctx
```
Run the `with` block's body, then always restore the full-size values.

## Lines 156–190: `_segments_within`

With timestamps, Whisper's output tokens look like:
`<0.00> Okay sounds good.<1.44><8.44> Okay sounds good.<10.44> ...`
Pairs of timestamps surround each segment of text. This function splits the token list into
segments and stops where repeating starts.

```python
first_timestamp = self.tokenizer.timestamp_begin
segments, covered, words, opened = [], [], [], 0.0
```
Token IDs from `timestamp_begin` upward are timestamps (`<0.00>`, `<0.02>`, ...); IDs below
are text. `words` collects the text tokens of the segment in progress; `opened` is the time
when it started.

```python
for token in tokens:
    if token < first_timestamp:
        words.append(token)
        continue
    seconds = (token - first_timestamp) * SECONDS_PER_TIMESTAMP
```
Text token → collect it. Timestamp token → compute its time, e.g. ID `timestamp_begin + 72`
→ 1.44 s.

```python
    if words:
        text = self.tokenizer.decode(words).strip()
        if segments and text == segments[-1]:
            return segments, covered, True
        if not only_prompt(text, prompt):
            segments.append(text)
            covered.append((opened, min(seconds, window)))
        words = []
    else:
        opened = seconds
```
- If text was collected, this timestamp **closes** a segment: turn the tokens into text. If it's
  identical to the previous segment, the decoder is looping → stop (the `True` means "stopped
  early"). Otherwise keep it (unless it's only a word from the prompt) and record which seconds
  it covers.
- If no text was collected, this timestamp **opens** a segment: remember its time.

```python
    if seconds > window:
        return segments, covered, True
```
A timestamp beyond the end of the window can only be invented → stop.

```python
if words:
    segments.append(self.tokenizer.decode(words).strip())
    covered.append((opened, window))
return segments, covered, False
```
If the last segment never got its closing timestamp, keep it and assume it runs to the end.

## Lines 193–200: `only_prompt`

```python
plain = re.sub(r"[^\w' -]", "", text).strip().lower()
return bool(prompt and plain) and plain in {word.strip(" .").lower() for word in prompt.split(",")}
```
- `plain`: the text with everything except letters/digits, apostrophes, spaces and hyphens
  removed, lowercased. `"Jiacai."` → `"jiacai"`.
- The set comprehension `{...}` builds the set of prompt words: the prompt
  `"Parole, Jiacai."` split on commas → `{"parole", "jiacai"}`.
- Returns `True` when there is a prompt, the text isn't empty, and the text is exactly one of
  the prompt words. When Whisper can't make out a sound it tends to write a prompt word: a
  guess, not something you said.

## Lines 203–216: `first_copy`

Cuts a decoder loop like `"a b, a b, a b, ..."` down to `"a b"`. Needs **three** identical
copies in a row, so something you really said twice is left for cleanup.py.

```python
words = text.split()
plain = [re.sub(r"[^\w']", "", word.lower()) for word in words]
```
The words, and a normalised version (lowercase, no punctuation) for comparing.

```python
for end in range(3, len(words) + 1):
    for size in range(1, end // 3 + 1):
        a, b, c = (plain[end - k * size : end - (k - 1) * size] for k in (3, 2, 1))
```
For every position `end` and every phrase length `size` that fits three times before `end`,
take the three consecutive chunks of `size` words that end at `end`:
- `k=3` → `plain[end-3·size : end-2·size]` (first copy)
- `k=2` → `plain[end-2·size : end-size]` (second)
- `k=1` → `plain[end-size : end]` (third)

```python
        if a == b == c:
            return " ".join(words[: end - 2 * size]).rstrip(",;:"), True
return text, False
```
Three equal chunks → keep everything up to the end of the first copy, remove a dangling
comma/semicolon/colon, and report `looped=True`. The outer loop goes left to right, so the
earliest loop is found. Example: `"on se voit demain, on se voit demain, on se voit demain,"`
→ `("on se voit demain", True)`.

## Lines 219–223: `SUBTITLE_CREDITS`

Whisper learned from subtitled videos, so in noise it sometimes writes their credits. The
pattern matches "sous-titr…", "amara.org", "thank(s) (you) for watching", "merci d'avoir
regard…", "abonnez-vous", "like and subscribe", in any case. `(?:you )?` makes "you " optional;
`s?` makes "s" optional; `\.` is a literal dot.

## Lines 226–230: `clean`

```python
sentences = re.split(r"(?<=[.!?])\s+", text.strip())
```
Split into sentences at whitespace that comes right after `.`, `!` or `?`. The lookbehind
`(?<=...)` checks the punctuation without removing it, so each sentence keeps its period.

```python
text = " ".join(s for s in sentences if not SUBTITLE_CREDITS.search(s))
return text if any(c.isalnum() for c in text) else ""
```
Drop sentences that look like subtitle credits and join the rest. If no letter or digit is
left (e.g. Whisper wrote just `"."` for noise), return `""`.
