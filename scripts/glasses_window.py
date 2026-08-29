"""The lens: what the wearer sees, with the glass added onto the world.

This window is the view through one lens. The world behind it is not a place:
a slow field of out-of-focus light, warm and cool, drifting — unless a
``Backdrop`` is given, in which case the world is that video, the room the
wearer stands in, looping behind the lens (the reception demo: the guest at
the desk, first person, 2026-08-29). The lens is one hairline. The glass — the
emulator's 256-px display, pixel for pixel — sits top right and is **added**
onto the world, the way a see-through optic works: black
on the glass is transparent, text and icons float. Below, one subtitle:
Millia's reply, whole. Nothing else — what the wearer said, the room hears.

Ground and accent are the landing page's (near-black hsl(220 20% 6%), #8b5cf6);
the face is PretendardJP (assets/fonts, the dashboard's own files). ``run_window``
must own the main thread on macOS; ``render`` draws one frame onto any surface,
so a test renders headless.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
FONT_DIR = REPO / "assets" / "fonts"
ICON = REPO / "assets" / "logo.png"
FONT_REGULAR = FONT_DIR / "PretendardJP-Regular.ttf"
FONT_MEDIUM = FONT_DIR / "PretendardJP-Medium.ttf"
FONT_BOLD = FONT_DIR / "PretendardJP-Bold.ttf"

WIDTH, HEIGHT = 800, 450
GROUND = (12, 14, 18)  # hsl(220 20% 6%)
RULE = (38, 43, 55)
INK = (238, 240, 245)
INK_MUTED = (146, 152, 168)
INK_FAINT = (84, 90, 108)
PURPLE = (139, 92, 246)  # #8b5cf6
PURPLE_DIM = (72, 52, 128)
GREEN = (0x22, 0xC5, 0x5E)
# The guest view's question, mirrored as the subtitle in its colour (main.lua QUESTION_COLOURS).
ASK_COLOURS = {"needed": (0xEF, 0x44, 0x44), "optional": (0xF9, 0x73, 0x16)}

MARGIN = 40
DISPLAY = 256  # the glass at 1x: one device pixel per glass pixel
DISPLAY_POS = (WIDTH - MARGIN - DISPLAY, 36)  # top right, where the optic sits
OPTIC_INSET = 8
LENS_INSET = 22  # the hairline, this far in from the window's edge
LENS_RADIUS = 130
SUBTITLE_BOTTOM = HEIGHT - LENS_INSET - 30  # inside the lens
SUBTITLE_W = 600
START_RECT = (MARGIN, 24, 88, 24)  # the Start control, top left
TURNS_KEPT = 4  # the last replies of Millia's, for the subtitle
INTRO_SECONDS = 2.0  # after Start the glass glides from large-and-centred to its place
INTRO_SCALE = 1.6  # the glass before Start: large in the centre, so a viewer sees it is a display

# The world: light that is out of focus. Each blob is (colour, diameter, home x, home y,
# drift x, drift y, period s, phase). Warm from the right, cool from the left, all dim
# enough that white text added on top stays white.
LIGHTS: tuple[tuple[tuple[int, int, int], int, float, float, float, float, float, float], ...] = (
    ((84, 58, 30), 520, 0.78, 0.30, 36, 22, 41.0, 0.0),
    ((70, 44, 22), 300, 0.62, 0.72, 28, 18, 29.0, 1.9),
    ((34, 32, 74), 560, 0.18, 0.62, 42, 26, 53.0, 0.7),
    ((30, 24, 60), 320, 0.32, 0.20, 24, 30, 37.0, 3.1),
    ((52, 40, 22), 180, 0.92, 0.84, 18, 12, 23.0, 2.4),
    ((26, 30, 58), 220, 0.06, 0.16, 20, 16, 31.0, 4.2),
)

BACKDROP_FPS = 30  # the video is resampled to the window's own tick, one frame per frame
BACKDROP_CATCH_UP = BACKDROP_FPS  # frames the window will skip through in one tick to stay on time
SHADE_CENTRE = 96  # under the glass the world is dimmed to this /255 at the centre, so text added on a bright room stays legible
CAPTION_PLATE = (*GROUND, 176)  # behind a caption: the ground, mostly, so the words hold on marble
CAPTION_PAD = (16, 10)


class Backdrop:
    """A video — or a still image, held — behind the lens. ffmpeg decodes it to
    raw RGB at the window's size and tick, looping for ever; the window reads
    one frame per tick and holds only the current one. Needs ffmpeg on PATH
    and nothing else."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._proc: subprocess.Popen[bytes] | None = None
        self._audio: subprocess.Popen[bytes] | None = None
        self._frame: bytes | None = None
        self._index = -1
        self._size = WIDTH * HEIGHT * 3

    def open(self) -> None:
        if not self.path.is_file():
            raise SystemExit(f"--backdrop: no such file: {self.path}")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise SystemExit("--backdrop needs ffmpeg on PATH (brew install ffmpeg)")
        self._proc = subprocess.Popen(
            [
                ffmpeg, "-v", "error", "-stream_loop", "-1", "-i", str(self.path), "-an",
                "-vf", f"scale={WIDTH}:{HEIGHT},fps={BACKDROP_FPS}",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def _read(self) -> bool:
        assert self._proc is not None and self._proc.stdout is not None
        data = self._proc.stdout.read(self._size)
        if len(data) < self._size:
            return False  # the stream ended (a file ffmpeg could not loop): the last frame stays
        self._frame = data
        self._index += 1
        return True

    def frame_at(self, t: float) -> bytes | None:
        """The frame for the window's clock `t`, RGB bytes at WIDTH x HEIGHT; None
        until the first frame has arrived. Frames the window was too slow for are
        skipped, so the video keeps time with the room."""
        if self._proc is None:
            self.open()
        want = max(0, int(t * BACKDROP_FPS))
        for _ in range(BACKDROP_CATCH_UP):
            if self._index >= want or not self._read():
                break
        return self._frame

    def play_audio(self) -> None:
        """The file's sound, if it has any, to the speakers from now: a second
        ffmpeg decodes it to PCM and a thread streams it. A silent file (a still
        image) yields nothing and the thread ends."""
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None or self._audio is not None:
            return
        self._audio = subprocess.Popen(
            [ffmpeg, "-v", "error", "-i", str(self.path), "-vn", "-f", "s16le", "-ac", "2", "-ar", "48000", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        proc = self._audio

        def pump() -> None:
            import sounddevice as sd  # type: ignore[import-untyped]

            assert proc.stdout is not None
            with sd.RawOutputStream(samplerate=48000, channels=2, dtype="int16") as out:
                while True:
                    chunk = proc.stdout.read(9600)  # 50 ms
                    if not chunk:
                        return
                    out.write(chunk)

        threading.Thread(target=pump, daemon=True, name="glasses-film-audio").start()

    def close(self) -> None:
        for proc in (self._proc, self._audio):
            if proc is not None:
                proc.kill()
                proc.wait()
        self._proc = None
        self._audio = None


@dataclass
class WindowState:
    """Everything the lens shows besides the framebuffer. Written by the
    driver's threads, read by the window's; guarded by one lock."""

    me: str = ""
    room: str = ""
    state: str = "idle"  # idle | listening | thinking
    turns: list[str] = field(default_factory=list)  # Millia's replies, oldest first
    guest: bool = False  # a guest session is open: the ring stays lit, the ear is held open
    ask: tuple[str, str] | None = None  # the open question and its level, while a session runs
    caption: str | None = None  # in a take: the line being spoken, as a caption; the glass keeps the question
    # A backdrop that is a cut video: the glass and the captions are drawn only from
    # `ui_from` to `ui_until` seconds after Start — the POV part; the rest is the film.
    ui_from: float = 0.0
    ui_until: float | None = None
    take_go: threading.Event = field(default_factory=threading.Event, repr=False)  # set at ui_from: the take begins
    started_mono: float | None = None  # time.monotonic() at Start: the film's clock for the driver's thread
    # The ear does not open until the wearer clicks Start (or presses Enter): the
    # window can be set up, phone and dashboard beside it, with no room talk going up.
    start: threading.Event = field(default_factory=threading.Event, repr=False)
    started_at: float | None = None  # the window's clock when Start was pressed: the intro's zero
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def film_time(self) -> float | None:
        """Seconds of film since Start, on any thread; None before Start."""
        return None if self.started_mono is None else time.monotonic() - self.started_mono

    def click(self, pos: tuple[int, int]) -> None:
        if not self.start.is_set() and START_RECT[0] <= pos[0] <= START_RECT[0] + START_RECT[2] and START_RECT[1] <= pos[1] <= START_RECT[1] + START_RECT[3]:
            self.start.set()

    def observe(self, event: str, payload: Any) -> None:
        """The driver's observer hook."""
        with self._lock:
            if event == "context":
                me = payload.get("me") or {}
                self.me = str(me.get("name") or "") if isinstance(me, dict) else str(me)
                current = payload.get("current") or payload.get("next") or {}
                self.room = str(current.get("unit_code") or "")
            elif event == "state":
                self.state = str(payload)
            elif event == "guest":
                self.guest = bool(payload)
                if not self.guest:
                    self.caption = None  # the session closed: the last line is not left hanging
            elif event == "line":
                self.caption = str(payload) if payload else None
            elif event == "checklist":
                self.room = str(payload.get("unit_code") or self.room)
            elif event == "cue":
                if payload.get("intent") == "ignored":
                    self.state = "idle"
                    return
                if payload.get("intent") == "guest":
                    # Nothing is spoken in a session: the subtitle is the open
                    # question, in its colour, large enough for a recording —
                    # the glass has it at 16 px. Millia's last line is stale now.
                    display = payload.get("display") or {}
                    question, level = display.get("question"), display.get("level")
                    self.ask = (str(question), str(level)) if question and level in ASK_COLOURS else None
                    self.turns.clear()
                    self.state = "idle"
                    return
                if payload.get("say"):
                    self.turns.append(str(payload["say"]))
                self.state = "idle"
                del self.turns[:-TURNS_KEPT]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "me": self.me,
                "room": self.room,
                # While a guest speaks the ear is open: the ring says so, as in the follow-up window.
                "state": "listening" if self.guest and self.state == "idle" else self.state,
                "turns": list(self.turns),
                "ask": self.ask,
                "caption": self.caption,
            }


def _fonts() -> dict[str, Any]:
    import pygame

    pygame.font.init()
    return {
        "hint": pygame.font.Font(str(FONT_MEDIUM), 12),
        "you": pygame.font.Font(str(FONT_REGULAR), 16),
        "millia": pygame.font.Font(str(FONT_BOLD), 19),
        "control": pygame.font.Font(str(FONT_MEDIUM), 13),
    }


def wrap_text(text: str, font: Any, max_width: int) -> list[str]:
    """Greedy word wrap on the font's real metrics. Nothing is cut."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if font.size(candidate)[0] <= max_width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _light(colour: tuple[int, int, int], diameter: int) -> Any:
    """One out-of-focus light: the colour at the centre, black at the edge, so
    it adds onto the ground and fades to nothing."""
    import pygame

    surf = pygame.Surface((diameter, diameter))
    surf.fill((0, 0, 0))
    r = diameter // 2
    rings = 64
    for i in range(rings, 0, -1):
        k = (i / rings) ** 2  # a soft falloff: most of the light is near the centre
        shade = tuple(int(c * (1 - k)) for c in colour)
        pygame.draw.circle(surf, shade, (r, r), int(r * i / rings))
    return surf


_LIGHTS_CACHE: list[Any] = []
_OUTSIDE_LENS: list[Any] = []
def _outside_lens() -> Any:
    """The ground everywhere except inside the lens: the world is seen through
    the glass only, so the hairline reads as an edge, not a decoration."""
    import pygame

    surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    surf.fill((*GROUND, 255))
    lens = pygame.Rect(LENS_INSET, LENS_INSET, WIDTH - 2 * LENS_INSET, HEIGHT - 2 * LENS_INSET)
    pygame.draw.rect(surf, (0, 0, 0, 0), lens, border_radius=LENS_RADIUS)
    return surf


def draw_world(screen: Any, t: float, backdrop: Backdrop | None = None) -> None:
    """The world: the backdrop's frame for `t`, edge to edge and nothing over it
    — a film is the whole picture (Ryan, 2026-08-29) — else the ground and the
    drifting lights inside the lens, and the lens as one hairline."""
    import pygame

    frame = backdrop.frame_at(t) if backdrop else None
    if frame is not None:
        screen.blit(pygame.image.frombuffer(frame, (WIDTH, HEIGHT), "RGB"), (0, 0))
        return
    if not _LIGHTS_CACHE:
        _LIGHTS_CACHE.extend(_light(colour, d) for colour, d, *_rest in LIGHTS)
    screen.fill(GROUND)
    for surf, (_c, d, hx, hy, dx, dy, period, phase) in zip(_LIGHTS_CACHE, LIGHTS, strict=True):
        w = 2 * math.pi / period
        x = hx * WIDTH + dx * math.sin(w * t + phase) - d / 2
        y = hy * HEIGHT + dy * math.cos(w * t * 0.8 + phase) - d / 2
        screen.blit(surf, (int(x), int(y)), special_flags=pygame.BLEND_RGB_ADD)
    if not _OUTSIDE_LENS:
        _OUTSIDE_LENS.append(_outside_lens())
    screen.blit(_OUTSIDE_LENS[0], (0, 0))
    lens = pygame.Rect(LENS_INSET, LENS_INSET, WIDTH - 2 * LENS_INSET, HEIGHT - 2 * LENS_INSET)
    pygame.draw.rect(screen, RULE, lens, width=1, border_radius=LENS_RADIUS)


def intro_progress(started_at: float | None, t: float) -> float:
    """0 before Start (the glass large in the centre), 1 once it has glided to
    its place; an ease-out in between, so it lands rather than stops."""
    if started_at is None:
        return 0.0
    p = min(1.0, max(0.0, (t - started_at) / INTRO_SECONDS))
    return 1 - (1 - p) ** 3


def glass_geometry(k: float) -> tuple[int, int, int]:
    """(x, y, size) of the glass at intro progress k: from INTRO_SCALE in the
    centre of the lens to 1x at DISPLAY_POS."""
    big = int(DISPLAY * INTRO_SCALE)
    x0, y0 = (WIDTH - big) // 2, (HEIGHT - big) // 2
    x1, y1 = DISPLAY_POS
    size = int(big + (DISPLAY - big) * k)
    return int(x0 + (x1 - x0) * k), int(y0 + (y1 - y0) * k), size


_SHADE_CACHE: dict[int, Any] = {}


def _shade(size: int) -> Any:
    """The world under the glass, dimmed: full at the rim, SHADE_CENTRE at the
    centre, a soft falloff between — so white text added on a bright room is
    still white on something, and the disc does not read as a hole."""
    import pygame

    if size not in _SHADE_CACHE:
        surf = pygame.Surface((size, size))
        surf.fill((255, 255, 255))
        r = size // 2 - int(OPTIC_INSET * size / DISPLAY)
        rings = 48
        for i in range(rings, 0, -1):
            k = (i / rings) ** 2
            v = int(255 - (255 - SHADE_CENTRE) * (1 - k))
            pygame.draw.circle(surf, (v, v, v), (size // 2, size // 2), int(r * i / rings))
        _SHADE_CACHE[size] = surf
    return _SHADE_CACHE[size]


def draw_display(
    screen: Any, framebuffer: Any, state: str, t: float, k: float = 1.0, shade: bool = False
) -> None:
    """The glass, added onto the world. Black is transparent; the rest floats.
    `k` is the intro's progress: the glass is scaled and placed by it. With
    `shade` the world under the glass is dimmed first (a backdrop is a lit room)."""
    import pygame

    x, y, size = glass_geometry(k)
    if shade:
        screen.blit(_shade(size), (x, y), special_flags=pygame.BLEND_RGB_MULT)
    disp = pygame.image.fromstring(framebuffer.tobytes(), framebuffer.size, framebuffer.mode).convert()
    if size != DISPLAY:
        disp = pygame.transform.scale(disp, (size, size))
    mask = pygame.Surface((size, size))
    r = size // 2 - int(OPTIC_INSET * size / DISPLAY)
    pygame.draw.circle(mask, (255, 255, 255), (size // 2, size // 2), r)
    disp.blit(mask, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
    screen.blit(disp, (x, y), special_flags=pygame.BLEND_RGB_ADD)
    # the state, as a ring: purple while listening, breathing while thinking,
    # nothing when idle. Before Start the glass is dark (its program loads on
    # Start) and black is see-through, so the ring stands in for the optic's
    # edge: the circle is there to be seen, then glides (Ryan, 2026-08-28).
    cx, cy = x + size // 2, y + size // 2
    if state == "off":
        pygame.draw.circle(screen, PURPLE, (cx, cy), r + 4, width=2)
    elif state == "listening":
        pygame.draw.circle(screen, PURPLE, (cx, cy), r + 4, width=2)
    elif state == "thinking":
        kk = 0.5 + 0.5 * math.sin(t * 2 * math.pi / 1.6)
        colour = tuple(int(PURPLE_DIM[i] + (PURPLE[i] - PURPLE_DIM[i]) * kk) for i in range(3))
        pygame.draw.circle(screen, colour, (cx, cy), r + 4, width=2)


def draw_subtitles(
    screen: Any,
    fonts: dict[str, Any],
    turns: list[str],
    bottom: int,
    ask: tuple[str, str] | None = None,
    caption: str | None = None,
) -> None:
    """Millia's whole reply, centred, wrapped, never cut, growing upward from `bottom`.
    What the wearer said is not shown: the room hears it. In a guest session the
    subtitle is the open question instead, in the glass's colour for it — unless
    a take is running: then the slot is a caption of the line being spoken, on a
    plate of the ground, and the question is on the glass alone, once."""
    import pygame

    text: str | None
    colour: tuple[int, int, int]
    if caption:
        text, colour = caption, INK
    else:
        text, colour = (ask[0], ASK_COLOURS[ask[1]]) if ask else (turns[-1] if turns else None, INK)
    if not text:
        return
    font = fonts["millia"]
    lines = wrap_text(text, font, SUBTITLE_W)
    y = bottom - font.get_linesize() * len(lines)
    if caption:
        w = max(font.size(line)[0] for line in lines) + 2 * CAPTION_PAD[0]
        h = font.get_linesize() * len(lines) + 2 * CAPTION_PAD[1]
        plate = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(plate, CAPTION_PLATE, plate.get_rect(), border_radius=12)
        screen.blit(plate, (WIDTH // 2 - w // 2, y - CAPTION_PAD[1]))
    for line in lines:
        label = font.render(line, True, colour)
        screen.blit(label, (WIDTH // 2 - label.get_width() // 2, y))
        y += font.get_linesize()


def render(
    screen: Any,
    framebuffer: Any,
    state: WindowState,
    fonts: dict[str, Any],
    t: float,
    backdrop: Backdrop | None = None,
) -> None:
    """Draw one frame. `framebuffer` is the emulator's 256x256 PIL image;
    `backdrop`, if given, is the world behind the lens."""
    import pygame

    s = state.snapshot()
    if state.start.is_set() and state.started_at is None:
        state.started_at = t  # Start was pressed: the intro glide begins on this frame
        state.started_mono = time.monotonic()
        if backdrop is not None:
            backdrop.play_audio()  # the film's own sound, from its first frame
    since = t - state.started_at if state.started_at is not None else 0.0  # the film's clock: Start is its first frame
    draw_world(screen, since if backdrop is not None else t, backdrop)
    if backdrop is not None and state.start.is_set():
        if since >= state.ui_from:
            state.take_go.set()
        ui_on = since >= state.ui_from and (state.ui_until is None or since < state.ui_until)
        if not ui_on:
            return  # the film alone: before the POV part, and after the tasks are filed
        k = 1.0 if state.ui_from else intro_progress(state.started_at, t)  # cut in at its place, no glide
    else:
        k = intro_progress(state.started_at, t)
    shown = s["state"] if state.start.is_set() else "off"
    draw_display(screen, framebuffer, shown, t, k, shade=backdrop is not None)
    draw_subtitles(screen, fonts, s["turns"], SUBTITLE_BOTTOM, s["ask"], s["caption"])

    if not state.start.is_set():
        # Before Start: one control, the brand's colour, and nothing listens.
        rect = pygame.Rect(*START_RECT)
        pygame.draw.rect(screen, PURPLE, rect, border_radius=12)
        label = fonts["control"].render("Start", True, INK)
        screen.blit(label, label.get_rect(center=rect.center))
        hint = fonts["hint"].render("or press Enter", True, INK_FAINT)
        screen.blit(hint, (rect.right + 10, rect.centery - hint.get_height() // 2))


def run_window(
    emulator: Any,
    state: WindowState,
    stop: threading.Event,
    backdrop: Backdrop | None = None,
) -> None:
    """Own the main thread until the window closes or `stop` is set."""
    import os

    os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "80,60")
    import pygame

    if backdrop is not None:
        backdrop.open()  # before the window: a missing file or ffmpeg fails here, not mid-demo
    pygame.display.init()
    pygame.display.set_icon(pygame.image.load(str(ICON)))  # Millia in the Dock, not pygame
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Millia · glasses")
    fonts = _fonts()
    clock = pygame.time.Clock()
    t0 = time.monotonic()
    try:
        while not stop.is_set():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    stop.set()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        stop.set()
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        state.start.set()
                    elif event.key == pygame.K_SPACE:
                        emulator.inject_button_single()
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    state.click(event.pos)
            render(screen, emulator.get_framebuffer(), state, fonts, time.monotonic() - t0, backdrop)
            pygame.display.flip()
            clock.tick(30)
    finally:
        pygame.display.quit()
        if backdrop is not None:
            backdrop.close()
