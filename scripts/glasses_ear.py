"""The ear of the laptop-as-glasses: microphone → utterances, as WAV.

Two ways an utterance opens:

- **The wake word.** Speech is cut by an energy gate into provisional segments,
  and every half second the last 2.5 s of the current one goes through a small
  local Whisper with word timestamps. Nothing is shown and nothing is sent until
  a word is "Millia" (the backend's own spelling family judges the word). Then
  the segment starts at that word — mid-sentence is fine — the listening state
  lights, and the clip goes up with ``require_wake_word`` for the backend's
  second opinion. A segment that closes with no wake word is dropped unsent.
- **The follow-up window.** For a few seconds after Millia finishes a line, the
  next utterance needs no name: it is armed the moment the gate opens and goes
  up without ``require_wake_word``. Silence closes the window; a reply reopens it.

``Speaker``/``Voice`` are Millia's voice; only a new wake word cuts her off.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import queue
import subprocess
import threading
import time
import wave
from collections import deque
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from scripts.glasses_wake import is_wake_word

SAMPLE_RATE = 16_000
FRAME = 480  # 30 ms at 16 kHz
# Silence that ends an utterance. 0.75 s split "Ilya what was the / cleaning task
# that I did" into two clips (measured 2026-08-27); a wearer who thinks mid-sentence
# pauses longer than a breath. Siri waits about this long. --end-silence tunes it.
END_SILENCE_SECONDS = 1.6
END_FRAMES = int(END_SILENCE_SECONDS * SAMPLE_RATE / FRAME)


def end_frames_for(seconds: float) -> int:
    return max(1, int(seconds * SAMPLE_RATE / FRAME))


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(frame.astype(np.float32))))) if len(frame) else 0.0


SPOT_EVERY = 16  # frames between two looks at the provisional segment: ~0.5 s
SPOT_WINDOW = 83  # frames the spotter reads: ~2.5 s, longer than "Millia, report"
FOLLOW_UP_SECONDS = 4.0  # after Millia's line, the next utterance needs no name


class WakeSpotter(Protocol):
    def spot(self, samples: np.ndarray) -> int | None:
        """The sample index where the wake word starts, or None."""


class WhisperSpotter:
    """A small local Whisper with word timestamps. ``tiny`` runs in ~0.2 s per
    2.5 s window on an Apple-silicon CPU; the model is fetched once."""

    def __init__(self, model: str = "tiny") -> None:
        self.model_name = model
        self._model: Any = None

    def warm(self) -> None:
        """Load the model now, so the first "Millia" is not ten seconds late."""
        if self._model is None:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]

            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")

    def spot(self, samples: np.ndarray) -> int | None:
        self.warm()
        segments, _info = self._model.transcribe(samples, beam_size=1, word_timestamps=True, vad_filter=False)
        for segment in segments:
            for word in segment.words or []:
                if is_wake_word(word.word):
                    return int(word.start * SAMPLE_RATE)
        return None


def listen(
    frames: Iterable[np.ndarray],
    *,
    threshold: float | Callable[[], float] = 0.015,
    spotter: WakeSpotter | None = None,
    conversation_open: Callable[[], bool] = lambda: False,
    start_frames: int = 3,
    end_frames: int = END_FRAMES,
    pre_roll: int = 10,
    max_frames: int = 400,
    min_frames: int = 15,
    on_open: Callable[[], None] | None = None,
    on_frame: Callable[[float, float, bool], None] | None = None,
) -> Iterator[tuple[np.ndarray, bool]]:
    """Yield ``(samples, wake_required)`` per utterance Millia should hear.

    An energy gate over 30 ms frames, pure enough for a test to feed synthetic
    audio: ``threshold`` is RMS on float32 samples in [-1, 1] — a number, or a
    callable read per frame so the gate can rise while Millia speaks;
    ``start_frames`` loud frames open a segment, ``end_frames`` quiet ones close
    it, ``max_frames`` (12 s) closes it anyway, and a segment shorter than
    ``min_frames`` (450 ms) is noise and is dropped.

    With no ``spotter`` every segment is
    armed at once (the old behaviour: the backend judges). With one, a segment
    is provisional until the spotter finds the wake word in its tail; it is
    then cut to start at that word and armed. While ``conversation_open()`` the
    gate arms at once and the clip is marked as needing no wake word.
    ``on_frame``'s third value is "armed", so a meter lights only for speech
    that will be sent.
    """
    recent: deque[np.ndarray] = deque(maxlen=pre_roll)
    active: list[np.ndarray] = []
    armed = False
    wake_required = True
    loud_run = quiet_run = since_spot = 0

    def look() -> None:
        nonlocal active, armed
        window = active[-SPOT_WINDOW:]
        at = spotter.spot(np.concatenate(window)) if spotter is not None else None
        if at is None:
            return
        start = len(active) - len(window) + at // FRAME
        active = active[max(0, start - 3) :]  # three frames before the word: its onset survives
        armed = True
        if on_open is not None:
            on_open()

    for frame in frames:
        gate = threshold() if callable(threshold) else threshold
        level = rms(frame)
        loud = level >= gate
        if on_frame is not None:
            on_frame(level, gate, armed)
        if not active:
            recent.append(frame)
            loud_run = loud_run + 1 if loud else 0
            if loud_run >= start_frames:
                active = list(recent)
                quiet_run = since_spot = 0
                wake_required = not conversation_open()
                armed = spotter is None or not wake_required
                if armed and on_open is not None:
                    on_open()
            continue
        active.append(frame)
        quiet_run = 0 if loud else quiet_run + 1
        if not armed and conversation_open():
            # Millia went quiet while a provisional segment was already running
            # — her own voice through the speakers had opened it, and the wearer's
            # follow-up landed inside it (measured 2026-08-28: "it didn't
            # register"). Arm it now, no name needed, from 90 ms back: enough
            # for the wearer's onset, not enough to carry the tail of her voice
            # from the speaker into the clip.
            active = active[-3:]
            armed = True
            wake_required = False
            if on_open is not None:
                on_open()
        if not armed:
            since_spot += 1
            if since_spot >= SPOT_EVERY:
                since_spot = 0
                look()
            if not armed and len(active) > SPOT_WINDOW + pre_roll:
                active = active[-SPOT_WINDOW:]  # a long monologue: keep the tail, keep looking
        if quiet_run >= end_frames or (armed and len(active) >= max_frames):
            if not armed:
                look()  # the last half second was not looked at yet
            if armed and len(active) - quiet_run >= min_frames:
                yield np.concatenate(active), wake_required
            active = []
            recent.clear()
            loud_run = 0
            armed = False
    if active:
        if not armed:
            look()
        if armed and len(active) - quiet_run >= min_frames:
            yield np.concatenate(active), wake_required


def wav_bytes(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """16-bit mono PCM WAV, the `audio/wav` the backend accepts."""
    pcm = np.clip(samples, -1.0, 1.0)
    data = (pcm * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(data)
    return buf.getvalue()


def read_wav(path: str) -> np.ndarray:
    """A 16 kHz mono 16-bit WAV as float32 samples (what `feed` takes)."""
    with wave.open(path) as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError(f"{path}: need 16 kHz mono 16-bit (ffmpeg -ar 16000 -ac 1)")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


class Speaker:
    """Millia's voice. Non-blocking, and only a new wake word cuts it off."""

    def __init__(self, popen: Callable[..., Any] = subprocess.Popen) -> None:
        self._popen = popen
        self._proc: Any = None

    def speak(self, text: str) -> None:
        self.interrupt()
        if text:
            self._proc = self._popen(["say", text])

    def interrupt(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=2)  # reaped, not left as a zombie per utterance
        self._proc = None

    def wait(self) -> None:
        """Block until the current line is fully spoken (scripted runs pace on this)."""
        proc = self._proc
        if proc is not None:
            proc.wait()
            self._proc = None

    def is_speaking(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


class Voice:
    """Millia's voice through OpenAI text-to-speech, streamed to the speakers.

    ``gpt-4o-mini-tts`` streams its first audio in about 0.8 s and reads Malay as
    well as English (measured 2026-08-27; ``tts-1`` took 2.8 s, macOS ``say`` is
    instant but sounds like 1999). 24 kHz 16-bit mono PCM goes chunk by chunk to
    a ``sounddevice`` output stream on a thread, so listening continues, and
    ``interrupt()`` — a new wake word — stops it between chunks (100 ms).
    """

    RATE = 24_000
    CHUNK = 4_800  # 100 ms of 16-bit mono at 24 kHz

    def __init__(
        self,
        voice: str = "shimmer",
        model: str = "gpt-4o-mini-tts",
        *,
        speed: float = 1.2,
        stream: Callable[[str], Iterable[bytes]] | None = None,
        play: Callable[[Iterable[bytes], threading.Event], None] | None = None,
        log: Callable[[str], None] = print,
        on_first_audio: Callable[[float], None] | None = None,
        cache_dir: Path | None = None,
        instructions: str | None = None,
    ) -> None:
        self.voice = voice
        self.model = model
        self.speed = speed  # 1.0 is the provider's pace; a little faster reads as sure of itself
        # How to read, in words ("a tired guest at a hotel desk"): gpt-4o-mini-tts
        # takes it as `instructions`. Part of the cache key: a tone is another take.
        self.instructions = instructions
        self._stream = stream or self._openai_stream
        self._play = play or self._sounddevice_play
        self.log = log
        self.on_first_audio = on_first_audio  # ms from speak() to the first chunk: the latency instrument
        # A line spoken once is on disk; the next time it plays at once. A
        # rehearsal fills the cache, the recorded take never waits for the
        # provider (2026-08-27). Keyed by model, voice and text; a line cut
        # part-way is not written.
        self.cache_dir = cache_dir
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()

    def _cached(self, text: str) -> Iterable[bytes]:
        """The provider is asked at once (so its error surfaces here, not in the
        player); the chunks are kept and written when the line played to its end."""
        if self.cache_dir is None:
            return self._stream(text)
        key = hashlib.sha1(f"{self.model}|{self.voice}|{self.speed}|{self.instructions or ''}|{text}".encode()).hexdigest()
        path = self.cache_dir / f"{key}.pcm"
        if path.is_file():
            data = path.read_bytes()
            return [data[i : i + self.CHUNK] for i in range(0, len(data), self.CHUNK)]
        return self._keep(self._stream(text), path)

    def _keep(self, chunks: Iterable[bytes], path: Path) -> Iterator[bytes]:
        heard: list[bytes] = []
        for chunk in chunks:
            heard.append(chunk)
            yield chunk
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(heard))

    def _openai_stream(self, text: str) -> Iterator[bytes]:
        from openai import OpenAI

        client = OpenAI()
        tone: dict[str, Any] = {"instructions": self.instructions} if self.instructions else {}
        with client.audio.speech.with_streaming_response.create(
            model=self.model, voice=self.voice, input=text, response_format="pcm", speed=self.speed, **tone
        ) as response:
            yield from response.iter_bytes(self.CHUNK)

    def prepare(self, text: str) -> float:
        """Render a line to the cache now, without playing it, and say how many
        seconds it runs. A take calls this for every line before the first is
        spoken, so the provider is never in a gap between two people."""
        if not text:
            return 0.0
        size = sum(len(chunk) for chunk in self._cached(text))
        return size / (self.RATE * 2)  # 16-bit mono

    def _sounddevice_play(self, chunks: Iterable[bytes], cancel: threading.Event) -> None:
        import sounddevice as sd  # type: ignore[import-untyped]

        with sd.RawOutputStream(samplerate=self.RATE, channels=1, dtype="int16") as out:
            for chunk in chunks:
                if cancel.is_set():
                    return
                out.write(chunk)

    def speak(self, text: str) -> None:
        self.interrupt()
        if not text:
            return
        cancel = threading.Event()
        self._cancel = cancel
        started = time.monotonic()

        def timed(chunks: Iterable[bytes]) -> Iterator[bytes]:
            first = True
            for chunk in chunks:
                if first and self.on_first_audio is not None:
                    self.on_first_audio((time.monotonic() - started) * 1000)
                first = False
                yield chunk

        def work() -> None:
            try:
                self._play(timed(self._cached(text)), cancel)
            except Exception as exc:  # the voice must never take the ear down
                self.log(f"[voice] {exc}")

        self._thread = threading.Thread(target=work, daemon=True, name="glasses-voice")
        self._thread.start()

    def interrupt(self) -> None:
        self._cancel.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def wait(self) -> None:
        """Block until the current line is fully spoken (scripted runs pace on this)."""
        if self._thread is not None:
            self._thread.join()

    def is_speaking(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


class Ear:
    """Microphone → `on_utterance(wav_bytes, wake_required)` on the event loop,
    one call per utterance Millia should hear."""

    # While Millia speaks, her own voice reaches the microphone. The gate rises
    # by this factor so only close, loud speech - the wearer cutting in - opens
    # an utterance. (A Halo cancels its own speaker in hardware: on-device AEC.)
    SPEAKING_BOOST = 4.0

    def __init__(
        self,
        on_utterance: Callable[[bytes, bool], Any],
        *,
        loop: asyncio.AbstractEventLoop,
        threshold: float = 0.015,
        end_silence: float = END_SILENCE_SECONDS,
        spotter: WakeSpotter | None = None,
        follow_up: float = FOLLOW_UP_SECONDS,
        log: Callable[[str], None] = print,
        on_listening: Callable[[], None] | None = None,
        on_window: Callable[[bool], None] | None = None,
        is_speaking: Callable[[], bool] | None = None,
        on_frame: Callable[[float, float, bool], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.on_utterance = on_utterance
        self.loop = loop
        self.threshold = threshold
        self.end_frames = end_frames_for(end_silence)
        self.spotter = spotter
        self.follow_up = follow_up
        self.clock = clock
        self._open_until = 0.0
        self._was_speaking = False
        # A guest session (the reception scene) holds the ear open: every
        # utterance goes up without a name until the button closes it.
        self.hold_open = False
        self.on_frame = on_frame  # (rms, gate, open) every 30 ms: the mic instrument
        self.log = log
        self.on_listening = on_listening
        self.on_window = on_window  # True when the follow-up window opens, False when it closes
        self._window_open = False
        self.is_speaking = is_speaking or (lambda: False)
        self._frames: queue.Queue[np.ndarray | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stream: Any = None

    # ---- microphone thread

    def _on_audio(self, indata: np.ndarray, _frames: int, _time: Any, status: Any) -> None:
        if status:
            self.log(f"[ear] {status}")
        self._frames.put(indata[:, 0].copy())

    def _frame_iter(self) -> Iterator[np.ndarray]:
        while True:
            frame = self._frames.get()
            if frame is None:
                return
            yield frame

    def feed(self, samples: np.ndarray, *, then_quiet_seconds: float = END_SILENCE_SECONDS + 0.5) -> None:
        """Push audio through the ear as if the microphone heard it, then enough
        quiet to close the utterance. A WAV file stands in for a human."""
        for i in range(0, len(samples), FRAME):
            self._frames.put(samples[i : i + FRAME].astype(np.float32))
        for _ in range(int(then_quiet_seconds * SAMPLE_RATE / FRAME)):
            self._frames.put(np.zeros(FRAME, dtype=np.float32))

    def _tick(self) -> None:
        """Every frame: watch Millia's voice. The window opens on the
        speaking→quiet edge and closes `follow_up` seconds later; each change is
        told to `on_window`, so the ring and the glass can show it. Measured
        2026-08-28: the edge was watched only while a segment was open, so when
        her voice did not open one the window never opened — and nothing showed
        either way."""
        speaking = self.is_speaking()
        now = self.clock()
        if self._was_speaking and not speaking:
            self._open_until = now + self.follow_up
        self._was_speaking = speaking
        open_ = self.hold_open or (not speaking and now < self._open_until)
        if open_ != self._window_open:
            self._window_open = open_
            if self.on_window is not None:
                self.on_window(open_)

    def conversation_open(self) -> bool:
        """True for `follow_up` seconds after Millia's line ends: the next
        utterance needs no name."""
        self._tick()
        return self._window_open

    def _work(self) -> None:
        self.log('[ear] listening; say "Millia, ..."')

        def gate() -> float:
            self._tick()  # per frame, segment or not: the window's edge is never missed
            return self.threshold * (self.SPEAKING_BOOST if self.is_speaking() else 1.0)

        for samples, wake_required in listen(
            self._frame_iter(),
            threshold=gate,
            spotter=self.spotter,
            conversation_open=self.conversation_open,
            end_frames=self.end_frames,
            on_open=self.on_listening,
            on_frame=self.on_frame,
        ):
            self._open_until = 0.0  # the window is spent; Millia's reply opens the next
            self._tick()
            asyncio.run_coroutine_threadsafe(self.on_utterance(wav_bytes(samples), wake_required), self.loop)

    # ---- lifecycle

    def start(self, *, microphone: bool = True) -> None:
        if microphone:
            import sounddevice as sd

            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=FRAME, callback=self._on_audio
            )
            self._stream.start()
        self._thread = threading.Thread(target=self._work, daemon=True, name="glasses-ear")
        self._thread.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._frames.put(None)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def stopped(self) -> bool:
        return self._thread is None
