"""scripts/glasses_host.py — the reception scene, on the laptop-as-phone.

USER-VISIBLE ARTIFACTS: (1) what leaves for the glass while a guest speaks —
the guest view (0x0F) with the room, the name, the requests and the question
in its colour, and the tick with the count on the button; (2) what goes up —
the whole session each turn, `close` on the button; (3) nothing spoken; (4)
the ear held open while the session runs; (5) the shot list's `@button`,
`guest:` and `wearer:`. The last test runs the real route (the FastAPI app
over ASGI, the data layer faked) and the real Lua app in the emulator, and
reads the red pixels off the framebuffer.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from halo_emulator import EmulatorBrilliantMsg  # type: ignore[import-untyped]
from halo_emulator import HaloEmulator

import scripts.glasses_host as host
from tests.scripts.helpers import ASK
from tests.scripts.helpers import HELLO
from tests.scripts.helpers import _glass_shows
from tests.scripts.helpers import _RecordingFrame
from tests.scripts.helpers import _Voice

pytestmark = pytest.mark.unit

APP = Path(__file__).parents[2] / "glasses" / "main.lua"


def _guest_cue(**display: Any) -> dict[str, Any]:
    base = {"unit_code": "", "guest_name": "", "requests": [], "question": None, "level": None, "filed": None}
    base.update(display)
    return {"intent": "guest", "guest": None, "requests": [], "question": None, "filed": None, "display": base, "say": "", "language": "en", "heard": None}


def test_pack_guest_is_a_colour_byte_then_four_lines() -> None:
    view = host.GuestView("red", "1013", "Mark Robelo", "AC too noisy; extra towels", "How many towels?")
    assert host.pack_guest(view) == b"\x01" + b"1013\nMark Robelo\nAC too noisy; extra towels\nHow many towels?"
    with pytest.raises(KeyError):
        host.pack_guest(host.GuestView("pink", "", "", "", ""))


def test_the_guest_view_listens_then_lists_then_asks_in_the_levels_colour() -> None:
    fresh = host.view_for_guest_cue(_guest_cue())
    assert fresh == host.GuestView("white", "", "", "Listening..", "")
    named = host.view_for_guest_cue(_guest_cue(unit_code="1013", guest_name="Mark Robelo"))
    assert (named.unit, named.name, named.requests) == ("1013", "Mark Robelo", "Listening..")
    red = host.view_for_guest_cue(_guest_cue(unit_code="1013", guest_name="Mark Robelo", requests=["AC too noisy", "extra towels"], question="How many towels?", level="needed"))
    assert red == host.GuestView("red", "1013", "Mark Robelo", "AC too noisy; extra towels", "How many towels?")
    orange = host.view_for_guest_cue(_guest_cue(unit_code="1013", requests=["4 towels"], question="When to deliver?", level="optional"))
    assert orange.colour == "orange"


def test_the_requests_line_keeps_the_newest_whole_and_counts_the_rest() -> None:
    assert host.requests_line(["AC too noisy", "4 extra towels"]) == "AC too noisy; 4 extra towels"
    assert host.requests_line(["Make up room", "2 bottles of water, now", "TV remote does not work"]) == (
        "+2; TV remote does not work"
    ), "three rows of 13: the newest whole, the older two counted"
    assert host.requests_line(["Make up room", "2 pillows", "TV remote broken"]) == "+1; 2 pillows; TV remote broken"
    assert host.requests_line(["A request summary that is itself longer than the three rows hold"]).startswith("A request"), "one long request is shown, and the glass wraps it"
    three = host.view_for_guest_cue(_guest_cue(unit_code="0712", requests=["Make up room", "2 bottles of water, now", "TV remote does not work"]))
    assert three.requests == "+2; TV remote does not work"


def test_the_closing_turn_is_the_tick_with_the_count() -> None:
    two = host.view_for_guest_cue(_guest_cue(unit_code="1013", filed=2))
    assert two == host.View("ambient", "tick", "1013", "2 tasks created", "", None)
    one = host.view_for_guest_cue(_guest_cue(unit_code="1013", filed=1))
    assert one.main == "1 task created"
    none = host.view_for_guest_cue(_guest_cue(unit_code="", filed=0))
    assert (none.icon, none.main) == ("question", "Nothing to file")


def test_script_lines_drop_the_crib_prefix_and_keep_the_words() -> None:
    assert host.script_line("guest: Hi, I'm in room 1013") == "Hi, I'm in room 1013"
    assert host.script_line("Wearer:  How many towels?") == "How many towels?"
    assert host.script_line("Millia, done") == "Millia, done"
    assert host.script_line("The guest: is here") == "The guest: is here", "only a leading prefix is the crib's"


def test_guest_line_is_one_console_line_of_what_the_glass_shows() -> None:
    assert host.guest_line(_guest_cue()) == "(no guest yet)"
    assert host.guest_line(_guest_cue(unit_code="1013", guest_name="Mark Robelo", requests=["AC too noisy"], question="Which?", level="needed")) == (
        "1013 Mark Robelo · AC too noisy · [needed] Which?"
    )
    assert host.guest_line(_guest_cue(unit_code="1013", filed=2)) == "1013 · 2 filed"
    assert host.guest_line({**_guest_cue(unit_code="1013"), "timing": {"total": 1234}}) == "1013 · 1234 ms"
    assert host.guest_line({"intent": "refused", "say": "Clock in first"}) == "refused: Clock in first"


class _Backend:
    """`/api/v1/glasses/guest` as the host sees it: every form recorded, one
    cue per turn keyed by the last line, and the close."""

    def __init__(self) -> None:
        self.forms: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/glasses/guest"
        form = dict(httpx.QueryParams(request.content.decode()))
        self.forms.append(form)
        return self.respond(form)

    def respond(self, form: dict[str, Any]) -> httpx.Response:
        if form.get("close") == "true":
            return httpx.Response(200, json=_guest_cue(unit_code="1013", filed=2))
        line = form.get("transcript", "")
        if line == HELLO:
            return httpx.Response(200, json={**_guest_cue(unit_code="1013", guest_name="Mark Robelo"), "heard": line})
        return httpx.Response(200, json={**_guest_cue(unit_code="1013", guest_name="Mark Robelo", requests=["AC too noisy", "extra towels"], question="How many towels?", level="needed"), "heard": line})


DISMISS = "Millia, dismiss that, I'll do it in the app"


class _DismissingBackend(_Backend):
    def respond(self, form: dict[str, Any]) -> httpx.Response:
        if form.get("transcript") == DISMISS:
            cue = {**_guest_cue(unit_code="1013", guest_name="Mark Robelo", requests=["extra towels"], dismissed=True), "intent": "dismissed", "heard": DISMISS}
            return httpx.Response(200, json=cue)
        return super().respond(form)


@pytest.mark.asyncio
async def test_millia_dismiss_ends_the_session_on_the_host_without_a_close_and_the_next_press_opens_the_next_guest() -> None:
    """A `dismissed` cue is the end of the session: no close goes up (so nothing
    can be filed, not by the button and not by the clock), the ring goes off,
    the glass says "Dismissed", and the next press is the next guest's open."""
    backend = _DismissingBackend()
    frame = _RecordingFrame()
    voice = _Voice()
    sessions: list[bool] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend.handler), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=voice, on_session=sessions.append, guest_silence=0.2)
        driver._loop = asyncio.get_running_loop()
        await driver.toggle_guest_session()
        await driver.guest_say(HELLO)
        cue = await driver.guest_say(DISMISS)
        assert cue["intent"] == "dismissed"
        assert not driver.in_guest_session and sessions == [True, False]
        assert driver._guest_timer is None, "no clock runs on a dismissed session"
        assert frame.sent[-1] == (host.MSG_AMBIENT, host.pack_view("none", "1013", "Dismissed", ""))
        await asyncio.sleep(0.3)
        assert [f.get("close") for f in backend.forms] == ["false", "false"], "no close ever went up"
        assert await driver.toggle_guest_session() is None, "the next press opens the next guest's session"
        assert driver.in_guest_session and driver.guest_lines == []
    assert voice.spoken == []
    assert host.guest_line(cue) == "1013 Mark Robelo · extra towels · dismissed, nothing filed"


@pytest.mark.asyncio
async def test_the_button_opens_the_session_every_line_carries_the_session_and_the_button_closes_it() -> None:
    backend = _Backend()
    frame = _RecordingFrame()
    voice = _Voice()
    sessions: list[bool] = []
    events: list[tuple[str, Any]] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend.handler), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=voice, on_session=sessions.append, observer=lambda e, p: events.append((e, p)), guest_silence=0)
        driver._loop = asyncio.get_running_loop()
        assert not driver.in_guest_session
        assert await driver.toggle_guest_session() is None, "opening answers nothing: nothing went up"
        assert driver.in_guest_session and sessions == [True]
        assert frame.sent[-1] == (host.MSG_GUEST, host.pack_guest(host.GuestView("white", "", "", "Listening..", "")))
        assert backend.forms == [], "the glass listens; nothing is posted until the guest speaks"

        await driver.guest_say(HELLO)
        assert backend.forms[-1] == {"client_request_id": backend.forms[-1]["client_request_id"], "close": "false", "transcript": HELLO}
        assert frame.sent[-1][0] == host.MSG_GUEST and b"Mark Robelo" in frame.sent[-1][1]

        await driver.guest_say(ASK)
        assert backend.forms[-1]["prior_transcript"] == HELLO, "the session so far rides with every line"
        assert frame.sent[-1][1].startswith(b"\x01"), "red: a count is needed"

        close_id = driver.guest_close_id
        closed = await driver.toggle_guest_session()
        assert closed is not None and closed["display"]["filed"] == 2
        assert backend.forms[-1]["close"] == "true"
        assert backend.forms[-1]["client_request_id"] == close_id, "minted when the session opened: a retried close reuses it"
        assert backend.forms[-1]["prior_transcript"] == f"{HELLO}\n{ASK}"
        assert "transcript" not in backend.forms[-1], "the button carries no words"
        assert not driver.in_guest_session and sessions == [True, False]
        assert frame.sent[-1] == (host.MSG_AMBIENT, host.pack_view("tick", "1013", "2 tasks created", ""))
    assert voice.spoken == [], "Millia observes: nothing is spoken in a guest session"
    assert ("guest", True) in events and ("guest", False) in events


@pytest.mark.asyncio
async def test_a_single_press_from_the_lua_thread_toggles_on_the_drivers_loop() -> None:
    backend = _Backend()
    frame = _RecordingFrame()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend.handler), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=_Voice(), guest_silence=0)
        driver._loop = asyncio.get_running_loop()
        await asyncio.to_thread(driver._on_button, bytes([host.MSG_BUTTON, 1]))
        for _ in range(50):
            if driver.in_guest_session:
                break
            await asyncio.sleep(0.02)
        assert driver.in_guest_session
        await asyncio.to_thread(driver._on_button, bytes([host.MSG_BUTTON, 2]))
        await asyncio.sleep(0.05)
        assert driver.in_guest_session, "a double press is not the door"
        await asyncio.to_thread(driver._on_button, bytes([host.MSG_BUTTON, 1]))
        for _ in range(50):
            if not driver.in_guest_session:
                break
            await asyncio.sleep(0.02)
        assert not driver.in_guest_session


@pytest.mark.asyncio
async def test_silence_closes_the_session_and_a_word_resets_the_clock() -> None:
    backend = _Backend()
    frame = _RecordingFrame()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend.handler), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=_Voice(), guest_silence=0.3)
        driver._loop = asyncio.get_running_loop()
        await driver.open_guest_session()
        assert driver._guest_timer is None, "no clock at the open: the guest may take a moment"
        await asyncio.sleep(0.4)
        assert driver.in_guest_session, "0.4 s after the open with no word: still open"
        await driver.guest_say(HELLO)  # the clock starts with the first answer
        assert driver._guest_timer is not None
        await asyncio.sleep(0.2)
        assert driver.in_guest_session, "0.2 s since the answer: still open"
        await asyncio.sleep(0.25)
        assert not driver.in_guest_session, "0.45 s of silence: closed on its own"
        assert backend.forms[-1]["close"] == "true"
        await driver.stop()


class _SlowBackend(_Backend):
    """The same backend behind an ASGI app whose request is held until the test
    lets it go — so a close is really in flight when something else happens,
    and the test says so with events, not with sleeps."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()  # a request is in
        self.release = asyncio.Event()  # the test lets it answer

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        form = dict(httpx.QueryParams(body.decode()))
        self.forms.append(form)  # recorded on entry: a test reads it while the request is held
        self.entered.set()
        await self.release.wait()
        response = self.respond(form)
        await send({"type": "http.response.start", "status": response.status_code, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": response.content})

    def let_one_through(self) -> None:
        self.release.set()
        self.release = asyncio.Event()
        self.entered = asyncio.Event()


async def _held(backend: _SlowBackend, coro: Any) -> Any:
    """Start `coro`, wait until its request is held in the backend."""
    task = asyncio.ensure_future(coro)
    await backend.entered.wait()
    return task


@pytest.mark.asyncio
async def test_a_run_that_ends_while_the_silence_close_is_in_flight_waits_for_it() -> None:
    """A piped take ended right after the clock closed the session; the POST
    was cut off and nothing was filed (2026-08-29, the 2008 shower ticket)."""
    backend = _SlowBackend()
    frame = _RecordingFrame()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=_Voice(), guest_silence=0.02)
        driver._loop = asyncio.get_running_loop()
        await driver.open_guest_session()
        turn = await _held(backend, driver.guest_say(HELLO))
        backend.let_one_through()
        await turn
        await backend.entered.wait()  # the clock fired after the answer was drawn; the close is held in the backend
        assert driver._toggles and backend.forms[-1]["close"] == "true"
        stopping = asyncio.ensure_future(driver.stop())
        await asyncio.sleep(0)
        assert not stopping.done(), "stop() waits for the close"
        backend.let_one_through()
        await stopping
        assert not driver.in_guest_session and not driver._toggles
        assert frame.sent[-1] == (host.MSG_AMBIENT, host.pack_view("tick", "1013", "2 tasks created", ""))


@pytest.mark.asyncio
async def test_a_button_press_while_a_line_is_posting_waits_for_it_and_the_line_is_in_the_close() -> None:
    """The normal end of the scene: the wearer presses the button while the
    guest's last line is still going up. The close must carry that line, and
    the run must end after the close, not through it."""
    backend = _SlowBackend()
    frame = _RecordingFrame()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=_Voice(), guest_silence=0)
        driver._loop = asyncio.get_running_loop()
        await driver.open_guest_session()
        turn = await _held(backend, driver.guest_say(HELLO))
        await asyncio.to_thread(driver._on_button, bytes([host.MSG_BUTTON, 1]))
        await asyncio.sleep(0.01)
        assert driver.in_guest_session and len(driver._toggles) == 1, "the press waits for the turn"
        backend.let_one_through()
        await turn
        await backend.entered.wait()  # now the close is held
        assert backend.forms[-1]["close"] == "true"
        assert backend.forms[-1]["prior_transcript"] == HELLO, "the line that was posting is in the close"
        backend.let_one_through()
        await driver.stop()  # awaits the button's close
        assert not driver.in_guest_session


@pytest.mark.asyncio
async def test_two_fast_presses_are_one_close_and_the_next_guests_open() -> None:
    """The second press lands while the first close is posting. It is not a
    second close of the same session (nothing to close) and it is not lost:
    it opens the next guest's session once the first has closed."""
    backend = _SlowBackend()
    frame = _RecordingFrame()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=_Voice(), guest_silence=0)
        driver._loop = asyncio.get_running_loop()
        await driver.open_guest_session()
        turn = await _held(backend, driver.guest_say(HELLO))
        backend.let_one_through()
        await turn
        await asyncio.to_thread(driver._on_button, bytes([host.MSG_BUTTON, 1]))
        await backend.entered.wait()  # the first close is held
        await asyncio.to_thread(driver._on_button, bytes([host.MSG_BUTTON, 1]))
        await asyncio.sleep(0.01)
        assert len(driver._toggles) == 2, "both presses are kept until done"
        backend.let_one_through()
        await asyncio.gather(*driver._toggles)
        closes = [f for f in backend.forms if f.get("close") == "true"]
        assert len(closes) == 1, "one close"
        assert driver.in_guest_session and driver.guest_lines == [], "the second press opened the next session"
        assert frame.sent[-1] == (host.MSG_GUEST, host.pack_guest(host.GuestView("white", "", "", "Listening..", "")))
        closing = await _held(backend, driver.close_guest_session())
        backend.let_one_through()
        await closing
        await driver.stop()


@pytest.mark.asyncio
async def test_a_backend_that_does_not_answer_the_close_leaves_the_session_and_the_teardown_intact() -> None:
    """A 5xx or a dead link on the closing beat: the words stay, the clock is
    re-armed, the glass and the ear say why — and stop() still tears the link down."""
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        if form.get("close") == "true":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(502, text="bad gateway")
            if calls["n"] == 2:
                raise httpx.ConnectError("no route to host")
        return httpx.Response(200, json={**_guest_cue(unit_code="1013", filed=1), "heard": form.get("transcript")})

    frame = _RecordingFrame()
    voice = _Voice()
    async with httpx.AsyncClient(transport=httpx.MockTransport(flaky), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=voice, guest_silence=5)
        driver._loop = asyncio.get_running_loop()
        await driver.open_guest_session()
        await driver.guest_say(HELLO)
        for _ in range(2):
            cue = await driver.toggle_guest_session()
            assert cue is not None and host.refused(cue)
            assert driver.in_guest_session and driver.guest_lines == [HELLO]
            assert driver._guest_timer is not None, "the clock runs again"
        assert voice.spoken == ["The backend did not answer. Try again."] * 2
        closed = await driver.toggle_guest_session()
        assert closed is not None and closed["display"]["filed"] == 1
        await driver.stop()
        assert frame.stopped and frame.disconnected


@pytest.mark.asyncio
async def test_a_line_that_arrives_as_the_clock_closes_the_session_is_dropped_not_an_assertion() -> None:
    """Measured 2026-08-29: the script's next line saw the session open, waited
    on the lock while the clock's close posted, then asserted on None."""
    backend = _SlowBackend()
    frame = _RecordingFrame()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=_Voice(), guest_silence=0.02)
        driver._loop = asyncio.get_running_loop()
        await driver.open_guest_session()
        turn = await _held(backend, driver.guest_say(HELLO))
        backend.let_one_through()
        await turn
        await backend.entered.wait()  # the clock's close holds the lock and the backend
        assert driver.in_guest_session, "not yet swapped out: the close is still posting"
        late = asyncio.ensure_future(driver.guest_say("and one more thing"))
        await asyncio.sleep(0.01)
        backend.let_one_through()
        cue = await late
        assert cue["intent"] == "ignored" and cue["heard"] == "and one more thing"
        assert host.guest_line(cue) == "(dropped: the session had closed)"
        assert not driver.in_guest_session
        assert backend.forms[-1]["close"] == "true" and "and one more thing" not in backend.forms[-1].get("prior_transcript", "")
        again = await driver.close_guest_session()
        assert again["intent"] == "ignored", "a second close after the first is nothing"
        await driver.stop()


@pytest.mark.asyncio
async def test_a_refused_close_keeps_the_session_and_its_words() -> None:
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        if form.get("close") == "true" and calls["n"] == 0:
            calls["n"] += 1
            return httpx.Response(409, json={"error": {"code": "clock_in_required", "message": "Clock in first"}})
        return httpx.Response(200, json={**_guest_cue(unit_code="1013", filed=1), "heard": form.get("transcript")})

    frame = _RecordingFrame()
    voice = _Voice()
    async with httpx.AsyncClient(transport=httpx.MockTransport(flaky), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=voice, guest_silence=0)
        driver._loop = asyncio.get_running_loop()
        await driver.open_guest_session()
        await driver.guest_say(HELLO)
        refused = await driver.toggle_guest_session()
        assert refused is not None and host.refused(refused)
        assert driver.in_guest_session and driver.guest_lines == [HELLO], "nothing lost: the button can be pressed again"
        assert voice.spoken == ["Clock in first"]
        closed = await driver.toggle_guest_session()
        assert closed is not None and closed["display"]["filed"] == 1 and not driver.in_guest_session


@pytest.mark.asyncio
async def test_a_refused_door_in_a_session_is_shown_and_the_session_survives() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": {"code": "clock_in_required", "message": "Clock in first"}})

    frame = _RecordingFrame()
    voice = _Voice()
    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=voice, guest_silence=0)
        driver._loop = asyncio.get_running_loop()
        await driver.open_guest_session()
        cue = await driver.guest_say(HELLO)
        assert host.refused(cue) and driver.in_guest_session
        assert frame.sent[-1] == (host.MSG_AMBIENT, host.pack_view("question", "", "Clock in first", ""))
        assert driver.guest_lines == [], "a refused line is not part of the session"
    assert voice.spoken == ["Clock in first"], "a refusal is the one thing spoken: the wearer must know"


async def _ready(value: dict[str, Any]) -> dict[str, Any]:
    return value


# --- the read-aloud take: two voices, one timeline (Ryan, 2026-08-29) ---


def test_take_lines_name_the_reader_and_keep_the_button() -> None:
    text = "# a comment\n@button\nguest: Hi, I'm in room 1013.\n\nwearer: How many towels?\nBy six.\n@button\n"
    assert host.take_lines(text) == [
        ("button", ""),
        ("guest", "Hi, I'm in room 1013."),
        ("wearer", "How many towels?"),
        ("wearer", "By six."),
        ("button", ""),
    ]
    assert host.script_reader("Guest: hello") == "guest" and host.script_reader("hello") == "wearer"


class _TakeVoice:
    """A Voice for a take: `prepare` renders, `speak` starts a line that runs
    `seconds`, `wait` blocks to its end; every call is logged with the clock."""

    def __init__(self, who: str, log: list[tuple[float, str]], seconds: float) -> None:
        self.who, self.log, self.seconds = who, log, seconds
        self._until = 0.0

    def prepare(self, text: str) -> float:
        self.log.append((time.monotonic(), f"prepare {self.who}: {text}"))
        return self.seconds

    def speak(self, text: str) -> None:
        self.log.append((time.monotonic(), f"speak {self.who}: {text}"))
        self._until = time.monotonic() + self.seconds

    def wait(self) -> None:
        time.sleep(max(0.0, self._until - time.monotonic()))
        self.log.append((time.monotonic(), f"end {self.who}"))


class _LateBackend(_Backend):
    """The LLM takes longer than the guest's line: the take must wait for it."""

    def __init__(self, delay: float) -> None:
        super().__init__()
        self.delay = delay
        self.answered: list[tuple[float, str]] = []

    async def async_handler(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(self.delay)
        resp = self.handler(request)
        self.answered.append((time.monotonic(), dict(httpx.QueryParams(request.content.decode())).get("transcript", "close")))
        return resp


@pytest.mark.asyncio
async def test_a_take_renders_every_line_first_then_speaks_in_turn_and_never_asks_before_the_glass_answered() -> None:
    backend = _LateBackend(delay=0.15)
    frame = _RecordingFrame()
    log: list[tuple[float, str]] = []
    voices = {"guest": _TakeVoice("guest", log, 0.05), "wearer": _TakeVoice("wearer", log, 0.05)}
    lines = [("button", ""), ("guest", HELLO), ("guest", ASK), ("wearer", "How many towels would you like?"), ("button", "")]
    events: list[tuple[float, str, Any]] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend.async_handler), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=_Voice(), guest_silence=0, observer=lambda e, p: events.append((time.monotonic(), e, p)))
        driver._loop = asyncio.get_running_loop()
        await host.play_take(driver, lines, voices, threading.Event(), gap=0.02, log=lambda _m: None)
        assert not driver.in_guest_session
    # After the guest's line ends the ring thinks, and the glass answers SCRIPT_THINK
    # later — not the instant the backend returns, which here is before he stops.
    hello_ended = next(t for t, m in log if m == "end guest")
    thought = next(t for t, e, p in events if e == "state" and p == "thinking")
    answered = next(t for t, e, p in events if e == "cue" and (p.get("display") or {}).get("guest_name") == "Mark Robelo")
    assert hello_ended <= thought <= answered
    spoken_lines = [p for _t, e, p in events if e == "line"]
    assert spoken_lines == [None, HELLO, ASK, "How many towels would you like?", None], "each line is captioned as it is spoken; the button clears it"
    assert answered - hello_ended >= host.SCRIPT_THINK * 0.8, "the glass held the answer for the thinking beat"
    names = [m for _t, m in log]
    prepared = [m for m in names if m.startswith("prepare")]
    assert prepared == [f"prepare guest: {HELLO}", f"prepare guest: {ASK}", "prepare wearer: How many towels would you like?"]
    assert names.index("speak guest: " + HELLO) > len(prepared) - 1, "every line is rendered before the first is spoken"
    spoken = [m for m in names if m.startswith("speak")]
    assert spoken == [f"speak guest: {HELLO}", f"speak guest: {ASK}", "speak wearer: How many towels would you like?"], "each line by its reader, in order"
    # The wearer's question starts only after the backend answered the guest's ask —
    # the red line is on the glass before she reads it — even though the answer
    # took longer than his line.
    asked_at = next(t for t, m in log if m == "speak wearer: How many towels would you like?")
    answered_ask = next(t for t, line in backend.answered if line == ASK)
    assert asked_at > answered_ask
    assert backend.forms[-1]["close"] == "true" and backend.forms[-1]["prior_transcript"].startswith(HELLO)
    assert frame.sent[-1] == (host.MSG_AMBIENT, host.pack_view("tick", "1013", "2 tasks created", ""))


@pytest.mark.asyncio
async def test_a_stopped_take_ends_between_lines() -> None:
    backend = _Backend()
    frame = _RecordingFrame()
    log: list[tuple[float, str]] = []
    voices = {"guest": _TakeVoice("guest", log, 0.0), "wearer": _TakeVoice("wearer", log, 0.0)}
    stop = threading.Event()
    stop.set()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend.handler), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=_Voice(), guest_silence=0)
        driver._loop = asyncio.get_running_loop()
        await host.play_take(driver, [("button", ""), ("guest", HELLO)], voices, stop, gap=0.0, log=lambda _m: None)
    assert backend.forms == [] and not any(m.startswith("speak") for _t, m in log)


@pytest.mark.asyncio
async def test_a_quiet_power_on_leaves_the_glass_dark_until_the_button() -> None:
    """A take opens on the button, not on "Good morning, Ry" (Ryan, 2026-08-29)."""
    frame = _RecordingFrame()
    events: list[tuple[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/glasses/context"
        return httpx.Response(200, json={"me": {"name": "Ry"}, "mode": "reception", "display": {"ambient": "Next · room 1013"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=_Voice(), observer=lambda e, p: events.append((e, p)))
        ctx = await driver.start(quiet=True)
    assert ctx["me"] == {"name": "Ry"}
    assert [e for e, _p in events] == ["context"], "no greeting cue: the window's subtitle stays empty"
    assert all(code not in (host.MSG_AMBIENT, host.MSG_DETAIL) for code, _payload in frame.sent), "nothing drawn on the glass"


# --- the film take: the film speaks, the glass keeps its clock (Ryan, 2026-08-29) ---


def test_film_events_read_cuts_buttons_and_timed_lines_and_a_spoken_list_has_none() -> None:
    text = "# c\n@cut 3.5\n@button ~5\n~7-8.2 guest: Hi, I'm in room 1013.\n8.2-10.1 wearer: Of course.\n@cut 22.5\n"
    ev = host.film_events(text)
    assert [(e.at, e.kind) for e in ev] == [(3.5, "cut"), (5.0, "button"), (7.0, "line"), (8.2, "line"), (22.5, "cut")]
    assert ev[2].who == "guest" and ev[2].words == "Hi, I'm in room 1013." and ev[2].until == 8.2
    assert host.film_events(open("glasses/shot-list-reception.txt").read()) == [], "the spoken list has no times"
    film = host.film_events(open("glasses/shot-list-film.txt").read())
    cuts = [e.at for e in film if e.kind == "cut"]
    assert len(cuts) == 2 and cuts[0] < cuts[1] and sum(e.kind == "button" for e in film) == 2, "two cuts, two buttons"


@pytest.mark.asyncio
async def test_a_film_take_follows_the_clock_captions_every_line_and_sends_only_the_sessions_lines() -> None:
    """Real seconds: `guest_say` holds the glass in real time, so a sped-up clock
    would stretch it. The script is compact instead — about four seconds."""
    backend = _Backend()
    frame = _RecordingFrame()
    events: list[tuple[float, str, Any]] = []
    t0 = time.monotonic()
    clock = lambda: time.monotonic() - t0  # noqa: E731
    lead = host.FILM_LEAD
    script = (
        f"@cut 0.1\n@button {lead - 0.8:.1f}\n{lead + 0.3:.1f}-{lead + 0.6:.1f} guest: Hi, I'm in room 1013.\n"
        f"{lead + 0.7:.1f}-{lead + 0.9:.1f} wearer: Of course.\n{lead + 1.2:.1f}-{lead + 1.5:.1f} guest: The AC is too noisy.\n"
        f"@button {lead + 2.2:.1f}\n{2 * lead + 2.4:.1f}-{2 * lead + 2.6:.1f} guest: Perfect, thank you.\n@cut {2 * lead + 3:.1f}\n"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend.handler), base_url="http://t") as http:
        driver = host.GlassesHost(frame, http=http, task_id=None, speak=_Voice(), guest_silence=0, observer=lambda e, p: events.append((clock(), e, p)))
        driver._loop = asyncio.get_running_loop()
        await host.play_film(driver, host.film_events(script), clock, threading.Event(), log=lambda _m: None)
        assert not driver.in_guest_session
    captions = [(t, p) for t, e, p in events if e == "line"]
    assert [p for _t, p in captions] == [None, "Hi, I'm in room 1013.", "Of course.", "The AC is too noisy.", None, "Perfect, thank you."]
    wanted = [lead - 0.8, lead + 0.3, lead + 0.7, lead + 1.2, lead + 2.2, 2 * lead + 2.4]
    assert all(abs(t - at) <= 0.25 for (t, _p), at in zip(captions, wanted, strict=True)), f"each at its second: {captions}"
    sent = [f.get("transcript") for f in backend.forms if f.get("close") != "true"]
    assert sent == ["Hi, I'm in room 1013.", "Of course.", "The AC is too noisy."], "the goodbye after the close is a caption only"
    assert backend.forms[-1]["close"] == "true"
    assert frame.sent[-1] == (host.MSG_AMBIENT, host.pack_view("tick", "1013", "2 tasks created", ""))
    # The line goes up FILM_LEAD before it is heard; the glass names him FILM_THINK
    # after he stops — before the receptionist says his name.
    hello_posted = next(t for t, e, p in events if e == "state" and p == "listening")
    named = next(t for t, e, p in events if e == "cue" and (p.get("display") or {}).get("guest_name") == "Mark Robelo")
    assert abs(hello_posted - 0.3) <= 0.25, f"posted a second early: {hello_posted}"
    assert abs(named - (lead + 0.6 + host.FILM_THINK)) <= 0.3, f"named at the beat: {named}"

