"""Speech-to-text with Whisper on the Apple Silicon GPU (via MLX).

How Whisper works, in two halves:
  - The encoder "listens": it turns 30 s of audio (shorter clips are padded
    with silence) into a grid of numbers describing the sound. This is the
    expensive part, about 1 s on an M4 for large-v3-turbo.
  - The decoder "writes": it reads that grid and produces text one token at a
    time. For a short sentence this is ~100 ms.

mlx_whisper.transcribe() runs the encoder twice when the language is unknown
(once to detect the language, once to transcribe). For clips up to 30 s we
call the two halves ourselves so the encoder runs only once.
"""

import os

# The model is already in ~/.cache/huggingface, so never contact the internet.
os.environ["HF_HUB_OFFLINE"] = "1"

import mlx.core as mx  # noqa: E402  (must come after setting HF_HUB_OFFLINE)
import mlx_whisper  # noqa: E402
import numpy as np  # noqa: E402
from mlx_whisper.audio import N_SAMPLES, log_mel_spectrogram, pad_or_trim  # noqa: E402
from mlx_whisper.decoding import DecodingOptions, decode  # noqa: E402
from mlx_whisper.load_models import load_model  # noqa: E402

from recorder import SAMPLE_RATE  # noqa: E402

MODEL = "mlx-community/whisper-large-v3-turbo"


class Transcriber:
    def __init__(self, model=MODEL):
        self.model_name = model
        self.model = None

    def warm_up(self):
        # Load the weights into memory once (~3 s) and run them on a second of
        # silence, so the GPU code is compiled before your first dictation.
        self.model = load_model(self.model_name, dtype=mx.float16)
        self.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))

    def transcribe(self, audio):
        """Return (text, language) for a 16 kHz mono float32 array."""
        if len(audio) > N_SAMPLES:
            return self._transcribe_long(audio)

        # Audio -> mel spectrogram (a picture of which frequencies are loud
        # over time) -> padded to 30 s -> encoder, run exactly once.
        mel = log_mel_spectrogram(pad_or_trim(mx.array(audio)), n_mels=self.model.dims.n_mels)
        features = self.model.encoder(mel[None].astype(mx.float16))

        # Ask the decoder which language token is most likely (fr, en, ...).
        _, language_probs = self.model.detect_language(features)
        language = max(language_probs[0], key=language_probs[0].get)

        result = decode(self.model, features, DecodingOptions(language=language, without_timestamps=True))[0]

        # Whisper sometimes "hears" words in noise (e.g. "Thank you."). Its own
        # rule: if it thinks there's no speech AND it's unsure of the text, drop it.
        if result.no_speech_prob > 0.6 and result.avg_logprob < -1.0:
            return "", language
        return clean(result.text), language

    def _transcribe_long(self, audio):
        # Over 30 s, let mlx_whisper slide its 30 s window over the audio.
        result = mlx_whisper.transcribe(audio, path_or_hf_repo=self.model_name, condition_on_previous_text=False)
        return clean(result["text"]), result.get("language")


def clean(text):
    """Trim spaces; treat punctuation-only output (e.g. "." on noise) as nothing."""
    text = text.strip()
    return text if any(c.isalnum() for c in text) else ""
