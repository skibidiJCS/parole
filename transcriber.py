"""Speech-to-text with Whisper on the Apple Silicon GPU (via MLX).

How Whisper works, in two halves:
  - The encoder "listens": it turns the audio into a grid of numbers
    describing the sound. This is the expensive part.
  - The decoder "writes": it reads that grid and produces text one token at a
    time (~10 ms per token).

Whisper was trained on 30 s windows, so normally every clip is padded with
silence to 30 s and the encoder costs ~1 s on an M4 whatever you say.

Fast mode shrinks the window to the clip length + 1 s (at least 6 s: below
that, language detection mistakes short French for English), so the encoder
only works on real audio (~150-300 ms). The catch: without the long silence, the
decoder doesn't realise the speech has ended and repeats it. We ask for
timestamps, split the output into segments, and stop at the first segment
that is an exact repeat or a timestamp past the end of the window. Loops
inside one segment ("on se voit demain, on se voit demain, ...") are cut at
the second of three identical copies.
Whenever fast mode is unsure (nothing found, low confidence, or the text was
cut off by the token limit) we retry with the full 30 s window.

We call the encoder and decoder ourselves rather than mlx_whisper.transcribe(),
which would run the encoder twice (once to detect the language) and keep its
own second copy of the model. Clips must be at most 30 s; voice.py cuts longer
recordings into pieces.
"""

import math
import os
import re
from contextlib import contextmanager

# The model is already in ~/.cache/huggingface, so never contact the internet.
os.environ["HF_HUB_OFFLINE"] = "1"

import mlx.core as mx  # noqa: E402  (must come after setting HF_HUB_OFFLINE)
import numpy as np  # noqa: E402
from mlx_whisper.audio import log_mel_spectrogram, pad_or_trim  # noqa: E402
from mlx_whisper.decoding import DecodingOptions, decode  # noqa: E402
from mlx_whisper.load_models import load_model  # noqa: E402
from mlx_whisper.tokenizer import get_tokenizer  # noqa: E402

from recorder import SAMPLE_RATE  # noqa: E402

MODEL = "mlx-community/whisper-large-v3-turbo"
FULL_WINDOW = 30  # seconds, what Whisper was trained on
MIN_WINDOW = 6  # seconds; shorter windows misdetect short French clips as English
LANGUAGES = ("en", "fr")  # the languages you speak; detection picks between these
MEL_FRAMES_PER_SECOND = 100  # the encoder halves this: 50 features per second
SECONDS_PER_TIMESTAMP = 0.02  # each timestamp token is 20 ms
# Average token log-probability below which fast mode is "unsure". Measured:
# speech -0.6 to -1.05 (repeats included), noise hallucinations about -1.6.
FAST_MIN_LOGPROB = -1.2


class Transcriber:
    def __init__(self, model=MODEL):
        self.model_name = model
        self.model = None
        self.tokenizer = None
        self.fast = True
        self.last_path = None  # "fast" or "full": which path produced the text

    def warm_up(self):
        # Load the weights into memory once (~3 s) and run them on a second of
        # silence. Fast mode finds nothing in silence and falls back to the
        # full window, so both code paths are ready before your first dictation.
        self.model = load_model(self.model_name, dtype=mx.float16)
        self.tokenizer = get_tokenizer(self.model.is_multilingual, num_languages=self.model.num_languages)
        self.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))

    def transcribe(self, audio, prompt=""):
        """Return (text, language) for up to 30 s of 16 kHz mono float32 audio.

        `prompt` is text Whisper reads as if it came just before the audio.
        Listing names and jargon there makes it reuse those spellings.
        """
        prompt = prompt or None

        # Audio -> mel spectrogram (a picture of which frequencies are loud
        # over time), padded to 30 s. Fast mode only uses the start of it.
        mel = log_mel_spectrogram(pad_or_trim(mx.array(audio)), n_mels=self.model.dims.n_mels)
        if self.fast:
            window = min(FULL_WINDOW, max(MIN_WINDOW, math.ceil(len(audio) / SAMPLE_RATE) + 1))
            text, language = self._transcribe_short(mel, window, prompt)
            if text:
                self.last_path = "fast"
                return text, language
        self.last_path = "full"
        return self._transcribe_full(mel, prompt)

    def _encode(self, mel, window):
        """Run the encoder once, then detect the language from its output."""
        frames = window * MEL_FRAMES_PER_SECOND
        features = self.model.encoder(mel[None, :frames].astype(mx.float16))
        # Ask the decoder which of your languages is most likely.
        _, language_probs = self.model.detect_language(features)
        return features, max(LANGUAGES, key=language_probs[0].get)

    def _transcribe_full(self, mel, prompt):
        features, language = self._encode(mel, FULL_WINDOW)
        options = DecodingOptions(language=language, without_timestamps=True, prompt=prompt)
        result = decode(self.model, features, options)[0]
        # Whisper sometimes "hears" words in noise (e.g. "Thank you."). Its own
        # rule: if it thinks there's no speech AND it's unsure of the text, drop it.
        if result.no_speech_prob > 0.6 and result.avg_logprob < -1.0:
            return "", language
        return clean(result.text), language

    def _transcribe_short(self, mel, window, prompt):
        """Fast mode. Returns ("", language) whenever the result can't be trusted."""
        # Cap the tokens so a repeating decoder stops quickly (~6 per second of
        # audio is plenty for speech, plus room for the timestamp tokens).
        sample_len = window * 6 + 12
        with self._encoder_window(window * MEL_FRAMES_PER_SECOND // 2):
            features, language = self._encode(mel, window)
            options = DecodingOptions(
                language=language, without_timestamps=False, sample_len=sample_len, prompt=prompt
            )
            result = decode(self.model, features, options)[0]

        if not result.avg_logprob >= FAST_MIN_LOGPROB:  # also catches "not a number"
            return "", language  # probably noise; let the full window decide
        segments, stopped = self._segments_within(result.tokens, window)
        text, looped = first_copy(" ".join(segments))
        if not (stopped or looped) and len(result.tokens) >= sample_len:
            return "", language  # the token cap cut the speech off
        return clean(text), language

    @contextmanager
    def _encoder_window(self, n_features):
        """Temporarily make the model accept a window shorter than 30 s.

        The encoder adds a fixed "position" vector to each of its 1500 time
        steps; with fewer steps we use only the first ones. mlx_whisper also
        checks n_audio_ctx to recognise already-encoded audio.
        """
        encoder, dims = self.model.encoder, self.model.dims
        full_embedding, full_ctx = encoder._positional_embedding, dims.n_audio_ctx
        encoder._positional_embedding = full_embedding[:n_features]
        dims.n_audio_ctx = n_features
        try:
            yield
        finally:
            encoder._positional_embedding = full_embedding
            dims.n_audio_ctx = full_ctx

    def _segments_within(self, tokens, window):
        """Split the output into segments and stop where the repeating starts.

        With timestamps the output looks like
            <0.00> Okay sounds good.<1.44><8.44> Okay sounds good.<10.44> ...
        When the decoder starts repeating itself, either the timestamps jump
        past the real audio (<8.44> on a 3 s clip) or the next segment is an
        exact copy of the previous one. Returns (segments, stopped_early).
        """
        first_timestamp = self.tokenizer.timestamp_begin
        segments, words = [], []
        for token in tokens:
            if token < first_timestamp:
                words.append(token)
                continue
            # A timestamp token closes the segment in progress.
            if words:
                text = self.tokenizer.decode(words).strip()
                if segments and text == segments[-1]:
                    return segments, True
                segments.append(text)
                words = []
            if (token - first_timestamp) * SECONDS_PER_TIMESTAMP > window:
                return segments, True
        if words:
            segments.append(self.tokenizer.decode(words).strip())
        return segments, False


def first_copy(text):
    """Cut a decoder loop: "a b, a b, a b, ..." -> "a b". Returns (text, looped).

    Needs three identical copies in a row, so a phrase you really said twice
    is left alone (cleanup.py removes that one more carefully).
    """
    words = text.split()
    plain = [re.sub(r"[^\w']", "", word.lower()) for word in words]
    for end in range(3, len(words) + 1):
        for size in range(1, end // 3 + 1):
            a, b, c = (plain[end - k * size : end - (k - 1) * size] for k in (3, 2, 1))
            if a == b == c:
                return " ".join(words[: end - 2 * size]).rstrip(",;:"), True
    return text, False


def clean(text):
    """Trim spaces; treat punctuation-only output (e.g. "." on noise) as nothing."""
    text = text.strip()
    return text if any(c.isalnum() for c in text) else ""
