"""scripts/glasses_window.py — the lens, rendered headless and read back as pixels.

USER-VISIBLE ARTIFACT: the frame on screen. SDL's dummy video driver renders
the real `render()` onto a surface with no display attached, so the assertions
are on what is seen: the glass added onto the world pixel for pixel (black is
see-through), the world drifting, the lens hairline, the ring per state, the
subtitle whole, the Start control.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest
from PIL import Image

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import scripts.glasses_window as win

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def surface():  # type: ignore[no-untyped-def]
    import pygame

    pygame.display.init()
    screen = pygame.display.set_mode((win.WIDTH, win.HEIGHT))
    yield screen, win._fonts()
    pygame.display.quit()


def _frame_with_green_block() -> Image.Image:
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 255))
    for x in range(108, 148):
        for y in range(100, 140):
            img.putpixel((x, y), (*win.GREEN, 255))
    return img


def _has(screen, colour, box, tol=6):  # type: ignore[no-untyped-def]
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(win.WIDTH, x1), min(win.HEIGHT, y1)
    return any(
        all(abs(int(c) - int(t)) <= tol for c, t in zip(screen.get_at((x, y))[:3], colour, strict=True))
        for x in range(x0, x1, 2)
        for y in range(y0, y1, 2)
    )


def _render(surface, state, t=0.4, frame=None):  # type: ignore[no-untyped-def]
    screen, fonts = surface
    win.render(screen, frame or _frame_with_green_block(), state, fonts, t)
    return screen


def _settled() -> win.WindowState:
    """A state past the intro: Start pressed long ago, the glass at its place."""
    state = win.WindowState()
    state.start.set()
    state.started_at = -100.0
    return state


def test_fonts_and_icon_are_the_dashboards_own_files() -> None:
    for path in (win.FONT_REGULAR, win.FONT_MEDIUM, win.FONT_BOLD, win.ICON):
        assert path.is_file(), path


def test_the_glass_is_added_onto_the_world_and_black_is_see_through(surface) -> None:  # type: ignore[no-untyped-def]
    """The glass sits top right, one device pixel per glass pixel. A lit glass
    pixel floats over the world; a black one shows the world, unchanged."""
    x, y = win.DISPLAY_POS
    assert x + win.DISPLAY <= win.WIDTH and x > win.WIDTH // 2, "top right"
    state = _settled()
    lit = _render(surface, state).get_at((x + 110, y + 110))[:3]
    assert lit[1] >= win.GREEN[1] and lit[1] > lit[0] + 100, f"framebuffer (110, 110) floats green on screen: {lit}"
    beside = _render(surface, state).get_at((x + 107, y + 110))[:3]
    assert beside[1] < 0x60, f"one glass pixel is one device pixel: {beside}"
    blank = Image.new("RGBA", (256, 256), (0, 0, 0, 255))
    world = _render(surface, state, frame=blank).get_at((x + 107, y + 110))[:3]
    assert beside == world, "a black glass pixel is the world behind it"


def test_the_world_drifts_and_the_lens_is_one_hairline(surface) -> None:  # type: ignore[no-untyped-def]
    state = win.WindowState()
    a = _render(surface, state, t=0.0).copy()
    b = _render(surface, state, t=12.0)
    assert any(a.get_at((x, y)) != b.get_at((x, y)) for x in range(0, win.WIDTH, 40) for y in range(0, win.HEIGHT, 40)), (
        "the light behind the lens moves"
    )
    assert b.get_at((win.WIDTH // 2, win.LENS_INSET))[:3] == win.RULE, "the hairline, top centre"
    assert b.get_at((4, 4))[:3] == win.GROUND, "outside the lens is the ground"


def test_the_ring_tells_the_state(surface) -> None:  # type: ignore[no-untyped-def]
    x, y = win.DISPLAY_POS
    cx, cy = x + win.DISPLAY // 2, y + win.DISPLAY // 2
    r = win.DISPLAY // 2 - win.OPTIC_INSET + 4
    ring = (cx - r - 3, cy - 2, cx - r + 3, cy + 2)
    state = _settled()
    assert not _has(_render(surface, state), win.PURPLE, ring), "idle: no ring"
    state.observe("state", "listening")
    assert _has(_render(surface, state), win.PURPLE, ring)
    state.observe("state", "idle")
    assert not _has(_render(surface, state), win.PURPLE, ring)


def test_subtitles_show_millia_only_and_ignored_adds_nothing(surface) -> None:  # type: ignore[no-untyped-def]
    state = win.WindowState()
    state.observe("cue", {"intent": "ignored", "heard": "the bathroom is done", "say": ""})
    assert state.snapshot()["turns"] == []
    state.observe("cue", {"intent": "done", "heard": "Milia, done.", "say": "Done. Step 2 of 5: Strip the bed."})
    screen = _render(surface, state)
    area = (win.WIDTH // 2 - win.SUBTITLE_W // 2, win.SUBTITLE_BOTTOM - 80, win.WIDTH // 2 + win.SUBTITLE_W // 2, win.SUBTITLE_BOTTOM)
    assert _has(screen, win.INK, area), "Millia's reply in ink"
    assert not _has(screen, win.INK, (0, win.SUBTITLE_BOTTOM, win.WIDTH, win.HEIGHT)), "nothing below the subtitle"
    for i in range(10):
        state.observe("cue", {"intent": "next", "heard": f"q{i}", "say": f"a{i}"})
    assert len(state.snapshot()["turns"]) == 4


def test_start_control_shows_until_clicked_and_a_click_elsewhere_does_nothing(surface) -> None:  # type: ignore[no-untyped-def]
    state = win.WindowState()
    x, y, w, h = win.START_RECT
    button = (x, y, x + w, y + h)
    screen = _render(surface, state)
    assert _has(screen, win.PURPLE, button), "Start is the brand's colour"
    assert not state.start.is_set()
    state.click((win.WIDTH // 2, win.HEIGHT // 2))
    assert not state.start.is_set(), "a click outside the control arms nothing"
    state.click((x + w // 2, y + h // 2))
    assert state.start.is_set()
    screen = _render(surface, state)
    assert not _has(screen, win.PURPLE, button), "after Start the control is gone"


def test_wrap_text_cuts_nothing(surface) -> None:  # type: ignore[no-untyped-def]
    _screen, fonts = surface
    text = "You have two cleanings today: Makeup 2008, then Departure 1213, and nothing is in progress right now."
    lines = win.wrap_text(text, fonts["millia"], 400)
    assert " ".join(lines) == text
    assert all(fonts["millia"].size(line)[0] <= 400 for line in lines)


def test_a_three_line_reply_is_drawn_whole_and_the_wearers_line_is_not(surface) -> None:  # type: ignore[no-untyped-def]
    """Nothing on the lens is cut: a long reply from Millia grows upward from
    the subtitle floor, every line in ink."""
    _screen, fonts = surface
    state = win.WindowState()
    reply = (
        "You have two cleanings today: Makeup 2008, then Departure 1213. Nothing is in progress right now, "
        "and Kai finished 1607 at ten past nine, so the corridor on that floor is clear for you. "
        "After that the afternoon is free."
    )
    lines = win.wrap_text(reply, fonts["millia"], win.SUBTITLE_W)
    assert len(lines) >= 3
    state.observe("cue", {"intent": "ask", "heard": "Milia, what is next?", "say": reply})
    screen = _render(surface, state)
    line_h = fonts["millia"].get_linesize()
    top = win.SUBTITLE_BOTTOM - len(lines) * line_h
    for i in range(len(lines)):
        row = (win.WIDTH // 2 - 100, top + i * line_h, win.WIDTH // 2 + 100, top + (i + 1) * line_h)
        assert _has(screen, win.INK, row), f"reply line {i + 1} of {len(lines)} in ink"
    assert not _has(screen, win.INK_MUTED, (0, top - 40, win.WIDTH, top)), "what the wearer said is not printed: the room hears it"


def test_before_start_the_glass_is_large_in_the_centre_and_glides_to_its_place_after(surface) -> None:  # type: ignore[no-untyped-def]
    """Ryan, 2026-08-28: a viewer must not think the glasses fill their sight
    with a circle. Before Start the display is shown large and centred — "this
    is the display" — and on Start it glides to where it sits in the lens."""
    state = win.WindowState()
    x, _y, size = win.glass_geometry(0.0)
    assert size == int(win.DISPLAY * win.INTRO_SCALE) and abs(x + size // 2 - win.WIDTH // 2) <= 1
    screen = _render(surface, state, t=1.0)
    centre = screen.get_at((win.WIDTH // 2 + int(-1 * size / win.DISPLAY), win.HEIGHT // 2))[:3]
    assert centre[1] > 150, f"the green block, scaled, sits at the centre before Start: {centre}"
    r = size // 2 - int(win.OPTIC_INSET * size / win.DISPLAY) + 4
    rim = (win.WIDTH // 2 - r - 3, win.HEIGHT // 2 - 2, win.WIDTH // 2 - r + 3, win.HEIGHT // 2 + 2)
    assert _has(screen, win.PURPLE, rim), "before Start the optic's edge is a purple ring: the dark glass is see-through"
    state.start.set()
    _render(surface, state, t=1.0)
    assert state.started_at == 1.0, "the first frame after Start is the intro's zero"
    assert 0.0 < win.intro_progress(1.0, 1.5) < 1.0 and win.intro_progress(1.0, 1.0 + win.INTRO_SECONDS) == 1.0
    screen = _render(surface, state, t=1.0 + win.INTRO_SECONDS + 1)
    hx, hy = win.DISPLAY_POS
    assert screen.get_at((hx + 110, hy + 110))[1] >= win.GREEN[1], "landed: one glass pixel per device pixel, top right"


def test_the_ring_stays_lit_while_a_guest_session_is_open() -> None:
    state = _settled()
    state.observe("guest", True)
    assert state.snapshot()["state"] == "listening", "the ear is held open: the ring says so"
    state.observe("cue", {"intent": "guest", "say": "", "display": {}})
    assert state.snapshot()["state"] == "listening", "a silent guest cue does not put the ring out"
    assert state.snapshot()["turns"] == [], "nothing spoken, nothing subtitled"
    state.observe("state", "thinking")
    assert state.snapshot()["state"] == "thinking"
    state.observe("guest", False)
    state.observe("state", "idle")
    assert state.snapshot()["state"] == "idle"


def test_in_a_session_the_open_question_is_the_subtitle_in_its_colour(surface) -> None:  # type: ignore[no-untyped-def]
    state = _settled()
    state.observe("cue", {"intent": "where_am_i", "say": "Good morning, Ry.", "display": {}})
    state.observe("guest", True)
    red = {"intent": "guest", "say": "", "display": {"question": "How many towels?", "level": "needed"}}
    state.observe("cue", red)
    snap = state.snapshot()
    assert snap["ask"] == ("How many towels?", "needed")
    assert snap["turns"] == [], "Millia's last spoken line is stale once the guest speaks"
    screen = _render(surface, state)
    band = (0, win.SUBTITLE_BOTTOM - 40, win.WIDTH, win.SUBTITLE_BOTTOM)
    assert _has(screen, win.ASK_COLOURS["needed"], band), "the question, in red, where the subtitle goes"
    state.observe("cue", {"intent": "guest", "say": "", "display": {"question": "When to deliver?", "level": "optional"}})
    screen = _render(surface, state)
    assert _has(screen, win.ASK_COLOURS["optional"], band)
    state.observe("cue", {"intent": "guest", "say": "", "display": {"question": None, "level": None, "filed": 2}})
    assert state.snapshot()["ask"] is None
    screen = _render(surface, state)
    assert not _has(screen, win.ASK_COLOURS["needed"], band) and not _has(screen, win.ASK_COLOURS["optional"], band)


# --- the backdrop: a video is the world behind the lens (the reception demo, 2026-08-29) ---



def _clip(path, source: str) -> None:
    """A one-second 30 fps clip from an ffmpeg lavfi source, so the test needs no fixture file."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source,
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


@pytest.fixture
def blue_clip(tmp_path):  # type: ignore[no-untyped-def]
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not on PATH")
    path = tmp_path / "blue.mp4"
    _clip(path, "color=c=0x2040A0:s=64x36:d=1:r=30")
    return path


def _blank() -> Image.Image:
    return Image.new("RGBA", (256, 256), (0, 0, 0, 255))


def _render_over(surface, state, backdrop, t=0.4, frame=None):  # type: ignore[no-untyped-def]
    screen, fonts = surface
    win.render(screen, frame or _blank(), state, fonts, t, backdrop)
    return screen


def test_a_backdrop_fills_the_window_edge_to_edge(surface, blue_clip) -> None:  # type: ignore[no-untyped-def]
    backdrop = win.Backdrop(blue_clip)
    try:
        screen = _render_over(surface, _settled(), backdrop)
        inside = screen.get_at((200, 300))[:3]
        assert all(abs(int(c) - int(t)) <= 8 for c, t in zip(inside, (0x20, 0x40, 0xA0), strict=True)), inside
        outside = screen.get_at((2, 2))[:3]
        assert all(abs(int(c) - int(t)) <= 8 for c, t in zip(outside, inside, strict=True)), f"the film fills the window: no lens, no frame {outside}"
        assert not _has(screen, win.RULE, (0, win.LENS_INSET - 2, win.WIDTH, win.LENS_INSET + 2), tol=2), "no hairline"
        assert not _has(screen, (84, 58, 30), (0, 0, win.WIDTH, win.HEIGHT), tol=2), "the drifting lights are gone"
    finally:
        backdrop.close()


def test_the_backdrop_keeps_time_with_the_clock_and_loops(tmp_path) -> None:  # type: ignore[no-untyped-def]
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not on PATH")
    path = tmp_path / "moving.mp4"
    _clip(path, "testsrc=s=64x36:d=1:r=30")  # a moving pattern: a later frame differs from an earlier one
    backdrop = win.Backdrop(path)
    try:
        first = backdrop.frame_at(0.0)
        assert first is not None and len(first) == win.WIDTH * win.HEIGHT * 3
        assert backdrop.frame_at(0.5) != first, "half a second on, the picture has moved"
        past_the_end = backdrop.frame_at(1.7)  # the clip is one second long
        # one tick catches up at most BACKDROP_CATCH_UP frames; past 30 the clip has looped
        assert past_the_end is not None and backdrop._index > 30, "the clip loops rather than freezing"
    finally:
        backdrop.close()


def test_under_the_glass_the_room_is_dimmed_and_the_glass_still_floats(surface, blue_clip) -> None:  # type: ignore[no-untyped-def]
    backdrop = win.Backdrop(blue_clip)
    try:
        x, y = win.DISPLAY_POS
        centre = (x + win.DISPLAY // 2, y + win.DISPLAY // 2)
        screen = _render_over(surface, _settled(), backdrop)
        under = screen.get_at(centre)[:3]
        room = screen.get_at((200, 300))[:3]
        assert sum(under) < sum(room) * 0.6, f"under the glass {under} is dimmed against the room {room}"
        rim = screen.get_at((x + 2, y + win.DISPLAY // 2))[:3]
        assert all(abs(int(c) - int(t)) <= 8 for c, t in zip(rim, room, strict=True)), "the shade fades to nothing at the rim"
        screen = _render_over(surface, _settled(), backdrop, frame=_frame_with_green_block())
        lit = screen.get_at((x + 110, y + 110))[:3]
        assert lit[1] > under[1] + 100, "the glass's green is added on top of the dimmed room"
    finally:
        backdrop.close()


def test_a_missing_clip_or_no_ffmpeg_fails_before_the_window_opens(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(SystemExit, match="no such file"):
        win.Backdrop(tmp_path / "nope.mp4").open()
    clip = tmp_path / "there.mp4"
    clip.write_bytes(b"")
    monkeypatch.setattr(win.shutil, "which", lambda _name: None)
    with pytest.raises(SystemExit, match="ffmpeg"):
        win.Backdrop(clip).open()


def test_a_still_image_is_a_backdrop_too(surface, tmp_path) -> None:  # type: ignore[no-untyped-def]
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not on PATH")
    path = tmp_path / "room.png"
    Image.new("RGB", (64, 36), (0x20, 0x40, 0xA0)).save(path)
    backdrop = win.Backdrop(path)
    try:
        screen = _render_over(surface, _settled(), backdrop, t=3.0)  # well past the one frame the file holds
        inside = screen.get_at((200, 300))[:3]
        assert all(abs(int(c) - int(t)) <= 8 for c, t in zip(inside, (0x20, 0x40, 0xA0), strict=True)), inside
        assert backdrop.frame_at(4.0) is not None, "the image holds for as long as the demo runs"
    finally:
        backdrop.close()


def test_in_a_take_the_caption_takes_the_subtitle_slot_on_a_plate_and_the_question_stays_on_the_glass_alone(surface, blue_clip) -> None:  # type: ignore[no-untyped-def]
    state = _settled()
    state.observe("guest", True)
    state.observe("cue", {"intent": "guest", "say": "", "display": {"question": "How many towels?", "level": "needed"}})
    band = (0, win.SUBTITLE_BOTTOM - 40, win.WIDTH, win.SUBTITLE_BOTTOM)
    backdrop = win.Backdrop(blue_clip)
    try:
        screen = _render_over(surface, state, backdrop)
        assert _has(screen, win.ASK_COLOURS["needed"], band), "no take: the question is mirrored"
        state.observe("line", "The AC is a bit too noisy, and can I have some more towels, please?")
        assert state.snapshot()["caption"].startswith("The AC")
        screen = _render_over(surface, state, backdrop)
        assert not _has(screen, win.ASK_COLOURS["needed"], band), "a take: the question is on the glass, once"
        assert _has(screen, win.INK, band), "the spoken line, as a caption"
        assert _has(screen, tuple(int(c * 176 / 255 + b * 79 / 255) for c, b in zip(win.GROUND, (0x20, 0x40, 0xA0), strict=True)), band, tol=10), "on a plate of the ground over the room"
        state.observe("guest", False)
        assert state.snapshot()["caption"] is None, "the session closed: no caption left hanging"
    finally:
        backdrop.close()


def test_the_glass_and_captions_are_drawn_only_between_ui_from_and_ui_until_and_the_take_goes_at_ui_from(surface, blue_clip) -> None:  # type: ignore[no-untyped-def]
    state = win.WindowState(ui_from=4.0, ui_until=9.0)
    state.observe("guest", True)
    state.observe("line", "Hi, I'm in room 1013.")
    x, y = win.DISPLAY_POS
    band = (0, win.SUBTITLE_BOTTOM - 40, win.WIDTH, win.SUBTITLE_BOTTOM)
    backdrop = win.Backdrop(blue_clip)
    try:
        screen, fonts = surface
        frame = _frame_with_green_block()
        lit = lambda: screen.get_at((x + 110, y + 110))[1] > 150  # noqa: E731  the block, added onto the film
        state.start.set()
        win.render(screen, frame, state, fonts, 10.0, backdrop)  # Start: the film's first frame; since = 0
        assert state.started_at == 10.0 and not state.take_go.is_set()
        assert not lit() and not _has(screen, win.INK, band), "before ui_from: the film alone"
        win.render(screen, frame, state, fonts, 14.5, backdrop)  # since = 4.5
        assert state.take_go.is_set(), "at ui_from the take begins"
        assert lit(), "the glass, at its place, no glide"
        assert _has(screen, win.INK, band), "and the caption"
        win.render(screen, frame, state, fonts, 19.5, backdrop)  # since = 9.5
        assert not lit() and not _has(screen, win.INK, band), "after ui_until: the film alone again"
    finally:
        backdrop.close()
