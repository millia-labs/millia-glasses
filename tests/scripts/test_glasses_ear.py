"""scripts/glasses_ear.py — microphone → utterances that begin with "Millia".

USER-VISIBLE ARTIFACTS: which stretches of sound become an utterance (and
which are dropped), the WAV bytes the backend receives, and whether Millia's
voice is cut off. No microphone here: the segmenter is a pure generator over
frames, the gate is a function of text, the speaker takes a fake Popen.
"""

from __future__ import annotations

import wave
from io import BytesIO
from typing import Any

import numpy as np
import pytest

import scripts.glasses_ear as ear

pytestmark = pytest.mark.unit


def _frames(*parts: tuple[float, float]) -> list[np.ndarray]:
    """(seconds, amplitude) pairs → 30 ms frames of noise at that amplitude."""
    rng = np.random.default_rng(1)
    out: list[np.ndarray] = []
    for seconds, amp in parts:
        n = int(seconds * ear.SAMPLE_RATE / ear.FRAME)
        for _ in range(n):
            out.append((rng.standard_normal(ear.FRAME) * amp).astype(np.float32))
    return out


def _gate(frames: list[np.ndarray], **kwargs: Any) -> list[np.ndarray]:
    """The energy gate as it ships: `listen` with no spotter arms every segment
    at once, so this is the segmenter alone, without the wake-word cut."""
    return [samples for samples, _wake_required in ear.listen(frames, **kwargs)]


def test_one_utterance_between_two_silences_becomes_one_segment_with_pre_roll() -> None:
    frames = _frames((1.0, 0.001), (1.5, 0.2), (2.0, 0.001))
    segments = list(_gate(frames))
    assert len(segments) == 1
    seconds = len(segments[0]) / ear.SAMPLE_RATE
    # 1.5 s of speech + 0.3 s pre-roll + 1.6 s trailing quiet, give or take a frame
    assert 3.3 <= seconds <= 3.5, seconds


def test_a_pause_to_think_inside_a_sentence_does_not_split_it() -> None:
    """Measured 2026-08-27: "Ilya what was the" / "cleaning task that I did" arrived
    as two clips at 0.75 s. A wearer thinking mid-sentence pauses 1-1.5 s."""
    frames = _frames((0.5, 0.001), (1.0, 0.2), (1.4, 0.001), (1.0, 0.2), (2.0, 0.001))
    assert len(list(_gate(frames))) == 1
    assert ear.end_frames_for(1.6) == ear.END_FRAMES
    assert ear.end_frames_for(0.0) == 1


def test_a_click_is_not_an_utterance() -> None:
    frames = _frames((0.5, 0.001), (0.12, 0.3), (2.0, 0.001))
    assert list(_gate(frames)) == []


def test_two_utterances_are_two_segments_and_a_long_one_is_capped() -> None:
    frames = _frames((0.5, 0.001), (1.0, 0.2), (2.2, 0.001), (1.0, 0.2), (2.2, 0.001))
    assert len(list(_gate(frames))) == 2
    long = _frames((0.5, 0.001), (14.0, 0.2), (2.0, 0.001))
    caps = list(_gate(long))
    assert len(caps) >= 2 and len(caps[0]) == 400 * ear.FRAME


def test_on_open_fires_once_when_speech_starts_and_a_raised_gate_ignores_millias_own_voice() -> None:
    frames = _frames((0.5, 0.001), (1.0, 0.2), (2.0, 0.001))
    opened: list[int] = []
    assert len(list(_gate(frames, on_open=lambda: opened.append(1)))) == 1
    assert opened == [1]
    # While Millia speaks the gate is 4x (0.06): her own voice back through the mic
    # at 0.04 RMS - speech at rest - is not speech now...
    echo = _frames((0.5, 0.001), (1.0, 0.04), (2.0, 0.001))
    assert len(list(_gate(echo))) == 1
    assert list(_gate(echo, threshold=lambda: 0.015 * ear.Ear.SPEAKING_BOOST)) == []
    # ...but the wearer cutting in close to the mic, at 0.2, still is.
    assert len(list(_gate(frames, threshold=lambda: 0.015 * ear.Ear.SPEAKING_BOOST))) == 1


def test_wav_bytes_is_16k_mono_16bit_and_above_the_backend_husk_floor() -> None:
    data = ear.wav_bytes(np.zeros(ear.SAMPLE_RATE // 2, dtype=np.float32))
    with wave.open(BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16_000)
        assert w.getnframes() == 8_000
    assert len(data) > 1024, "the backend rejects clips under 1 KB as husks"


def test_read_wav_round_trips_wav_bytes_and_refuses_other_rates(tmp_path: Any) -> None:
    samples = (np.sin(np.linspace(0, 200, ear.SAMPLE_RATE)) * 0.5).astype(np.float32)
    path = tmp_path / "a.wav"
    path.write_bytes(ear.wav_bytes(samples))
    back = ear.read_wav(str(path))
    assert back.shape == samples.shape and np.allclose(back, samples, atol=1e-3)
    other = tmp_path / "b.wav"
    other.write_bytes(ear.wav_bytes(samples, sample_rate=44_100))
    with pytest.raises(ValueError, match="16 kHz"):
        ear.read_wav(str(other))


@pytest.mark.asyncio
async def test_ear_hands_every_utterance_to_the_loop_as_wav_and_judges_nothing() -> None:
    """The laptop does not decide what was said. Two utterances in, two WAVs out."""
    got: list[bytes] = []
    loop = __import__("asyncio").get_running_loop()

    async def on_utterance(wav: bytes, wake_required: bool) -> None:
        assert wake_required, "no spotter and no window: the backend judges the wake word"
        got.append(wav)

    e = ear.Ear(on_utterance, loop=loop, log=lambda _m: None)
    e.start(microphone=False)
    rng = np.random.default_rng(2)
    speech = (rng.standard_normal(ear.SAMPLE_RATE) * 0.2).astype(np.float32)
    e.feed(speech)
    e.feed(speech)
    for _ in range(50):
        await __import__("asyncio").sleep(0.05)
        if len(got) == 2:
            break
    e.stop()
    assert len(got) == 2
    assert e.stopped, "stop() joins the listener thread"
    with wave.open(BytesIO(got[0])) as w:
        assert w.getframerate() == 16_000 and w.getnframes() > ear.SAMPLE_RATE


def test_voice_streams_chunks_to_the_player_and_a_new_line_cuts_the_old_one() -> None:
    import threading
    import time

    played: list[tuple[str, bytes]] = []
    current = {"text": ""}

    def stream(text: str) -> list[bytes]:
        current["text"] = text
        return [text.encode() + b"-%d" % i for i in range(20)]

    def play(chunks: Any, cancel: threading.Event) -> None:
        for chunk in chunks:
            if cancel.is_set():
                return
            played.append((current["text"], chunk))
            time.sleep(0.02)

    v = ear.Voice(stream=stream, play=play, log=lambda _m: None)
    v.speak("Step 2 of 7.")
    assert v.is_speaking()
    time.sleep(0.08)
    v.speak("Logged.")  # cuts the first line between chunks
    v.wait()
    first = [c for t, c in played if t == "Step 2 of 7."]
    second = [c for t, c in played if t == "Logged."]
    assert 0 < len(first) < 20, "the first line was cut part-way"
    assert len(second) == 20, "the second line played to the end"
    assert not v.is_speaking()
    v.speak("")
    assert not v.is_speaking(), "an empty line starts nothing"


def test_voice_plays_a_line_from_the_cache_the_second_time_and_never_caches_a_cut_line(tmp_path: Any) -> None:
    import threading
    import time

    calls: list[str] = []
    played: list[bytes] = []

    def stream(text: str) -> list[bytes]:
        calls.append(text)
        return [text.encode() + b"-%d" % i for i in range(10)]

    def play(chunks: Any, cancel: threading.Event) -> None:
        for chunk in chunks:
            if cancel.is_set():
                return
            played.append(chunk)
            time.sleep(0.01)

    v = ear.Voice(stream=stream, play=play, log=lambda _m: None, cache_dir=tmp_path / "voice")
    v.speak("Step 1 of 7.")
    v.wait()
    v.speak("Step 1 of 7.")
    v.wait()
    assert calls == ["Step 1 of 7."], "the provider is asked once; the second play is the file"
    first_play = b"".join(played[:10])
    assert b"".join(played[10:]) == first_play, "the same bytes, in order, from the file"
    del played[:]

    v.speak("Logged.")
    time.sleep(0.03)
    v.speak("Next.")  # cuts "Logged." part-way
    v.wait()
    assert sum(1 for c in played if c.startswith(b"Logged.")) < 10
    v.speak("Logged.")
    v.wait()
    assert calls.count("Logged.") == 2, "a cut line was not written, so it streams again"


def test_voice_swallows_a_provider_error_and_logs_it() -> None:
    logged: list[str] = []

    def stream(_text: str) -> list[bytes]:
        raise RuntimeError("quota")

    v = ear.Voice(stream=stream, play=lambda _c, _e: None, log=logged.append)
    v.speak("hello")
    v.wait()
    assert logged == ["[voice] quota"]


class _Proc:
    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.alive = True

    def poll(self) -> int | None:
        return None if self.alive else 0

    def terminate(self) -> None:
        self.alive = False

    def wait(self, timeout: float | None = None) -> int:
        self.reaped = True
        return 0


def test_speaker_is_non_blocking_and_a_new_line_cuts_the_old_one() -> None:
    started: list[_Proc] = []

    def popen(args: list[str], **_kw: Any) -> _Proc:
        p = _Proc(args)
        started.append(p)
        return p

    s = ear.Speaker(popen=popen)
    s.speak("Step 2 of 7: Strip and remake bed.")
    assert started[0].alive and started[0].args == ["say", "Step 2 of 7: Strip and remake bed."]
    s.speak("Logged.")
    assert not started[0].alive, "the earlier line was cut"
    assert getattr(started[0], "reaped", False), "a cut `say` is waited on, not left as a zombie"
    assert started[1].alive
    s.interrupt()
    assert not started[1].alive and getattr(started[1], "reaped", False)
    s.speak("")
    assert len(started) == 2, "an empty line starts nothing"


# ── the wake word on the laptop, and the follow-up window ────────────────────


def _speech(seconds: float, seed: int = 3, level: float = 0.08) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(seconds * ear.SAMPLE_RATE)) * level).astype(np.float32)


def _quiet(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * ear.SAMPLE_RATE), dtype=np.float32)


class _BurstSpotter:
    """Stands in for Whisper: the "wake word" is a loud 100 ms burst (|x| > 0.45)."""

    def __init__(self) -> None:
        self.looks = 0

    def spot(self, samples: np.ndarray) -> int | None:
        self.looks += 1
        hits = np.flatnonzero(np.abs(samples) > 0.45)
        return int(hits[0]) if len(hits) else None


def _burst() -> np.ndarray:
    return np.full(int(0.1 * ear.SAMPLE_RATE), 0.6, dtype=np.float32)


def _cut(samples: np.ndarray) -> list[np.ndarray]:
    return [samples[i : i + ear.FRAME] for i in range(0, len(samples) - ear.FRAME + 1, ear.FRAME)]


def test_room_talk_without_the_wake_word_is_never_sent_and_never_lights() -> None:
    """Ryan, 2026-08-28: "it detects and records everything I say". With a
    spotter, a segment that never carries the wake word is dropped unsent, and
    the meter never shows it as open."""
    spotter = _BurstSpotter()
    opened: list[bool] = []
    out = list(ear.listen(_cut(np.concatenate([_quiet(0.5), _speech(4.0), _quiet(2.5)])),
                          spotter=spotter, on_open=lambda: opened.append(True),
                          on_frame=lambda _l, _g, armed: armed and opened.append(armed)))
    assert out == [] and opened == []
    assert spotter.looks >= 7, "the tail was looked at every half second, and once more at the close"


def test_the_wake_word_mid_sentence_arms_the_segment_from_that_word() -> None:
    """Three seconds of talk, then "Millia, ..." for two seconds: one clip, sent
    with require_wake_word, starting just before the wake word — not at the
    start of the talk."""
    audio = np.concatenate([_quiet(0.5), _speech(3.0), _burst(), _speech(2.0, seed=5), _quiet(2.5)])
    opened: list[bool] = []
    out = list(ear.listen(_cut(audio), spotter=_BurstSpotter(), on_open=lambda: opened.append(True)))
    assert len(out) == 1 and opened == [True]
    samples, wake_required = out[0]
    assert wake_required
    burst_at = int(np.flatnonzero(np.abs(samples) > 0.45)[0])
    assert 0 < burst_at <= 4 * ear.FRAME, f"the clip starts at most three frames before the wake word, got {burst_at}"
    assert len(samples) >= 2 * ear.SAMPLE_RATE, "and runs to the end of the sentence"


def test_a_short_millia_done_is_caught_at_the_close_not_dropped() -> None:
    """"Millia, done" is under a second: shorter than one look. The close looks once more."""
    audio = np.concatenate([_quiet(0.5), _burst(), _speech(0.6), _quiet(2.5)])
    out = list(ear.listen(_cut(audio), spotter=_BurstSpotter()))
    assert len(out) == 1 and out[0][1] is True


def test_the_follow_up_window_arms_at_once_and_needs_no_wake_word() -> None:
    audio = np.concatenate([_quiet(0.5), _speech(1.0), _quiet(2.5)])
    out = list(ear.listen(_cut(audio), spotter=_BurstSpotter(), conversation_open=lambda: True))
    assert len(out) == 1 and out[0][1] is False, "armed by the window: the backend must not demand the name"


def test_ear_opens_the_window_when_millia_stops_speaking_and_says_so() -> None:
    now = [100.0]
    speaking = [True]
    shown: list[bool] = []
    e = ear.Ear(lambda _w, _r: None, loop=None, is_speaking=lambda: speaking[0], follow_up=4.0, clock=lambda: now[0], on_window=shown.append)  # type: ignore[arg-type]
    assert e.conversation_open() is False, "while she speaks only a wake word gets through"
    speaking[0] = False
    assert e.conversation_open() is True and shown == [True], "the window opens on the speaking→quiet edge, and is shown"
    now[0] += 3.9
    assert e.conversation_open() is True and shown == [True]
    now[0] += 0.2
    assert e.conversation_open() is False and shown == [True, False], "four seconds, then the name is needed again, and the ring goes"


@pytest.mark.asyncio
async def test_the_edge_is_seen_even_when_her_voice_opened_no_segment() -> None:
    """Measured 2026-08-28: "I'll take 1607" after "what are my tasks" needed
    the name. The raised gate kept her voice out of the ear, so no segment was
    open while she spoke, and the edge — watched only inside a segment — was
    missed. Now every frame watches it: quiet while she speaks, she stops, the
    wearer speaks inside four seconds, and the clip goes up without the name."""
    import asyncio

    got: list[bool] = []
    loop = asyncio.get_running_loop()

    async def on_utterance(_wav: bytes, wake_required: bool) -> None:
        got.append(wake_required)

    speaking = [True]
    e = ear.Ear(on_utterance, loop=loop, is_speaking=lambda: speaking[0], spotter=_BurstSpotter(), follow_up=4.0, log=lambda _m: None)
    e.start(microphone=False)
    e.feed(_quiet(1.0), then_quiet_seconds=0)  # she is speaking; the room is quiet to the ear
    await asyncio.sleep(0.2)
    speaking[0] = False  # her line ends
    e.feed(_quiet(0.3), then_quiet_seconds=0)  # a beat of silence, watched frame by frame
    e.feed(_speech(1.0))  # the wearer answers, no name
    for _ in range(60):
        await asyncio.sleep(0.05)
        if got:
            break
    e.stop()
    assert got == [False], "armed by the window: sent, and without require_wake_word"


def test_voice_speed_is_part_of_the_cache_key(tmp_path: Any) -> None:
    played: list[bytes] = []
    make = lambda speed: ear.Voice(  # noqa: E731
        "shimmer", speed=speed, stream=lambda _t: [b"a" * ear.Voice.CHUNK],
        play=lambda chunks, _c: played.extend(chunks), cache_dir=tmp_path,
    )
    v1, v2 = make(1.0), make(1.1)
    assert v1.speed == 1.0 and v2.speed == 1.1
    v1.speak("hello")
    v1.wait()
    v2.speak("hello")
    v2.wait()
    assert len(list(tmp_path.glob("*.pcm"))) == 2, "a line at another pace is another file"


def test_a_follow_up_that_starts_inside_millias_own_segment_is_armed_when_she_goes_quiet() -> None:
    """Measured 2026-08-28: Millia's voice through the speakers keeps a
    provisional segment open; the wearer answers as she stops; the window was
    checked only when the segment opened, so the answer was never armed. Now
    the window is read every frame and arms the running segment."""
    calls = {"n": 0}

    def conversation_open() -> bool:
        calls["n"] += 1
        return calls["n"] > 60  # she goes quiet about 1.8 s in

    audio = np.concatenate([_quiet(0.5), _speech(3.0), _quiet(2.5)])
    out = list(ear.listen(_cut(audio), spotter=_BurstSpotter(), conversation_open=conversation_open))
    assert len(out) == 1
    samples, wake_required = out[0]
    assert wake_required is False, "armed by the window"
    whole = (0.3 + 3.0 + ear.END_SILENCE_SECONDS) * ear.SAMPLE_RATE  # pre-roll, all her speech, the end silence
    assert len(samples) < whole - 1.5 * ear.SAMPLE_RATE, "the clip starts near the moment she went quiet, not at her first word"



def test_voice_prepare_renders_a_line_to_the_cache_and_says_how_long_it_runs(tmp_path: Any) -> None:
    calls: list[str] = []

    def stream(text: str) -> list[bytes]:
        calls.append(text)
        return [b"a" * ear.Voice.CHUNK] * 12  # 1.2 s of 24 kHz 16-bit mono

    played: list[bytes] = []
    v = ear.Voice(stream=stream, play=lambda chunks, _c: played.extend(chunks), cache_dir=tmp_path)
    assert v.prepare("Hi, I'm in room 1013.") == pytest.approx(1.2)
    assert calls == ["Hi, I'm in room 1013."] and played == [], "rendered, written, not played"
    v.speak("Hi, I'm in room 1013.")
    v.wait()
    assert calls == ["Hi, I'm in room 1013."], "the take plays the file: the provider is not asked again"
    assert len(played) == 12
    assert v.prepare("") == 0.0


def test_voice_instructions_are_part_of_the_cache_key(tmp_path: Any) -> None:
    make = lambda tone: ear.Voice(  # noqa: E731
        "onyx", instructions=tone, stream=lambda _t: [b"a" * ear.Voice.CHUNK],
        play=lambda _chunks, _c: None, cache_dir=tmp_path,
    )
    make("a tired guest").prepare("Four, please.")
    make("a cheerful guest").prepare("Four, please.")
    make(None).prepare("Four, please.")
    assert len(list(tmp_path.glob("*.pcm"))) == 3, "a line in another tone is another file"
