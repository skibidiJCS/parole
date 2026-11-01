"""Voice activity detection with Silero VAD: did anyone speak, and when?

Whisper always writes *something*, even for silence or background noise
("Thank you.", or a word from your vocabulary). Silero VAD is a tiny model
(~5-20 ms per dictation on one CPU core) trained only to tell speech from
non-speech, so we ask it first and skip Whisper when nobody spoke.

It also says where the speech is, which we use to cut the recording into
pieces at pauses: silence around and between them is dropped, each piece
(usually a sentence) gets its own language detection, so French and English
sentences can follow each other, and no piece is longer than MAX_CHUNK
seconds, since Whisper reads 30 s at a time.
"""

import torch
from silero_vad import get_speech_timestamps, load_silero_vad

from recorder import SAMPLE_RATE

PADDING = 0.2  # seconds kept around speech so first/last sounds aren't clipped
MAX_GAP = 0.6  # seconds between padded spans; a longer gap starts a new piece
PAUSE = MAX_GAP + 2 * PADDING  # the silence that actually separates two pieces (1 s)
MAX_CHUNK = 28  # seconds per piece; Whisper's window is 30


class VoiceDetector:
    def __init__(self):
        torch.set_num_threads(1)  # one core is plenty for this model and saves battery
        self.model = load_silero_vad()

    def spans(self, audio):
        """Where the speech is: a list of {"start": sample, "end": sample}."""
        return get_speech_timestamps(torch.from_numpy(audio), self.model, sampling_rate=SAMPLE_RATE)

    def speech_pieces(self, audio):
        """Where to cut: a list of (start, end) sample positions, empty if nobody spoke."""
        spans = self.spans(audio)
        padding, max_gap, max_len = (int(s * SAMPLE_RATE) for s in (PADDING, MAX_GAP, MAX_CHUNK))

        # Merge speech spans into pieces, starting a new piece after a long
        # pause or when the piece would get too long.
        pieces = []
        for span in spans:
            start, end = max(0, span["start"] - padding), min(len(audio), span["end"] + padding)
            if pieces and start - pieces[-1][1] < max_gap and end - pieces[-1][0] <= max_len:
                pieces[-1][1] = end
            else:
                pieces.append([start, end])

        # Someone talking non-stop for over MAX_CHUNK seconds: cut evenly.
        return [(cut, min(cut + max_len, end)) for start, end in pieces for cut in range(start, end, max_len)]
