"""Voice activity detection with Silero VAD: did anyone speak, and when?

Whisper always writes *something*, even for silence or background noise
("Thank you.", or a word from your vocabulary). Silero VAD is a tiny model
(~2 MB, ~5-20 ms per dictation on one CPU core) trained only to tell speech
from non-speech, so we ask it first and skip Whisper when nobody spoke.
It also says where the speech starts and ends, so we can cut the silence
around it, which makes fast mode's window shorter and faster.
"""

import torch
from silero_vad import get_speech_timestamps, load_silero_vad

from recorder import SAMPLE_RATE

PADDING = 0.2  # seconds kept around the speech so first/last sounds aren't clipped


class VoiceDetector:
    def __init__(self):
        torch.set_num_threads(1)  # one core is plenty for this model and saves battery
        self.model = load_silero_vad()

    def trim(self, audio):
        """Return the audio from the first to the last speech, or None if nobody spoke."""
        spans = get_speech_timestamps(torch.from_numpy(audio), self.model, sampling_rate=SAMPLE_RATE)
        if not spans:
            return None
        padding = int(PADDING * SAMPLE_RATE)
        return audio[max(0, spans[0]["start"] - padding) : spans[-1]["end"] + padding]
