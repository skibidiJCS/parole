# voice.py — voice activity detection

[voice.py](../voice.py) answers "did anyone speak, and when?" using **Silero VAD** (Voice
Activity Detection), a tiny neural network trained only to tell speech from non-speech.

---

## Lines 1–13: docstring

Why this exists:
- Whisper always writes *something*, even for silence ("Thank you."). Silero is asked first,
  and Whisper is skipped when nobody spoke.
- It also says *where* the speech is, so the recording is cut into pieces at pauses. Each
  piece (usually a sentence) gets its own language detection — so French and English
  sentences can alternate — and no piece is longer than 28 s (Whisper reads 30 s at a time).

## Lines 15–18: imports

```python
import torch                                                   # PyTorch: Silero runs on it
from silero_vad import get_speech_timestamps, load_silero_vad  # the VAD model and helper
from recorder import SAMPLE_RATE                               # 16000
```

## Lines 20–23: settings

```python
PADDING = 0.2      # keep 0.2 s around each bit of speech so first/last sounds aren't clipped
MAX_GAP = 0.6      # if padded spans are more than 0.6 s apart, start a new piece
PAUSE = MAX_GAP + 2 * PADDING   # = 1.0 s: the real silence that separates two pieces
MAX_CHUNK = 28     # seconds: the longest piece we hand to Whisper
```
Why `PAUSE` adds both paddings: two speech spans 1.0 s apart become, after padding, spans only
0.6 s apart (each grew by 0.2 s toward the other). So "padded gap ≥ 0.6 s" means "real
silence ≥ 1.0 s". parole.py uses `PAUSE` with this real-silence meaning.

## Lines 26–29: `__init__`

```python
torch.set_num_threads(1)        # use one CPU core: plenty for this model, saves battery
self.model = load_silero_vad()  # load the small model (bundled with the package)
```

## Lines 31–33: `spans`

```python
def spans(self, audio):
    return get_speech_timestamps(torch.from_numpy(audio), self.model, sampling_rate=SAMPLE_RATE)
```
`torch.from_numpy` wraps the NumPy array as a PyTorch tensor (no copy). The result is a list
of dictionaries like `[{"start": 3200, "end": 20800}, ...]` — sample positions where speech
starts and ends.

## Lines 35–51: `speech_pieces`

```python
spans = self.spans(audio)
padding, max_gap, max_len = (int(s * SAMPLE_RATE) for s in (PADDING, MAX_GAP, MAX_CHUNK))
```
Convert the three settings from seconds to samples (3200, 9600, 448000), using a generator
expression unpacked into three variables.

```python
pieces = []
for span in spans:
    start, end = max(0, span["start"] - padding), min(len(audio), span["end"] + padding)
```
Widen each span by the padding, without going below 0 or past the end of the audio.

```python
    if pieces and start - pieces[-1][1] < max_gap and end - pieces[-1][0] <= max_len:
        pieces[-1][1] = end
    else:
        pieces.append([start, end])
```
- `pieces[-1]` is the last piece so far, a `[start, end]` list (a list, not a tuple, so its
  end can be changed).
- If this span starts less than 0.6 s after the last piece ends **and** merging wouldn't make
  the piece longer than 28 s → extend the last piece to cover it.
- Otherwise start a new piece.

```python
return [(cut, min(cut + max_len, end)) for start, end in pieces for cut in range(start, end, max_len)]
```
A piece can still be longer than 28 s if one single speech span is (someone talking non-stop).
For each piece, `range(start, end, max_len)` gives cut points every 28 s, and each becomes a
`(cut, cut + 28 s)` chunk, with the last one stopping at `end`. A piece shorter than 28 s
gives just one chunk: `(start, end)`. The result is a list of `(start, end)` tuples.
