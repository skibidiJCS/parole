"""Parole: a menu bar app. Hold Shift + Right Command, speak, release,
and the text is pasted into the focused app.

    open /Applications/Parole.app          # normal use (see setup.py)
    .venv/bin/python -u parole.py          # from Terminal, with a live log

Three threads are involved:
  - The main thread belongs to AppKit (via rumps): it draws the menu bar icon
    and the menu. macOS only allows UI changes from this thread, so the other
    threads ask it to update the icon with AppHelper.callAfter().
  - pynput's listener thread gets key events and starts/stops the mic.
    It must stay fast, or macOS considers the key handler stuck.
  - A worker thread loads the Whisper model, then waits for recordings and
    transcribes + pastes them. MLX wants the model used from the thread that
    loaded it, so all Whisper work happens here, including the live preview
    it refreshes every LIVE_INTERVAL seconds while you speak.
A queue hands "a recording started" and finished recordings to the worker.
"""

import os
import queue
import subprocess
import sys
import threading
import time

import rumps
from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSColor,
    NSImage,
    NSPasteboard,
    NSPasteboardTypeString,
)
from PyObjCTools import AppHelper

import context
from bubble import Bubble
from cleanup import apply_corrections, join_pieces, remove_fillers, remove_repeats
from hotkey import Shortcut
from learning import Learner
from paster import paste_text
from recorder import SAMPLE_RATE, Recorder
from spacing import Spacer
from transcriber import Transcriber
from vocabulary import Vocabulary
from voice import PADDING, PAUSE, VoiceDetector

MIN_SECONDS = 0.3  # shorter recordings are treated as accidental
TAP_SECONDS = 0.3  # a press shorter than this starts hands-free recording
MAX_HANDS_FREE = 10 * 60  # seconds; hands-free recording stops by itself after this
LIVE_INTERVAL = 0.5  # seconds between live-preview refreshes while recording
MAX_PENDING = 20  # seconds of speech without a pause before we keep it anyway
HESITATION = 1.0  # seconds; a pause this long mid-sentence is written "..."
MISSED_SPEECH = 0.8  # seconds of speech left after the text ends before we transcribe it again
READY = "Ready: hold ⇧ + right ⌘ and speak"
LOG_PATH = os.path.expanduser("~/Library/Logs/Parole.log")

# SF Symbols (the icon set macOS itself uses) for each state.
ICONS = {
    "loading": "hourglass",
    "idle": "mic",
    "recording": "mic.fill",
    "hands_free": "mic.circle.fill",
    "transcribing": "waveform",
    "error": "exclamationmark.triangle",
}


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


def check_audio(audio):
    """Return None if the audio is worth transcribing, else the reason it isn't."""
    seconds = len(audio) / SAMPLE_RATE
    if seconds < MIN_SECONDS:
        return f"too short ({seconds:.2f}s), hold the keys while you speak"
    if not audio.any():
        # macOS hands out pure zeros instead of an error when access is denied.
        return "the mic only gives silence; allow Microphone access in Privacy & Security"
    return None


def transcribe_speech(transcriber, voice, audio, prompt="", before=""):
    """Transcribe the speech in `audio` (any length), continuing the text `before`.

    Returns (all the text, language of the first new piece). The audio is
    cut at pauses; join_pieces glues the pieces back, keeping a sentence
    going through a pause and writing a long one as "...".
    Whisper sometimes skips part of a piece (after a pause, or when you switch
    language): then the piece is cut where the skipped speech starts and ends,
    and each part is transcribed on its own.
    """
    text, first_language = before, None
    pieces = [(start, end, True) for start, end in voice.speech_pieces(audio)]
    previous_end = 0  # `audio` starts right after the text `before`
    while pieces:
        start, end, check = pieces.pop(0)
        piece, language, covered = transcriber.transcribe(audio[start:end], prompt)
        cuts = missed_speech(voice, audio[start:end], covered) if check and piece else []
        if cuts:
            bounds = [start] + [start + cut for cut in cuts] + [end]
            pieces[:0] = [(a, b, False) for a, b in zip(bounds, bounds[1:])]
            continue
        if piece:
            pause = (start - previous_end) / SAMPLE_RATE + 2 * PADDING  # both pieces carry padding
            text = join_pieces(text, piece, hesitation=pause >= HESITATION)
            first_language = first_language or language
        previous_end = end
    return text, first_language


def missed_speech(voice, audio, covered):
    """Where to cut a piece so the speech Whisper skipped gets its own turn ([] if none).

    `covered` is the (start, end) seconds the text came from; any stretch
    outside them holding more than MISSED_SPEECH seconds of speech was skipped.
    """
    edges = [0] + [int(t * SAMPLE_RATE) for span in covered for t in span] + [len(audio)]
    cuts = []
    for gap_start, gap_end in zip(edges[::2], edges[1::2]):  # the stretches between covered ones
        if gap_end - gap_start < MISSED_SPEECH * SAMPLE_RATE:
            continue
        speech = sum(span["end"] - span["start"] for span in voice.spans(audio[gap_start:gap_end]))
        if speech > MISSED_SPEECH * SAMPLE_RATE:
            cuts += [edge for edge in (gap_start, gap_end) if 0 < edge < len(audio)]
    return sorted(set(cuts))


class LivePreview:
    """What the live preview knows about the recording in progress (worker thread only)."""

    def __init__(self):
        self.done_samples = 0  # audio before this point is transcribed for good...
        self.done = ""  # ...into this text
        self.language = None
        self.preview = ""  # done + the piece in progress, re-transcribed each refresh

    def text(self):
        return self.preview or self.done


class Parole(rumps.App):
    def __init__(self, log_transcripts=True):
        super().__init__("Parole", quit_button=None)
        self.log_transcripts = log_transcripts
        # Items without a callback are greyed out: they're status lines.
        self.status_item = rumps.MenuItem("Loading the speech model…")
        self.last_item = rumps.MenuItem("No dictation yet")
        self.fast_item = rumps.MenuItem("Fast mode", callback=self.toggle_fast)
        self.fast_item.state = True
        self.repeats_item = rumps.MenuItem("Clean up fillers, repeats & corrections", callback=self.toggle_repeats)
        self.repeats_item.state = True
        self.live_item = rumps.MenuItem("Live preview", callback=self.toggle_live)
        self.live_item.state = True
        self.learn_item = rumps.MenuItem("Learn from corrections", callback=self.toggle_learn)
        self.learn_item.state = True
        self.menu = [
            self.status_item,
            self.last_item,
            None,  # separator
            rumps.MenuItem("Copy last dictation", callback=self.copy_last),
            rumps.MenuItem("Edit vocabulary…", callback=self.edit_vocabulary),
            self.fast_item,
            self.repeats_item,
            self.live_item,
            self.learn_item,
            None,
            rumps.MenuItem("Quit Parole", callback=self.quit),
        ]

        self.recorder = Recorder()
        self.recordings = queue.Queue()  # items: (audio, time the keys were released)
        self.is_recording = False
        self.hands_free = False  # recording continues after the keys are released
        self.ignore_release = False  # the press that stopped hands-free mode
        self.pressed_at = 0.0
        self.auto_stop = None  # timer that ends a forgotten hands-free recording
        # The key listener, the auto-stop timer and Quit can all touch the
        # recording state; the lock makes them take turns.
        self.lock = threading.Lock()
        self.last_text = ""  # kept in memory only, for "Copy last dictation"
        self.transcriber = Transcriber()
        self.voice = None  # loaded by the worker, with Whisper
        self.vocabulary = Vocabulary()
        self.vocabulary.ensure_file()
        self.spacer = Spacer()
        self.bubble = Bubble()
        self.live = None  # LivePreview while recording with the preview on
        self.context = context.Context()  # the text around the cursor (worker thread only)
        self.learner = Learner(self.vocabulary, on_learned=self.learned)
        self.shortcut = Shortcut(
            on_start=self.start_recording, on_stop=self.stop_recording, on_cancel=self.cancel_recording
        )

    def run(self):
        # Menu bar only: no Dock icon, and the app never takes focus from the
        # app you're dictating into.
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        threading.Thread(target=self.work, daemon=True).start()
        super().run()

    # --- UI (any thread can call show; _show runs on the main thread) -------

    def show(self, state, status=None, last=None):
        AppHelper.callAfter(self._show, state, status, last)

    def _show(self, state, status, last):
        button = self._nsapp.nsstatusitem.button()
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(ICONS[state], f"Parole: {state}")
        image.setTemplate_(True)  # let macOS colour it to match the menu bar
        button.setImage_(image)
        button.setTitle_("")
        red = state in ("recording", "hands_free")
        button.setContentTintColor_(NSColor.systemRedColor() if red else None)
        if status:
            self.status_item.title = status
        if last:
            self.last_item.title = last

    # --- Menu callbacks (main thread) --------------------------------------

    def toggle_fast(self, item):
        item.state = not item.state
        self.transcriber.fast = bool(item.state)
        log(f"Fast mode {'on' if item.state else 'off'}")

    def toggle_repeats(self, item):
        item.state = not item.state
        log(f"Clean up {'on' if item.state else 'off'}")

    def toggle_live(self, item):
        item.state = not item.state
        log(f"Live preview {'on' if item.state else 'off'}")

    def toggle_learn(self, item):
        item.state = not item.state
        log(f"Learn from corrections {'on' if item.state else 'off'}")

    def copy_last(self, _):
        if self.last_text:
            pasteboard = NSPasteboard.generalPasteboard()
            pasteboard.clearContents()
            pasteboard.setString_forType_(self.last_text, NSPasteboardTypeString)

    def edit_vocabulary(self, _):
        subprocess.Popen(["open", "-t", self.vocabulary.path])  # opens in TextEdit

    def quit(self, _):
        self.shortcut.stop()
        if self.auto_stop:
            self.auto_stop.cancel()
        try:
            self.recorder.stop()  # in case Quit is clicked mid-recording
        except Exception as error:
            log(f"Could not close the microphone: {error}")
        rumps.quit_application()

    # --- Shortcut callbacks (pynput's thread: keep them quick) -------------
    #
    # Two ways to dictate with the same shortcut:
    #   hold  -> push-to-talk: recording stops when you let go
    #   tap   -> hands-free: recording continues; tap again to stop

    def start_recording(self):  # shortcut pressed
        with self.lock:
            if self.hands_free:
                # This press ends a hands-free recording; its release does nothing.
                self.hands_free = False
                self.ignore_release = True
                self.finish_recording()
                return
            try:
                self.recorder.start()
            except Exception as error:
                log(f"Could not open the microphone: {error}")
                self.show("error", "Microphone unavailable; check Privacy & Security > Microphone")
                return
            self.is_recording = True
            self.pressed_at = time.perf_counter()
            self.recordings.put("start")  # wakes the worker for the live preview
        self.show("recording", "Recording…")

    def stop_recording(self):  # shortcut released
        with self.lock:
            if self.ignore_release:
                self.ignore_release = False
                return
            if not self.is_recording:
                return
            if time.perf_counter() - self.pressed_at < TAP_SECONDS:
                self.hands_free = True  # a tap: keep recording
                self.auto_stop = threading.Timer(MAX_HANDS_FREE, self.stop_forgotten)
                self.auto_stop.daemon = True
                self.auto_stop.start()
                self.show("hands_free", "Hands-free: tap ⇧ + right ⌘ again to stop")
                return
            self.finish_recording()

    def cancel_recording(self):  # another key pressed while holding the shortcut
        with self.lock:
            if not self.is_recording or self.hands_free:
                return
            try:
                self.recorder.stop()  # throw the audio away
            except Exception as error:
                log(f"Could not close the microphone: {error}")
            self.is_recording = False
        log("Cancelled: the shortcut was part of another key combination")
        self.show("idle", READY)

    def stop_forgotten(self):  # timer thread
        with self.lock:
            if not self.hands_free:
                return
            self.hands_free = False
            log(f"Hands-free recording stopped after {MAX_HANDS_FREE // 60} minutes")
            self.finish_recording()

    def finish_recording(self):
        """Stop the mic and queue the audio for the worker. Call with the lock held."""
        if self.auto_stop:
            self.auto_stop.cancel()
            self.auto_stop = None
        released_at = time.perf_counter()
        try:
            audio = self.recorder.stop()
        except Exception as error:
            log(f"Could not finish recording: {error}")
            self.show("error", "Recording failed; try again")
            return
        finally:
            self.is_recording = False
        self.show("transcribing", "Transcribing…")
        self.recordings.put((audio, released_at))

    def learned(self, heard, wanted):  # learner's timer thread, or the worker
        log(f"Learned: {heard} -> {wanted}" if self.log_transcripts else "Learned a correction")
        AppHelper.callAfter(setattr, self.last_item, "title", f"Learned: {heard} → {wanted}")

    # --- Worker thread -----------------------------------------------------

    def work(self):
        self.show("loading")
        log("Loading the Whisper model...")
        start = time.perf_counter()
        try:
            self.transcriber.warm_up()
            self.voice = VoiceDetector()
        except Exception as error:
            log(f"Could not load the offline model: {error}")
            self.show("error", "Speech model failed to load; see ~/Library/Logs/Parole.log")
            return
        log(f"Model ready in {time.perf_counter() - start:.1f}s")

        # Only listen to the keyboard once we can actually transcribe.
        self.shortcut.start()
        if self.shortcut.trusted:
            self.show("idle", READY)
        else:
            log("Accessibility is not granted: the shortcut and pasting won't work.")
            self.show("error", "Allow Accessibility + Input Monitoring, then reopen Parole")
            # Ask macOS to show its "would like to control this computer" prompt,
            # which also adds Parole to the list in System Settings.
            AppHelper.callAfter(AXIsProcessTrustedWithOptions, {kAXTrustedCheckOptionPrompt: True})

        while True:
            try:
                # Idle: wait for a recording, using no CPU. Recording with the
                # live preview on: wake up every LIVE_INTERVAL to refresh it.
                item = self.recordings.get(timeout=LIVE_INTERVAL if self.live else None)
            except queue.Empty:
                item = "refresh"
            try:
                if item == "start":
                    self.context = context.read()  # for the prompt; read again before pasting
                    if self.live_item.state:
                        self.live = LivePreview()
                        AppHelper.callAfter(self.bubble.show, "Listening…")
                elif item == "refresh":
                    self.refresh_live()
                else:
                    self.dictate(*item)
            except Exception as error:  # never let one bad dictation kill the worker
                log(f"Unexpected error: {error}")
                self.show("error", f"Error: {error}")
                self.live = None
                AppHelper.callAfter(self.bubble.hide)

    def transcribe_speech(self, audio, before=""):
        prompt = self.vocabulary.prompt(extra=self.context.terms)
        return transcribe_speech(self.transcriber, self.voice, audio, prompt, before)

    def tidy(self, text):
        if self.repeats_item.state:
            # "Um, I- I think" -> "I think"; "Tuesday, sorry, Wednesday" -> "Wednesday"
            text = remove_repeats(apply_corrections(remove_fillers(text)))
        return self.vocabulary.fix(text)

    def refresh_live(self):
        live = self.live
        if not self.is_recording:  # cancelled, or the mic failed
            self.live = None
            AppHelper.callAfter(self.bubble.hide)
            return
        rest = self.recorder.snapshot()[live.done_samples :]
        spans = self.voice.spans(rest) if len(rest) > SAMPLE_RATE // 2 else []
        if not spans:
            return
        speech_end = spans[-1]["end"]
        if len(rest) - speech_end > PAUSE * SAMPLE_RATE or speech_end > MAX_PENDING * SAMPLE_RATE:
            # A pause: transcribe what came before it for good and never look at
            # it again, so the end of a long dictation has little left to do.
            end = min(len(rest), speech_end + int(PADDING * SAMPLE_RATE))
            live.done, language = self.transcribe_speech(rest[:end], live.done)
            live.language = live.language or language
            live.done_samples += end
            live.preview = ""
        else:
            live.preview, _ = self.transcribe_speech(rest, live.done)
        AppHelper.callAfter(self.bubble.show, self.tidy(live.text()) or "Listening…")

    def dictate(self, audio, released_at):
        try:
            self._dictate(audio, released_at)
        finally:
            AppHelper.callAfter(self.bubble.hide)

    def _dictate(self, audio, released_at):
        live, self.live = self.live, None
        problem = check_audio(audio)
        if problem:
            log(f"Skipped: {problem}")
            self.show("idle", f"Skipped: {problem}")
            return

        # Sentences the live preview already finished are reused; only the rest
        # (usually the last sentence) is transcribed now.
        transcribe_start = time.perf_counter()
        done_samples, done, done_language = (live.done_samples, live.done, live.language) if live else (0, "", None)
        text, language = self.transcribe_speech(audio[done_samples:], done)
        language = done_language or language
        if not text:
            log("Skipped: no speech detected")
            self.show("idle", "Skipped: no speech detected")
            return
        text = self.tidy(text)
        if text[-1:].isalnum():
            text += "."  # Whisper sometimes leaves the last sentence open
        transcribed_at = time.perf_counter()
        if not text:
            log("Nothing recognized")
            self.show("idle", "Nothing recognized; try again")
            return
        self.last_text = text
        log(f"[{language}] {text if self.log_transcripts else f'{len(text)} characters'}")

        try:
            # A physically held Shift would turn Cmd+V into Cmd+Shift+V.
            if not self.shortcut.released.wait(timeout=2):
                raise RuntimeError("release Shift and Right Command, then try again")
            here = context.read()
            text = context.fit(text, here, names=self.vocabulary.words())  # "go home" mid-sentence, no "." in a search box...
            self.last_text = text
            self.learner.finish()  # last look at the previous dictation before this one lands
            pasted = self.spacer.prefix() + text + context.space_after(text, here)
            paste_sent_at = paste_text(pasted)
            self.spacer.pasted(pasted)
            if self.learn_item.state:
                self.learner.watch(here, text)
        except Exception as error:
            log(f"Paste failed: {error}")
            self.show("error", "Paste failed; use Copy last dictation", last=f"Last: {text[:40]}")
            return

        total_ms = (paste_sent_at - released_at) * 1000
        log(
            f"  audio {len(audio) / SAMPLE_RATE:.1f}s, {done_samples / SAMPLE_RATE:.1f}s done live, "
            f"last {(len(audio) - done_samples) / SAMPLE_RATE:.1f}s at release | latency {total_ms:.0f} ms "
            f"(transcribe {(transcribed_at - transcribe_start) * 1000:.0f} ms via {self.transcriber.last_path}, "
            f"paste {(paste_sent_at - transcribed_at) * 1000:.0f} ms)"
        )
        self.show("idle", READY, last=f"Last: {total_ms:.0f} ms ({self.transcriber.last_path}, {language})")


def main():
    in_terminal = sys.stdout is not None and sys.stdout.isatty()
    if not in_terminal:
        # Started as Parole.app: there's no Terminal to print to, so append to
        # a log file instead. Transcripts stay out of it (timings and errors only).
        sys.stdout = sys.stderr = open(LOG_PATH, "a", buffering=1)
    Parole(log_transcripts=in_terminal).run()


if __name__ == "__main__":
    main()
