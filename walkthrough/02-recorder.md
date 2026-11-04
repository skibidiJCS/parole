# recorder.py — microphone capture

[recorder.py](../recorder.py) opens the microphone when recording starts, collects the
audio in memory, and closes the mic when recording stops. Nothing is written to disk.

---

## Lines 1–11: docstring

Two points:
- The mic stream only exists while recording, so between dictations the mic is off (no
  orange dot in the menu bar, no CPU use).
- **PortAudio** (the C library under `sounddevice`) reads the list of microphones once. After
  the Mac sleeps, a USB mic reappears as a "new" device and the list is stale. So the list is
  re-read before every recording (~5 ms).

## Lines 13–16

```python
import numpy as np          # fast numeric arrays: the audio is a NumPy array
import sounddevice as sd    # Python wrapper around PortAudio

SAMPLE_RATE = 16_000        # 16,000 samples per second, mono: what Whisper expects
```

## Lines 19–22: `__init__`

```python
class Recorder:
    def __init__(self):
        self._stream = None   # the open mic stream, or None when not recording
        self._chunks = []     # the blocks of audio received so far
```

## Lines 24–41: `start`

```python
def start(self):
    self._chunks = []         # forget any previous recording
    sd._terminate()           # shut PortAudio down (forgets the device list)...
    sd._initialize()          # ...and start it again (reads the current list and default mic)
```
`_terminate` and `_initialize` start with `_`: they are internal sounddevice functions, not
officially public. They're used because they're the only way to make PortAudio re-scan the
devices.

```python
    self._stream = sd.InputStream(
        samplerate=SAMPLE_RATE,   # ask for 16 kHz
        channels=1,               # mono
        dtype="float32",          # samples as 32-bit floats between -1.0 and 1.0
        callback=self._on_audio,  # function to call with each new block of audio
    )
```
Creates (but doesn't yet start) an input stream on the default microphone. sounddevice will
call `self._on_audio` from **its own audio thread** every few milliseconds.

```python
    try:
        self._stream.start()
    except Exception:
        self._stream.close()
        self._stream = None
        raise
```
Start capturing. If that fails (e.g. no permission), close the stream, forget it, and
`raise` with no argument re-raises the same error so `parole.py` can show it.

## Lines 43–45: `_on_audio`

```python
def _on_audio(self, block, frames, time, status):
    self._chunks.append(block.copy())
```
sounddevice requires this exact signature:
- `block` – a NumPy array of shape `(frames, 1)`: `frames` rows, 1 column (mono).
- `frames` – how many samples are in the block.
- `time` – timing info (unused here; note it shadows the `time` module name only inside this
  function, which is harmless because the module isn't imported in this file).
- `status` – flags such as "input overflow" (unused).

sounddevice **reuses the same memory** for the next block, so we must `copy()` it, otherwise
every chunk in the list would end up holding the latest audio. `list.append` is safe to call
from another thread in CPython.

## Lines 47–50: `snapshot`

```python
def snapshot(self):
    chunks = list(self._chunks)
    return np.concatenate(chunks).flatten() if chunks else np.zeros(0, dtype=np.float32)
```
Returns everything recorded so far **without stopping** (used by the live preview).
- `list(self._chunks)` makes a copy of the list, because the audio thread keeps appending to
  the original while we work.
- `np.concatenate(chunks)` stacks all `(frames, 1)` blocks into one `(total, 1)` array;
  `.flatten()` turns it into a 1-D array of shape `(total,)`.
- If nothing was recorded yet, return an empty float32 array instead of crashing
  (`np.concatenate([])` would raise an error).

## Lines 52–64: `stop`

```python
def stop(self):
    if self._stream is None:
        return np.zeros(0, dtype=np.float32)
```
Not recording → return empty audio.

```python
    stream = self._stream
    self._stream = None
    try:
        stream.stop()
    finally:
        stream.close()
```
Forget the stream first (so we're "not recording" even if something below fails), then stop
it; `finally` makes sure it's closed (mic released) even if `stop()` raises.

```python
    if not self._chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(self._chunks).flatten()
```
Return all the audio as one 1-D float32 array (or an empty one).
