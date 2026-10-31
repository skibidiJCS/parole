"""Microphone capture, in memory only.

The mic stream is opened when recording starts and closed when it stops,
so between dictations the mic is off (no orange dot, no CPU use).
"""

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000  # Whisper expects 16 kHz mono audio


class Recorder:
    def __init__(self):
        self._stream = None
        self._chunks = []

    def start(self):
        self._chunks = []
        # sounddevice calls _on_audio from its own thread every few milliseconds
        # with the newest block of samples.
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self._on_audio,
        )
        try:
            self._stream.start()
        except Exception:
            self._stream.close()
            self._stream = None
            raise

    def _on_audio(self, block, frames, time, status):
        # `block` is reused by sounddevice, so keep a copy.
        self._chunks.append(block.copy())

    def snapshot(self):
        """The audio recorded so far, without stopping (for the live preview)."""
        chunks = list(self._chunks)  # copy: the audio thread keeps appending
        return np.concatenate(chunks).flatten() if chunks else np.zeros(0, dtype=np.float32)

    def stop(self):
        """Stop recording and return the audio as a 1-D float32 array."""
        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        stream = self._stream
        self._stream = None
        try:
            stream.stop()
        finally:
            stream.close()
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._chunks).flatten()
