"""The phone's job, played by the laptop: drive the glasses app from the backend.

    uv run python scripts/glasses_host.py --login maria.chrisdemo@millia.test

That is the glasses, on the laptop: the window is the glass, the microphone
listens for "Millia, ...", the backend decides, Millia speaks. Only another
"Millia" interrupts her. Options:

    ... --task <cleaning task id>                # instead of the wearer's next clean
    ... --script glasses/shot-list.txt           # one utterance per line, no microphone
    ... --type                                   # type utterances instead
    ... GLASSES_JWT=<token> without --login      # a token you already hold
    ... --hardware                               # a real Halo over BLE instead of the emulator

The reception scene (plans/glasses-reception-2026-08-29.md): the button — Space in the
window, ``@button`` in a script — opens a guest session. While it is open every
utterance is the guest's and goes to ``POST /api/v1/glasses/guest`` with the session so
far; nothing is spoken; the glass shows the room, the name, the requests and the open
question in red or orange. The button again closes it: the requests are filed and the
glass says how many. ``--guest-silence`` seconds without a word closes it too.

While it runs, the wearer's MOPS notification inbox (``GET /api/v1/notifications``)
is polled: a row that arrives — a manager's "Go now", a task assigned to them —
is drawn on the glass with the alert icon and spoken once, and the view they
were on returns. ``--notice-poll 0`` turns that off.

Flow per utterance: the WAV (or the line) → ``POST /api/v1/glasses/say`` → a
Cue → the view for it goes to the glass over the vendor's message layer →
macOS ``say`` speaks ``cue.say``. The backend is the brain (ADR 0036); this
file owns layout only in the sense of choosing WHICH lines and icon to send —
the Lua app places them. The ear is scripts/glasses_ear.py.

Porting: ``make_frame(hardware=True)`` swaps ``EmulatorBrilliantMsg`` for the
vendor's ``BrilliantMsg`` over Bluetooth. Same calls, same bytes, same Lua.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from brilliant_msg import TxSprite  # type: ignore[import-untyped]
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
APP_PATH = REPO / "glasses" / "main.lua"
DEFAULT_API = "https://millia-dev.fly.dev"

# Message codes — mirrored in glasses/main.lua.
MSG_AMBIENT = 0x0A
MSG_DETAIL = 0x0B
MSG_SPRITE = 0x20
MSG_BUTTON = 0x0C
MSG_STATE = 0x0D
MSG_BADGE = 0x0E
MSG_GUEST = 0x0F
STATES = {"idle": 0, "listening": 1, "thinking": 2}
# The colour of the question at the foot of the guest view (main.lua QUESTION_COLOURS).
COLOURS = {"white": 0, "red": 1, "orange": 2, "green": 3}
LEVEL_COLOURS = {"needed": "red", "optional": "orange"}
GUEST_SILENCE = 20.0  # seconds without a word that close a guest session on their own

# A read-aloud take (`--read-aloud`): the scene spoken by two voices, no microphone.
# The tones go to the provider as `instructions`. The gap is the silence between two
# people; after a guest's line the ring thinks for SCRIPT_THINK before the glass answers.
GUEST_TONE = (
    "A hotel guest at the front desk, face to face with the receptionist: relaxed, polite, "
    "a little tired from travel. Conversational, with natural pauses; not an announcer."
)
WEARER_TONE = "A hotel receptionist answering a guest at the desk: warm, attentive, unhurried, quiet."
READ_ALOUD_SPEED = 1.1  # a touch above the provider's: 1.0 dragged (Ryan, 2026-08-29)
READ_ALOUD_GAP = 0.5
# A film take: the glass names the guest 0.4 s after he stops — before the
# receptionist says "Mr. Rubio" (Ryan, 2026-08-29). The film is known in
# advance, so a line goes up FILM_LEAD seconds before it is heard: the answer
# is ready when he stops, and the beat is the beat, not the backend's time.
FILM_THINK = 0.4
FILM_LEAD = 1.0

ICONS = {"none": 0, "tick": 1, "alert": 2, "camera": 3, "question": 4}
THUMB_SIDE = 104  # the detail band on the glass, docs/research/glasses-display-rnd
# The guest view's three request rows hold 13 glyphs each (main.lua GUEST_ROWS).
GUEST_REQUEST_GLYPHS = 39

# Notifications: what MOPS shows in the bell, on the glass. The wearer's inbox
# (`GET /api/v1/notifications`, the same rows the phone lists) is polled; a row
# that appears while the glasses are on is drawn and spoken once, and the view
# the badge stays on the glass for NOTICE_DWELL seconds.
NOTICE_POLL = 5.0
# A scripted take: after Enter the glass listens, then thinks, before the
# answer — the pace of a spoken exchange, not of a text round trip.
SCRIPT_HEAR = 0.6
SCRIPT_THINK = 0.9
NOTICE_DWELL = 6.0


@dataclass(frozen=True)
class View:
    kind: str  # "ambient" | "detail"
    icon: str
    top: str
    main: str
    hint: str
    image_url: str | None


def pack_view(icon: str, top: str, main: str, hint: str) -> bytes:
    """One byte of icon, then three UTF-8 lines. `KeyError` on an unknown icon."""
    return bytes([ICONS[icon]]) + "\n".join((top, main, hint)).encode("utf-8")


@dataclass(frozen=True)
class GuestView:
    """The guest view (0x0F): the room, the name, the requests, the question in its colour."""

    colour: str
    unit: str
    name: str
    requests: str
    question: str


def pack_guest(view: GuestView) -> bytes:
    """One byte of colour, then four UTF-8 lines. `KeyError` on an unknown colour."""
    return bytes([COLOURS[view.colour]]) + "\n".join((view.unit, view.name, view.requests, view.question)).encode("utf-8")


def view_for_guest_cue(cue: dict[str, Any]) -> GuestView | View:
    """What the glass shows for one turn of a guest session. While the session
    runs: the guest view — "Listening.." until the guest asks for something,
    then the requests, and the open question in red (needed) or orange
    (optional). On the closing turn: the ambient view with the tick and the
    count, the way a finished room is shown."""
    display = cue.get("display") or {}
    unit = str(display.get("unit_code") or "")
    if cue.get("intent") == "dismissed":
        # "Millia, dismiss": the session ended and nothing was filed.
        return View("ambient", "none", unit, "Dismissed", "", None)
    filed = display.get("filed")
    if filed is not None:
        n = int(filed)
        line = "Nothing to file" if n == 0 else f"{n} task{'s' if n != 1 else ''} created"
        return View("ambient", "tick" if n else "question", unit, line, "", None)
    requests = [str(r) for r in display.get("requests") or []]
    question = str(display.get("question") or "")
    colour = LEVEL_COLOURS.get(str(display.get("level") or ""), "white")
    return GuestView(
        colour=colour,
        unit=unit,
        name=str(display.get("guest_name") or ""),
        requests=requests_line(requests) if requests else "Listening..",
        question=question,
    )


def requests_line(requests: list[str]) -> str:
    """The requests on the glass, newest first to fit: the last thing the guest
    said is what the wearer is answering, so it is never the one cut to "..".
    Older ones are kept while the rows hold them; a "+2" says how many are off."""
    kept: list[str] = []
    for summary in reversed(requests):
        candidate = "; ".join([summary, *kept])
        if kept and len(candidate) > GUEST_REQUEST_GLYPHS:
            break
        kept.insert(0, summary)
    hidden = len(requests) - len(kept)
    line = "; ".join(kept)
    return f"+{hidden}; {line}" if hidden else line


def local_hour() -> int:
    return datetime.now().hour


def greeting(name: str, hour: int) -> str:
    """"Good morning, Maria." — what Millia says at power-on, and nothing more."""
    part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    return f"Good {part}, {name}." if name else f"Good {part}."


def split_ambient(ambient: str) -> tuple[str, str]:
    """"3/7 · Wipe the mirror" → ("3/7", "Wipe the mirror"); a line without the
    separator is all text."""
    head, sep, tail = ambient.partition(" · ")
    if sep and "/" in head:
        return head, tail
    return "", ambient


_NEXT_ROOM = re.compile(r"^Next · room (\S+)$")


def next_room(ambient: str) -> str | None:
    """"Next · room 1213" → "1213": the room goes to the top line, large, and
    the middle band says only "Next" — the glass never prints a room twice."""
    m = _NEXT_ROOM.match(ambient)
    return m.group(1) if m else None


def view_for_cue(cue: dict[str, Any], *, unit_code: str | None) -> View:
    display = cue.get("display") or {}
    ambient = display.get("ambient") or ""
    progress, text = split_ambient(ambient)
    nxt = next_room(ambient)
    if nxt:
        unit_code, text = nxt, "Next"
    top = "  ".join(p for p in (unit_code, progress) if p)
    detail = display.get("detail") or {}
    image_url = detail.get("image_url")
    inspector = cue.get("mode") == "inspector"
    intent = cue.get("intent")
    needs = cue.get("needs")

    # No verb hints ("say done"): Millia is an assistant, not a menu. The hint
    # row carries only what Millia is waiting for, and only while she waits.
    if intent == "refused":
        return View("ambient", "question", top, text, "", None)
    if needs == "unit_code":
        return View("ambient", "question", top, "Which room?", "", None)
    if needs == "confirm_counts":
        return View("ambient", "question", top, text, "yes?", None)
    if needs == "counts":
        return View("ambient", "question", top, text, "how many?", None)
    if cue.get("capture"):
        return View("ambient", "camera", top, text, "", None)
    if intent == "report":
        # Not "Task filed": it reads as "Task failed" in the pixel font.
        return View("ambient", "alert", top, "Reported", "", None)
    if image_url and (intent == "show" or inspector):
        # The middle band is the thumbnail's; the Lua app draws no text there.
        return View("detail", "none", top, "", "", image_url)
    if intent in ("done", "complete", "start_work"):
        return View("ambient", "tick", top, text, "", None)
    return View("ambient", "none", top, text, "", None)


def sprite_payload(image_bytes: bytes) -> bytes:
    """Any image → a 16-colour TxSprite no wider or taller than the detail band."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    sprite = TxSprite.from_image_bytes(buf.getvalue(), max_pixels=THUMB_SIDE * THUMB_SIDE)
    return bytes(sprite.pack())


# The marks phone copy uses that the pixel font has no glyph for, and the
# ASCII that means the same thing. Everything else non-ASCII becomes a space.
_MARKS = {ord(a): b for a, b in {"\u2014": "-", "\u2013": "-", "\u00b7": "-", "\u2022": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2026": "..."}.items()}
_NON_ASCII = re.compile(r"[^\x20-\x7e]+")


def plain(text: str) -> str:
    """The pixel font on the glass has ASCII and nothing else, and the upload
    path encodes latin-1. Notification copy is written for a phone screen and
    carries emoji and typographic marks ("\U0001f534 GO NOW \u2014 1607",
    "Cleaning \u00b7 proceed immediately"): the marks become their ASCII
    equivalent, anything else undrawable becomes one space. The words survive;
    nothing the optic cannot draw reaches it."""
    return " ".join(_NON_ASCII.sub(" ", text.translate(_MARKS)).split())


MOPS_BUNDLE_ID = "com.meetmillia.app"


def simulator_banner(title: str, body: str, *, popen: Callable[..., Any] = subprocess.Popen) -> None:
    """The same notification as an iOS banner on the booted simulator.

    The simulator has no APNs, so a real push never reaches it: the bell shows
    the row (it reads the table) and the lock screen shows nothing (measured
    2026-08-28). `xcrun simctl push` injects one from a payload — the row's own
    title and body, so the banner says what the glass and the bell say, in the
    same second. Non-blocking; a missing xcrun is not the demo's problem."""
    payload = json.dumps({"aps": {"alert": {"title": title, "body": body}, "sound": "default"}})
    try:
        proc = popen(["xcrun", "simctl", "push", "booted", MOPS_BUNDLE_ID, "-"], stdin=subprocess.PIPE,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if proc.stdin is not None:
            proc.stdin.write(payload.encode())
            proc.stdin.close()
    except OSError as exc:
        print(f"[phone] banner not sent: {exc}")


def speak_macos(text: str) -> None:
    if platform.system() == "Darwin":
        subprocess.run(["say", text], check=False)
    else:
        print(f"[say] {text}")


def fetch_image_httpx(url: str) -> bytes:
    return httpx.get(url, timeout=20, follow_redirects=True).raise_for_status().content


def make_frame(hardware: bool) -> Any:
    """The one line that changes between the emulator and a real Halo."""
    if hardware:
        from brilliant_msg import BrilliantMsg

        return BrilliantMsg()
    from halo_emulator import EmulatorBrilliantMsg  # type: ignore[import-untyped]
    from halo_emulator import HaloEmulator

    return EmulatorBrilliantMsg(HaloEmulator(print_handler=print))


class GlassesHost:
    def __init__(
        self,
        frame: Any,
        *,
        http: httpx.AsyncClient,
        task_id: str | None,
        app_path: Path = APP_PATH,
        speak: Callable[[str], None] = speak_macos,
        fetch_image: Callable[[str], bytes] = fetch_image_httpx,
        observer: Callable[[str, Any], None] | None = None,
        phone_banner: Callable[[str, str], None] | None = None,
        on_session: Callable[[bool], None] | None = None,
        guest_silence: float = GUEST_SILENCE,
    ) -> None:
        self.frame = frame
        self.http = http
        self.task_id = task_id
        # The reception scene. `guest_lines` is the session so far — None when
        # no session is open. `on_session` tells the ear to hold open (True) or
        # go back to the wake word (False).
        self.guest_lines: list[str] | None = None
        self.guest_close_id: str | None = None  # minted when the session opens: a retried close reuses it
        self.on_session = on_session or (lambda _open: None)
        self.guest_silence = guest_silence
        self._guest_timer: asyncio.TimerHandle | None = None
        # One turn at a time: a button press while a line is still posting
        # waits for it, so the line is in the close and nothing is dropped.
        self._guest_lock = asyncio.Lock()
        # Every toggle the button or the silence clock started and has not
        # finished: stop() ends after all of them, not through any.
        self._toggles: set[asyncio.Task[None]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.phone_banner = phone_banner  # the same notice as a banner on the simulator
        self.app_path = app_path
        self.speak = speak
        self.fetch_image = fetch_image
        # The Mac window listens here: ("context", ctx), ("state", name), ("cue", cue).
        self.observed = observer is not None
        self.observer = observer or (lambda _event, _payload: None)
        self.unit_code: str | None = None
        # The backend keeps no conversation state: when a cue says `needs`, the
        # next utterance carries the previous one as `prior_transcript`.
        self.prior_transcript: str | None = None
        # The last view the wearer was left on, and how many have been drawn:
        # a notice restores the first only if the second has not moved on.

    # ---- lifecycle

    async def start(self, *, quiet: bool = False) -> dict[str, Any]:
        """Power-on. With `quiet` the glass stays dark: a take opens on the
        button, not on a greeting (Ryan, 2026-08-29)."""
        self._loop = asyncio.get_running_loop()
        await self.frame.connect()
        await self.frame.upload_stdlua_libs(lib_names=["data", "sprite"])
        await self.frame.upload_frame_app(str(self.app_path))
        self.frame.register_data_response_handler(self, [MSG_BUTTON], self._on_button)
        await self.frame.start_frame_app()
        ctx = await self.context()
        if refused(ctx):
            await self.show(ctx)
            return ctx
        # Start is power-on. The glass draws where the wearer is; the greeting
        # is on the console and nothing is spoken — Millia's voice waits for a
        # question (a spoken good morning on every open was dropped 2026-08-29).
        if quiet:
            return ctx
        me = ctx.get("me")
        name = str(me.get("name") or "") if isinstance(me, dict) else str(me or "")
        cue = {
            "intent": "where_am_i",
            "mode": ctx.get("mode"),
            "display": ctx.get("display"),
            "say": greeting(name, local_hour()),
            "capture": False,
            "needs": None,
        }
        await self.push(view_for_cue(cue, unit_code=self.unit_code))
        self.observer("cue", cue)
        return ctx

    async def stop(self) -> None:
        self._cancel_guest_timer()
        if self._toggles:
            # A close the clock or the button started is still filing: the run
            # ends after it, not through it (a piped take ended before the POST
            # and the 2008 ticket was never filed, 2026-08-29). A failure in one
            # must not skip the link's teardown below.
            await asyncio.gather(*self._toggles, return_exceptions=True)
        self.frame.unregister_data_response_handler(self)
        await self.frame.stop_frame_app()
        await self.frame.disconnect()  # on --hardware this is the BLE link

    # ---- the backend

    async def clock_in(self) -> dict[str, Any]:
        """The day gate every action sits behind (409 clock_in_required otherwise).
        Idempotent: a second clock-in re-opens the shift and does not re-broadcast."""
        resp = await self.http.post("/api/v1/shifts/clock-in", data={})
        return cue_or_refusal(resp)

    async def context(self) -> dict[str, Any]:
        params = {"task_id": self.task_id} if self.task_id else {}
        resp = await self.http.get("/api/v1/glasses/context", params=params)
        ctx = cue_or_refusal(resp)
        if refused(ctx):
            return ctx
        current = ctx.get("current") or {}
        self.task_id = current.get("task_id") or self.task_id
        self.unit_code = current.get("unit_code") or (ctx.get("next") or {}).get("unit_code")
        self.observer("context", ctx)
        return ctx

    async def say(
        self,
        text: str = "",
        *,
        photo_url: str | None = None,
        audio: bytes | None = None,
        require_wake_word: bool = False,
        hold: float = 0.0,
    ) -> dict[str, Any]:
        """One utterance → one cue. With `audio` the WAV goes as `file` (the
        phone's path: the backend transcribes and answers in the spoken
        language). With `require_wake_word` the backend drops audio that did
        not begin with "Millia": the cue comes back `ignored` and nothing is
        shown or spoken. Without `audio`, `text` goes as `transcript`."""
        form: dict[str, str] = {"client_request_id": str(uuid.uuid4())}
        if audio is None:
            form["transcript"] = text
        if require_wake_word:
            form["require_wake_word"] = "true"
        if self.task_id:
            form["task_id"] = self.task_id
        if photo_url:
            form["photo_url"] = photo_url
        if self.prior_transcript:
            form["prior_transcript"] = self.prior_transcript
        files = {"file": ("utterance.wav", audio, "audio/wav")} if audio is not None else None
        started = time.monotonic()
        resp = await self.http.post("/api/v1/glasses/say", data=form, files=files)
        self.observer("timing", {"backend_ms": (time.monotonic() - started) * 1000})
        cue = cue_or_refusal(resp)
        if audio is not None and refused(cue) and "no speech" in str(cue.get("say", "")).lower():
            # A noise burst opened the ear and the clip held no words (422 from
            # Whisper). Room noise, not a refusal to speak aloud (heard 2026-08-27).
            cue = {**cue, "intent": "ignored", "say": "", "heard": None}
        if cue.get("intent") == "ignored":
            self.observer("cue", cue)
            return cue  # not addressed to Millia: nothing shown, nothing said, no interruption
        heard = cue.get("heard") or text
        self.prior_transcript = heard if cue.get("needs") else None
        if cue.get("intent") == "complete" and cue.get("mode") == "none":
            # The room is finished: stop pinning it, so the backend resolves the
            # wearer's next clean for what comes next (measured 2026-08-27).
            self.task_id = None
        elif cue.get("task_id") and cue["task_id"] != self.task_id:
            self.task_id = cue["task_id"]
            await self.context()  # the wearer moved rooms: refresh the unit code
        if hold:
            # A scripted line is sent as text and answered fast; hold the answer
            # so the glass thinks for at least `hold` seconds, as it would on a
            # spoken line (Ryan, 2026-08-28).
            await asyncio.sleep(max(0.0, hold - (time.monotonic() - started)))
        await self.show(cue)
        return cue

    # ---- the reception scene

    @property
    def in_guest_session(self) -> bool:
        return self.guest_lines is not None

    async def toggle_guest_session(self) -> dict[str, Any] | None:
        """The button: open a session when none is open, close it otherwise.
        Decided under the lock — a press while a close is still posting is the
        NEXT guest's open, not a second close of the last one."""
        async with self._guest_lock:
            if self.guest_lines is not None:
                return await self._close_locked()
            await self._open_locked()
            return None

    async def open_guest_session(self) -> None:
        """A guest is at the desk: the ear holds open, the glass says it listens,
        nothing goes up until the guest speaks, and no clock runs until then."""
        async with self._guest_lock:
            await self._open_locked()

    async def _open_locked(self) -> None:
        self.guest_lines = []
        self.guest_close_id = str(uuid.uuid4())
        self.on_session(True)
        self.observer("guest", True)
        await self.push_guest(GuestView("white", "", "", "Listening..", ""))
        # No clock yet: the button opened this on purpose, and a guest may take
        # a moment. The clock guards the END of the conversation — it starts
        # once the first answer is on the glass.

    async def guest_say(self, text: str = "", *, audio: bytes | None = None, hold: float = 0.0) -> dict[str, Any]:
        """One line of the session up, with every earlier line, and the glass
        redrawn from the answer. The backend keeps nothing: `prior_transcript`
        is the session so far. Nothing is spoken."""
        async with self._guest_lock:
            lines = self.guest_lines
            if lines is None:
                # The session closed while this line waited on the lock (the
                # clock, or the button): the words came after the close. Dropped,
                # said so; never an assertion (measured 2026-08-29).
                print(f"[guest] the session closed before this line: dropped {text!r}" if audio is None else "[guest] the session closed before this clip: dropped")
                return closed_cue(text if audio is None else None)
            self._cancel_guest_timer()  # the clock does not run while the guest's words are up
            form: dict[str, str] = {"client_request_id": str(uuid.uuid4()), "close": "false"}
            if audio is None:
                form["transcript"] = text
            if lines:
                form["prior_transcript"] = "\n".join(lines)
            files = {"file": ("utterance.wav", audio, "audio/wav")} if audio is not None else None
            started = time.monotonic()
            cue = await self._post_guest(form, files)
            self.observer("timing", {"backend_ms": (time.monotonic() - started) * 1000})
            if refused(cue):
                self._arm_guest_timer()
                if audio is not None and "no speech" in str(cue.get("say", "")).lower():
                    return {**cue, "intent": "ignored", "say": "", "heard": None}
                await self.show(cue)  # a refused door is shown, as everywhere else
                return cue
            heard = str(cue.get("heard") or text).strip()
            if heard:
                lines.append(heard)
            if cue.get("intent") == "dismissed":
                # "Millia, dismiss": the session is over and nothing is filed.
                # No close goes up — not from the button, not from the clock —
                # so the door is never reached; the next press is the next guest.
                self.guest_lines = None
                self.guest_close_id = None
                self.on_session(False)
                self.observer("guest", False)
                await self.push_guest(view_for_guest_cue(cue))
                self.observer("cue", cue)
                return cue
            if hold:
                await asyncio.sleep(max(0.0, hold - (time.monotonic() - started)))
            await self.push_guest(view_for_guest_cue(cue))
            self.observer("cue", cue)
            self._arm_guest_timer()  # the silence starts when the answer is on the glass
            return cue

    async def _post_guest(self, form: dict[str, str], files: Any = None) -> dict[str, Any]:
        """The round trip. A 4xx is a refusal cue; so is a 5xx or a dead link —
        a session must never be stranded with its clock stopped, and a failed
        close must never take the run's teardown down with it."""
        try:
            resp = await self.http.post("/api/v1/glasses/guest", data=form, files=files)
            return cue_or_refusal(resp)
        except (httpx.HTTPError, RuntimeError) as exc:
            print(f"[guest] the backend did not answer: {exc}")
            return {**refusal_cue(httpx.Response(503, text=str(exc))), "say": "The backend did not answer. Try again."}

    async def close_guest_session(self) -> dict[str, Any]:
        """The button again, or silence: the session goes up once more with
        `close`, the complete requests are filed, the glass shows the count."""
        async with self._guest_lock:
            if self.guest_lines is None:
                return closed_cue(None)  # a second press while the first close was posting
            return await self._close_locked()

    async def _close_locked(self) -> dict[str, Any]:
        lines = self.guest_lines
        assert lines is not None and self.guest_close_id is not None
        self._cancel_guest_timer()
        form: dict[str, str] = {"client_request_id": self.guest_close_id, "close": "true"}
        if lines:
            form["prior_transcript"] = "\n".join(lines)
        cue = await self._post_guest(form)
        if refused(cue):
            # The session survives a refused close: the words are still here,
            # the clock is re-armed, the button can be pressed again.
            await self.show(cue)
            self._arm_guest_timer()
            return cue
        self.guest_lines = None
        self.guest_close_id = None
        self.on_session(False)
        self.observer("guest", False)
        await self.push_guest(view_for_guest_cue(cue))
        self.observer("cue", cue)
        return cue

    async def push_guest(self, view: GuestView | View) -> None:
        if isinstance(view, GuestView):
            await self.frame.send_message(MSG_GUEST, pack_guest(view))
        else:
            await self.push(view)

    def _arm_guest_timer(self) -> None:
        self._cancel_guest_timer()
        if self._loop is not None and self.guest_silence > 0:
            self._guest_timer = self._loop.call_later(self.guest_silence, self._guest_silence_elapsed)

    def _cancel_guest_timer(self) -> None:
        if self._guest_timer is not None:
            self._guest_timer.cancel()
            self._guest_timer = None

    def _guest_silence_elapsed(self) -> None:
        self._guest_timer = None
        if self.in_guest_session and self._loop is not None:
            print(f"[guest] {self.guest_silence:.0f} s of silence: the session closes")
            self._spawn_toggle()

    def _spawn_toggle(self) -> None:
        """The button's or the clock's toggle, as a task on the loop, kept until
        it is done so stop() ends after it. Two presses are two tasks: the lock
        orders them, and neither is forgotten."""
        assert self._loop is not None
        task = self._loop.create_task(self._toggle_and_print())
        self._toggles.add(task)
        task.add_done_callback(self._toggles.discard)

    async def _toggle_and_print(self) -> None:
        cue = await self.toggle_guest_session()
        if cue is not None:
            print(f"  glass: {guest_line(cue)}")

    def _button_pressed(self) -> None:
        self._spawn_toggle()

    # ---- the glass

    async def show(self, cue: dict[str, Any]) -> None:
        """A cue on the glass and in the wearer's ear."""
        await self.push(view_for_cue(cue, unit_code=self.unit_code))
        self.observer("cue", cue)
        if cue.get("say"):
            self.speak(cue["say"])
        if cue.get("task_id") and self.observed:
            await self.checklist()

    async def checklist(self) -> dict[str, Any] | None:
        """The room's checklist as the backend holds it now — the third instrument.
        Read only when a window observes: it is one round-trip on the wearer's path."""
        if not self.task_id:
            return None
        resp = await self.http.get(f"/api/v1/cleaning/tasks/{self.task_id}/checklist")
        if resp.status_code >= 400:
            return None
        task: dict[str, Any] = resp.json()
        self.observer("checklist", task)
        return task

    # ---- the phone's notifications, on the glass

    async def notifications(self) -> list[dict[str, Any]]:
        """The wearer's unread inbox, oldest first — `GET /api/v1/notifications`,
        the same rows and the same tenant scope MOPS' bell reads (the staff JWT
        decides whose they are). A 4xx is not fatal: the run keeps going."""
        resp = await self.http.get("/api/v1/notifications", params={"unread_only": "true", "limit": 20})
        if resp.status_code >= 400:
            return []
        rows = resp.json().get("notifications") or []
        return list(reversed(rows))  # the route answers newest first

    async def badge(self, row: dict[str, Any], *, dwell: float = NOTICE_DWELL) -> None:
        """One inbox row: a small amber mark on the glass for `dwell` seconds,
        over whatever is drawn, and the same row as a banner on the phone.
        Nothing spoken, nothing pushed off (Ryan, 2026-08-28: the read-out
        notice broke the flow; the phone has the words)."""
        if self.phone_banner is not None:
            self.phone_banner(plain(str(row.get("title") or "")), plain(str(row.get("body") or "")))
        await self.frame.send_message(MSG_BADGE, b"\x01")
        self.observer("notice", row)
        await asyncio.sleep(dwell)
        await self.frame.send_message(MSG_BADGE, b"\x00")

    async def watch_notifications(self, stop: Any, *, interval: float = NOTICE_POLL, dwell: float = NOTICE_DWELL) -> None:
        """Poll the inbox for as long as the glasses are on. The first poll only
        learns what is already there, so a run does not open on yesterday's rows;
        every row that arrives after it is shown once."""
        seen = {str(r.get("id")) for r in await self.notifications()}
        while not stop.is_set():
            await asyncio.sleep(interval)
            for row in await self.notifications():
                rid = str(row.get("id"))
                if rid in seen:
                    continue
                seen.add(rid)
                print(f"[notice] {plain(str(row.get('title') or ''))}: {plain(str(row.get('body') or ''))}")
                await self.badge(row, dwell=dwell)

    async def push(self, view: View) -> None:
        code = MSG_DETAIL if view.kind == "detail" else MSG_AMBIENT
        await self.frame.send_message(code, pack_view(view.icon, view.top, view.main, view.hint))
        if view.kind == "detail" and view.image_url:
            await self.frame.send_message(MSG_SPRITE, sprite_payload(self.fetch_image(view.image_url)))

    async def set_state(self, name: str) -> None:
        """The dot under the hint: listening while the wearer speaks, thinking
        while the backend works. A drawn view clears it on the glass."""
        self.observer("state", name)
        await self.frame.send_message(MSG_STATE, bytes([STATES[name]]))

    def _on_button(self, data: bytes) -> None:
        """The Halo's button, from the Lua thread: a single press opens or
        closes a guest session. The work runs on the driver's loop."""
        kind = data[1] if len(data) > 1 else 0
        print(f"[glasses] button {kind}")
        if kind == 1 and self._loop is not None:
            self._loop.call_soon_threadsafe(self._button_pressed)


def refused(cue: dict[str, Any]) -> bool:
    return cue.get("intent") == "refused"


def closed_cue(heard: str | None) -> dict[str, Any]:
    """What a line gets when the session closed before it: nothing shown,
    nothing said — the `ignored` shape every caller already handles."""
    return {"intent": "ignored", "say": "", "heard": heard, "display": {}}


_CRIB_PREFIX = re.compile(r"^(?:guest|wearer)\s*:\s*", re.IGNORECASE)


def script_line(line: str) -> str:
    """A shot-list line as the ear would hear it: the crib sheet's "guest:" /
    "wearer:" prefix says who reads it, and is not part of the words."""
    return _CRIB_PREFIX.sub("", line.strip(), count=1)


_CRIB_WHO = re.compile(r"^(guest|wearer)\s*:", re.IGNORECASE)


def script_reader(line: str) -> str:
    """Who reads a shot-list line: "guest" or "wearer" from the crib prefix; a
    line with no prefix is the wearer's — she is the one Millia listens to."""
    m = _CRIB_WHO.match(line.strip())
    return m.group(1).lower() if m else "wearer"


def take_lines(text: str) -> list[tuple[str, str]]:
    """The shot list as (reader, words): comments and blanks dropped, the
    button as ("button", "")."""
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(("button", "") if line == "@button" else (script_reader(line), script_line(line)))
    return out


_TIMED = re.compile(r"^~?(\d+(?:\.\d+)?)\s*-\s*~?(\d+(?:\.\d+)?)\s+(.*)$")
_AT = re.compile(r"^@(cut|button)\s+~?(\d+(?:\.\d+)?)$")


@dataclass(frozen=True)
class FilmEvent:
    at: float
    kind: str  # "cut" | "button" | "line"
    who: str = ""
    words: str = ""
    until: float = 0.0  # a line's end


def film_events(text: str) -> list[FilmEvent]:
    """A timed shot list (glasses/shot-list-film.txt): `@cut T`, `@button T`,
    `start-end who: words`. Empty when the file has no times — then it is the
    spoken kind, for `play_take`."""
    out: list[FilmEvent] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if m := _AT.match(line):
            out.append(FilmEvent(float(m.group(2)), m.group(1)))
        elif m := _TIMED.match(line):
            rest = m.group(3)
            out.append(FilmEvent(float(m.group(1)), "line", script_reader(rest), script_line(rest), float(m.group(2))))
    return sorted(out, key=lambda e: e.at)


async def play_film(
    driver: GlassesHost,
    events: list[FilmEvent],
    clock: Callable[[], float | None],
    stop: threading.Event,
    *,
    log: Callable[[str], None] = print,
) -> None:
    """The scene over a film that carries the voices: nothing is spoken here.
    `clock` is the film's seconds since Start (None before it). Each line goes up
    to Millia at its start and the glass answers after its end plus the thinking
    beat; the button opens and files at its times; the cuts are the window's."""
    posts: list[asyncio.Task[Any]] = []
    # The timeline: a line is two moments — it goes up FILM_LEAD early, it is
    # captioned as it is heard; the button is one.
    moments: list[tuple[float, str, FilmEvent]] = []
    for ev in events:
        if ev.kind == "button":
            moments.append((ev.at, "button", ev))
        elif ev.kind == "line":
            moments.append((ev.at - FILM_LEAD, "post", ev))
            moments.append((ev.at, "caption", ev))
    filed = False  # the closing button fired: nothing said after it goes up, even while the close is in flight
    for at, what, ev in sorted(moments, key=lambda m: m[0]):
        while not stop.is_set():
            now = clock()
            if now is not None and now >= at:
                break
            await asyncio.sleep(0.02)
        if stop.is_set():
            break
        if what == "button":
            driver.observer("line", None)
            log(f"\n▶ {ev.at:5.1f}s @button")
            if driver.in_guest_session:
                filed = True
                posts.append(asyncio.ensure_future(driver.toggle_guest_session()))  # the close: files, takes seconds
            else:
                await driver.toggle_guest_session()  # the open: nothing goes up, and the next post needs it open
        elif what == "caption":
            log(f"\n▶ {ev.at:5.1f}s {ev.who}: {ev.words}")
            driver.observer("line", ev.words)
        elif driver.in_guest_session and not filed:  # a post before the button, or after the filing, is not one
            await driver.set_state("listening")
            # A guest's line: the glass answers FILM_THINK after he stops. The
            # wearer's goes up at once — a hold would keep the session's lock
            # for her whole line, and the button behind it would file late.
            hold = (ev.until - at) + FILM_THINK if ev.who == "guest" else 0.0
            posts.append(asyncio.ensure_future(driver.guest_say(ev.words, hold=hold)))
    for cue in await asyncio.gather(*posts, return_exceptions=True):
        if isinstance(cue, dict):
            log(f"  glass: {guest_line(cue)}")


async def play_take(
    driver: GlassesHost,
    lines: list[tuple[str, str]],
    voices: dict[str, Any],
    stop: threading.Event,
    *,
    gap: float = READ_ALOUD_GAP,
    log: Callable[[str], None] = print,
) -> None:
    """The scene as one take: two voices, no microphone, no Enter.

    Every line is rendered before the first is spoken, so the provider never sits
    in a gap between two people. Each line is spoken by its reader and goes up to
    the backend the moment the voice starts, so the glass answers while the words
    are still in the air. The next line starts `gap` seconds after the last one
    ended — and never before the glass has answered: the receptionist reads the
    red line before she asks it. `voices` maps "guest" and "wearer" to a Voice
    (`prepare`, `speak`, `wait`)."""
    seconds: dict[tuple[str, str], float] = {}
    for who, words in lines:
        if who in voices:
            seconds[(who, words)] = voices[who].prepare(words)
            log(f"[take] {who}: {seconds[(who, words)]:.1f}s  {words}")
    loop = asyncio.get_running_loop()
    for who, words in lines:
        if stop.is_set():
            return
        if who == "button":
            driver.observer("line", None)
            cue = await driver.toggle_guest_session()
            log(f"\n▶ @button\n  glass: {guest_line(cue) if cue is not None else 'Listening..'}")
            await asyncio.sleep(gap)
            continue
        log(f"\n▶ {who}: {words}")
        voice = voices[who]
        in_session = driver.in_guest_session
        # A guest's line: the glass answers SCRIPT_THINK after he stops, never
        # mid-sentence — Millia is seen to listen, then to think. The hold is
        # from the post, which starts with the voice, so it is the line plus the beat.
        hold = seconds[(who, words)] + SCRIPT_THINK if who == "guest" else 0.0
        await driver.set_state("listening")
        driver.observer("line", words)  # the window captions the line while it is spoken
        voice.speak(words)
        answer = asyncio.ensure_future(
            driver.guest_say(words, hold=hold) if in_session else driver.say(words, hold=hold)
        )
        await loop.run_in_executor(None, voice.wait)  # the line, to its end, off the event loop
        if who == "guest":
            await driver.set_state("thinking")
        cue = await answer
        log(f"  glass: {guest_line(cue)}" if in_session else f"  Millia: {cue.get('say') or '(silent)'}")
        await asyncio.sleep(gap)


def guest_line(cue: dict[str, Any]) -> str:
    """One console line for a guest-session cue: what the glass shows."""
    if refused(cue):
        return f"refused: {cue.get('say')}"
    if cue.get("intent") == "ignored":
        return "(dropped: the session had closed)"
    d = cue.get("display") or {}
    who = " ".join(p for p in (str(d.get("unit_code") or ""), str(d.get("guest_name") or "")) if p) or "(no guest yet)"
    parts = [who]
    if d.get("requests"):
        parts.append("; ".join(str(r) for r in d["requests"]))
    if d.get("question"):
        parts.append(f"[{d.get('level')}] {d['question']}")
    if cue.get("intent") == "dismissed":
        parts.append("dismissed, nothing filed")
    elif d.get("filed") is not None:
        parts.append(f"{d['filed']} filed")
    timing = cue.get("timing") or {}
    if timing.get("total") is not None:
        parts.append(f"{timing['total']} ms")
    return " · ".join(parts)


def cue_or_refusal(resp: httpx.Response) -> dict[str, Any]:
    """The body of a 2xx; a 4xx as a `refused` cue. A door that refuses
    ("Clock in first", 409; the flag off, 409; not the assignee, 403) is
    spoken and shown, and the run does not abort. 5xx still raises."""
    if 400 <= resp.status_code < 500:
        return refusal_cue(resp)
    _raise_for(resp)
    body: dict[str, Any] = resp.json()
    return body


def refusal_cue(resp: httpx.Response) -> dict[str, Any]:
    """A 4xx from any door as a Cue: the door's own message, spoken and shown."""
    try:
        body = resp.json()
    except ValueError:
        body = {}
    # Two shapes measured on millia-dev: {"error": {"code", "message"}} (409
    # clock_in_required) and {"error": "<sentence>"} (403 not the assignee).
    err = body.get("error")
    if isinstance(err, dict):
        message = err.get("message")
    else:
        message = err
    message = message or body.get("detail") or resp.text or f"HTTP {resp.status_code}"
    return {
        "intent": "refused",
        "task_id": None,
        "mode": None,
        "step": None,
        "say": str(message),
        "language": "en",
        "display": {"ambient": str(message), "detail": {"text": str(message), "image_url": None, "items": []}},
        "capture": False,
        "needs": None,
        "heard": None,
    }


def mint_session(email: str, *, admin: Any) -> str:
    """A real session for a dev staff user, minted with the service role.

    No JWT secret is on disk, so a token cannot be forged locally; instead the
    admin API issues a magic link and `verify_otp` redeems it — the token then
    carries the same claims the app's own sign-in would (client_id, staff_id,
    role, can_inspect), because it passes through the same access-token hook.
    """
    link = admin.auth.admin.generate_link({"type": "magiclink", "email": email})
    session = admin.auth.verify_otp({"token_hash": link.properties.hashed_token, "type": "magiclink"})
    token = str(session.session.access_token)
    # verify_otp makes the minted session the CLIENT's own: the next admin call
    # would run as the wearer and fail "User not allowed" (measured 2026-08-29:
    # the first mint worked, every one after it failed). Drop it locally — the
    # token stays valid; only this client forgets it.
    admin.auth.sign_out({"scope": "local"})
    return token


def admin_client_from_env() -> Any:
    """The service-role Supabase client `.env` points at (millia-dev here)."""
    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv(REPO / ".env")
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise RuntimeError(f"{resp.request.method} {resp.request.url.path} → {resp.status_code}: {resp.text}")


# ---- CLI


async def run(
    args: argparse.Namespace,
    frame: Any,
    stop: threading.Event,
    observer: Callable[[str, Any], None] | None = None,
    wait_for: threading.Event | None = None,
    take_go: threading.Event | None = None,
    film_clock: Callable[[], float | None] | None = None,
) -> None:
    from scripts.glasses_ear import WhisperSpotter

    spotter = None if args.say_file else WhisperSpotter()
    if spotter is not None:
        # The model loads while the wearer reads the window and clicks Start
        # (10 s from cold, measured 2026-08-28). Local only: no request goes out.
        threading.Thread(target=spotter.warm, daemon=True, name="glasses-spotter-warm").start()
    if wait_for is not None:
        # Start gates the whole program: no login, no clock-in, no context call,
        # nothing spoken, nothing on the glass until the wearer clicks it.
        while not wait_for.is_set() and not stop.is_set():
            await asyncio.sleep(0.1)
        if stop.is_set():
            return
    jwt = args.jwt or os.environ.get("GLASSES_JWT")
    if args.login:
        jwt = mint_session(args.login, admin=admin_client_from_env())
    if not jwt:
        raise SystemExit("pass --login <staff email> (dev), or set GLASSES_JWT / --jwt")
    from scripts.glasses_ear import Ear
    from scripts.glasses_ear import Speaker
    from scripts.glasses_ear import Voice
    from scripts.glasses_ear import read_wav

    listening = not args.script and not args.type
    observe: Callable[[str, Any], None] = observer or (lambda _e, _p: None)
    speaker: Speaker | Voice
    if args.voice == "say":
        speaker = Speaker()
    else:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")  # OPENAI_API_KEY, the same key the backend uses
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("--voice needs OPENAI_API_KEY (in .env), or pass --voice say")
        speaker = Voice(
            args.voice,
            speed=args.speed,
            on_first_audio=lambda ms: observe("timing", {"voice_ms": ms}),
            cache_dir=Path.home() / ".cache" / "millia-glasses" / "voice",
        )

    def print_only(text: str) -> None:
        print(f"[say] {text}")

    def speak_and_wait(text: str) -> None:
        speaker.speak(text)
        speaker.wait()  # a scripted run paces on the spoken line

    speak: Callable[[str], None]
    if not args.speak:
        speak = print_only
    elif listening:
        speak = speaker.speak  # non-blocking, so the ear keeps listening
    else:
        speak = speak_and_wait  # blocking, so a scripted run paces itself
    async with httpx.AsyncClient(
        base_url=args.api, headers={"Authorization": f"Bearer {jwt}"}, timeout=60
    ) as http:
        held: dict[str, Ear | None] = {"ear": None}  # the ear, once it exists: a guest session holds it open

        def on_session(open_: bool) -> None:
            ear_ = held["ear"]
            if ear_ is not None:
                ear_.hold_open = open_
            print("[guest] session open — the guest is speaking" if open_ else "[guest] session closed")

        driver = GlassesHost(
            frame, http=http, task_id=args.task, speak=speak, observer=observer,
            phone_banner=simulator_banner if args.phone_banner else None,
            on_session=on_session, guest_silence=args.guest_silence,
        )
        notices: asyncio.Task[None] | None = None
        # The glass is up before the first door, so a refusal has somewhere to go.
        ctx = await driver.start(quiet=args.read_aloud)
        if not args.read_aloud:
            await driver.checklist()  # the instrument shows the room before the first word
        try:
            if refused(ctx):
                print(f"[glasses] context refused: {ctx['say']}")
            else:
                print(f"[glasses] {ctx.get('me')} · mode {ctx.get('mode')} · room {driver.unit_code}")
            shift = await driver.clock_in()
            if refused(shift):
                print(f"[glasses] clock-in refused: {shift['say']}")
                await driver.show(shift)
            else:
                print(f"[glasses] clocked in · shift {shift.get('shift_id')}")
            if args.notice_poll > 0:
                # What MOPS would put in the bell arrives on the glass instead.
                notices = asyncio.create_task(
                    driver.watch_notifications(stop, interval=args.notice_poll, dwell=args.notice_dwell)
                )
            if listening:
                loop = asyncio.get_running_loop()
                handled = asyncio.Event()

                busy = {"n": 0}  # requests in flight: a closing window must not wipe "thinking"

                async def on_utterance(wav: bytes, wake_required: bool) -> None:
                    busy["n"] += 1
                    try:
                        await _on_utterance(wav, wake_required)
                    finally:
                        busy["n"] -= 1

                async def _on_utterance(wav: bytes, wake_required: bool) -> None:
                    await driver.set_state("thinking")
                    if driver.in_guest_session:
                        # The guest's words: no wake word, nothing spoken, the glass redrawn.
                        cue = await driver.guest_say(audio=wav)
                        if cue.get("intent") == "ignored":
                            await driver.set_state("idle")  # the session closed under this clip
                        else:
                            print(f"[guest] heard: {cue.get('heard')!r}")
                            await driver.set_state("listening")
                        handled.set()
                        return
                    cue = await driver.say(photo_url=args.photo_url, audio=wav, require_wake_word=wake_required)
                    if cue.get("intent") == "ignored":
                        await driver.set_state("idle")
                        print(f"[ear] not for Millia: {cue.get('heard')!r}")
                    else:
                        # `say` drew the view (which clears the dot) and spoke the new line,
                        # cutting the old one: only a wake word interrupts Millia, because
                        # only a wake word gets here.
                        print(f"[ear] heard: {cue.get('heard')!r}")
                        print(f"  {cue['intent']} · {cue['display']['ambient']}")
                    handled.set()

                def on_listening() -> None:
                    asyncio.run_coroutine_threadsafe(driver.set_state("listening"), loop)

                def on_window(open_: bool) -> None:
                    # The follow-up window, shown: the ring and the glass dot say
                    # "listening" while the wearer may speak without the name.
                    if open_:
                        asyncio.run_coroutine_threadsafe(driver.set_state("listening"), loop)
                    elif not busy["n"]:
                        asyncio.run_coroutine_threadsafe(driver.set_state("idle"), loop)

                ear = Ear(
                    on_utterance,
                    loop=loop,
                    threshold=args.vad_threshold,
                    end_silence=args.end_silence,
                    # A replayed clip is the wearer's whole line; the microphone is
                    # everything in the room, so only "Millia" opens it.
                    spotter=spotter,
                    follow_up=args.follow_up,
                    on_listening=on_listening,
                    on_window=on_window,
                    on_frame=lambda level, gate, open_: observe("level", (level, gate, open_)),
                    is_speaking=speaker.is_speaking,
                )
                held["ear"] = ear
                ear.start(microphone=not args.say_file)
                try:
                    if args.say_file:
                        # A WAV stands in for the wearer: the same path, minus the microphone.
                        ear.feed(read_wav(args.say_file))
                        await asyncio.wait_for(handled.wait(), timeout=90)
                    else:
                        while not stop.is_set():
                            await asyncio.sleep(0.2)
                finally:
                    ear.stop()
                    speaker.interrupt()
            elif args.script and args.read_aloud:
                # One take, two voices, no microphone and no Enter: the scene plays
                # itself in front of the recording (Ryan, 2026-08-29).
                events = film_events(Path(args.script).read_text())
                if events and film_clock is not None:
                    # The film speaks; the glass keeps its time.
                    await play_film(driver, events, film_clock, stop)
                    print("\n[take] end of the film's lines — the window stays open; Esc or close it to end")
                    while not stop.is_set():
                        await asyncio.sleep(0.2)
                    return
                if args.voice == "say":
                    raise SystemExit("--read-aloud needs an OpenAI voice, not `say`")
                cache = Path.home() / ".cache" / "millia-glasses" / "voice"
                voices = {
                    "wearer": Voice(args.voice, speed=READ_ALOUD_SPEED, instructions=WEARER_TONE, cache_dir=cache),
                    "guest": Voice(args.guest_voice, speed=READ_ALOUD_SPEED, instructions=GUEST_TONE, cache_dir=cache),
                }
                if take_go is not None:
                    # The window says when: `--ui-from` seconds into the film.
                    while not take_go.is_set() and not stop.is_set():
                        await asyncio.sleep(0.05)
                await play_take(driver, take_lines(Path(args.script).read_text()), voices, stop, gap=args.gap)
                print("\n[take] end of the take — the window stays open; Esc or close it to end")
                while not stop.is_set():
                    await asyncio.sleep(0.2)
            elif args.script:
                # On a terminal the script paces on Enter: the line to read is printed,
                # the wearer says it and presses Enter, Millia answers (spoken to the end),
                # then the next line is printed. Piped stdin paces on `--pause` instead.
                paced = sys.stdin.isatty()
                loop = asyncio.get_running_loop()
                if paced:
                    print("[script] read the line aloud, then press Enter to send it")
                for line in Path(args.script).read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or stop.is_set():
                        continue
                    if paced:
                        print(f"\n▶ {line}   ⏎", end=" ", flush=True)
                        await loop.run_in_executor(None, sys.stdin.readline)
                        if stop.is_set():
                            break
                    else:
                        print(f"\n▶ {line}")
                    if line == "@button":
                        cue = await driver.toggle_guest_session()
                        if cue is not None:
                            print(f"  glass: {guest_line(cue)}")
                        if not paced:
                            await asyncio.sleep(args.pause)
                        continue
                    line = script_line(line)
                    await driver.set_state("listening")
                    await asyncio.sleep(SCRIPT_HEAR)
                    await driver.set_state("thinking")
                    if driver.in_guest_session:
                        cue = await driver.guest_say(line, hold=SCRIPT_THINK)
                        print(f"  glass: {guest_line(cue)}")
                        await driver.set_state("listening")
                    else:
                        photo = args.photo_url if "redo" in line.lower() or "pass" in line.lower() else None
                        cue = await driver.say(line, photo_url=photo, hold=SCRIPT_THINK)
                        print(f"  Millia: {cue.get('say') or '(silent)'}")
                        print(f"  {cue['intent']} · {cue['display']['ambient']}")
                    if not paced:
                        await asyncio.sleep(args.pause)
                print("\n[script] end of the script")
                if paced:
                    # The take is over; the window stays, the glass keeps its last
                    # view and the inbox keeps being watched, until Esc or the red
                    # button (Ryan, 2026-08-28). A piped run returns.
                    print("[script] the window stays open — Esc or close it to end")
                    while not stop.is_set():
                        await asyncio.sleep(0.2)
            else:
                print("type what the wearer says (without 'Millia'); empty line quits")
                loop = asyncio.get_running_loop()
                while not stop.is_set():
                    line = await loop.run_in_executor(None, lambda: sys.stdin.readline())
                    line = line.strip()
                    if not line:
                        break
                    if line == "@button":
                        cue = await driver.toggle_guest_session()
                        if cue is not None:
                            print(f"  glass: {guest_line(cue)}")
                        continue
                    line = script_line(line)
                    if driver.in_guest_session:
                        cue = await driver.guest_say(line)
                        print(f"  glass: {guest_line(cue)}")
                        continue
                    cue = await driver.say(line, photo_url=args.photo_url)
                    print(f"  {cue['intent']} · {cue['display']['ambient']}")
        finally:
            stop.set()
            if notices is not None:
                notices.cancel()
            await driver.stop()


def main() -> None:
    # Run as a file (`python scripts/glasses_host.py`), so make `scripts.glasses_ear` importable.
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--jwt", default=None, help="MOPS staff bearer token (or GLASSES_JWT)")
    ap.add_argument("--login", default=None, metavar="EMAIL",
                    help="mint the wearer's session on the dev project in .env (service role)")
    ap.add_argument("--task", default=None, help="cleaning task id the wearer is on")
    ap.add_argument("--script", default=None, help="file with one utterance per line (no microphone)")
    ap.add_argument("--type", action="store_true", help="type utterances instead of speaking them")
    ap.add_argument("--say-file", default=None, metavar="WAV",
                    help="feed one 16 kHz mono WAV through the ear instead of the microphone, then exit")
    ap.add_argument("--vad-threshold", type=float, default=0.015, help="RMS above which a frame is speech")
    ap.add_argument("--end-silence", type=float, default=1.6,
                    help="seconds of quiet that end an utterance (a pause to think must not)")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between scripted lines")
    ap.add_argument("--photo-url", default=None, help="staged photo URL sent with pass/redo")
    ap.add_argument("--no-speak", dest="speak", action="store_false")
    ap.add_argument("--speed", type=float, default=1.2, help="the voice's pace; 1.0 is the provider's")
    ap.add_argument("--notice-poll", type=float, default=NOTICE_POLL, metavar="SECONDS",
                    help="how often the wearer's notification inbox is read; 0 turns notices off")
    ap.add_argument("--notice-dwell", type=float, default=NOTICE_DWELL, metavar="SECONDS",
                    help="how long a notice holds the glass before the previous view returns")
    ap.add_argument("--follow-up", type=float, default=4.0,
                    help="seconds after Millia's line in which the next utterance needs no wake word")
    ap.add_argument("--guest-silence", type=float, default=GUEST_SILENCE, metavar="SECONDS",
                    help="seconds without a word that close a guest session; 0 leaves it to the button")
    ap.add_argument("--voice", default="shimmer",
                    help="OpenAI voice (nova, shimmer, coral, sage, ...) or `say` for the macOS voice")
    ap.add_argument("--headless", action="store_true", help="no emulator window")
    ap.add_argument("--hardware", action="store_true", help="a real Halo over Bluetooth")
    ap.add_argument("--record", default=None, help="write the glass to this video file")
    ap.add_argument("--read-aloud", action="store_true",
                    help="with --script: the lines are spoken by two voices, in one take, no Enter")
    ap.add_argument("--guest-voice", default="ash", help="the guest's OpenAI voice in a read-aloud take")
    ap.add_argument("--gap", type=float, default=READ_ALOUD_GAP, metavar="SECONDS",
                    help="the silence between two people in a read-aloud take")
    ap.add_argument("--ui-from", type=float, default=0.0, metavar="SECONDS",
                    help="with --backdrop: the glass, the captions and the take begin this far into the film")
    ap.add_argument("--ui-until", type=float, default=None, metavar="SECONDS",
                    help="with --backdrop: the glass and the captions leave the film at this second")
    ap.add_argument("--backdrop", default=None, metavar="VIDEO",
                    help="a video or a still image behind the lens, looping: the room the wearer stands in (needs ffmpeg)")
    ap.add_argument("--no-phone-banner", dest="phone_banner", action="store_false",
                    help="do not mirror a notice as an iOS banner on the booted simulator")
    args = ap.parse_args()

    frame = make_frame(args.hardware)
    stop = threading.Event()
    if args.hardware or args.headless:
        asyncio.run(run(args, frame, stop))
        return

    from scripts.glasses_window import Backdrop
    from scripts.glasses_window import WindowState
    from scripts.glasses_window import run_window

    emulator = frame._emu
    if args.record:
        emulator.start_recording(fps=30)
    cuts = [e.at for e in film_events(Path(args.script).read_text()) if e.kind == "cut"] if args.script else []
    window = WindowState(
        ui_from=cuts[0] if cuts else args.ui_from,
        ui_until=cuts[1] if len(cuts) > 1 else args.ui_until,
    )
    backdrop = Backdrop(Path(args.backdrop)) if args.backdrop else None

    def _worker() -> None:
        try:
            asyncio.run(run(args, frame, stop, observer=window.observe, wait_for=window.start, take_go=window.take_go, film_clock=window.film_time))
        finally:
            stop.set()

    threading.Thread(target=_worker, daemon=True, name="glasses-host").start()
    try:
        run_window(emulator, window, stop, backdrop)  # macOS needs the window on the main thread
    except KeyboardInterrupt:
        stop.set()
    if args.record:
        emulator.stop_recording(args.record)
        print(f"[glasses] wrote {args.record}")


if __name__ == "__main__":
    main()
