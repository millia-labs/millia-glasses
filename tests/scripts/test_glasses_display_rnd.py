"""scripts/glasses_display_rnd.py — the Halo 256×256 round-display R&D.

USER-VISIBLE ARTIFACT: the framebuffer the vendor emulator renders — the same
Lua VM and ``frame.display`` calls the glasses run — seen through the round
optic (radius 120 px). The first render of this script cut every edge line
because it laid out to the 256-px square; these tests hold the fix: nothing
drawn may fall outside the circle, and a line that would is refused up front.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PIL import Image

import scripts.glasses_display_rnd as rnd

pytestmark = pytest.mark.unit


def _rgb(img: Image.Image, xy: tuple[int, int]) -> tuple[int, int, int]:
    px = img.convert("RGB").getpixel(xy)
    assert isinstance(px, tuple)
    r, g, b = px
    return int(r), int(g), int(b)


def _lit_pixels(frame: Image.Image) -> list[tuple[int, int]]:
    rgb = frame.convert("RGB")
    return [
        (x, y)
        for y in range(rnd.SIZE)
        for x in range(rnd.SIZE)
        if rgb.getpixel((x, y)) != (0, 0, 0)
    ]


def _inside_circle(x: int, y: int) -> bool:
    return (x - rnd.CENTER) ** 2 + (y - rnd.CENTER) ** 2 <= rnd.RADIUS**2


def test_lua_bytes_escapes_every_byte_as_hex() -> None:
    assert rnd.lua_bytes(b"\x00\xab\xff") == '"\\x00\\xab\\xff"'
    assert rnd.lua_bytes(b"") == '""'


def test_ble_chunk_count_matches_the_figures_in_the_readme() -> None:
    # README + CONTEXT.md quote these three numbers; they are derived here, not typed.
    assert rnd.ble_chunk_count(rnd.SIZE * rnd.SIZE * 3) == 384  # RGB888 full frame
    assert rnd.ble_chunk_count(rnd.SIZE * rnd.SIZE // 2) == 64  # 4-bit full frame
    assert rnd.ble_chunk_count(rnd.THUMB_SIDE * rnd.THUMB_SIDE // 2) == 13  # 4-bit thumbnail
    assert rnd.ble_chunk_count(0) == 0
    assert rnd.ble_chunk_count(rnd.BLE_CHUNK + 1) == 2


def test_text_width_is_the_dogica_advance_doubled() -> None:
    one = rnd.text_width("M")
    assert one == 16, "8-px Dogica at FONT_SIZE 16 advances 16 px per character"
    assert rnd.text_width("MM") == 2 * one
    assert rnd.text_width("") == 0


def test_chord_is_full_width_at_centre_and_zero_past_the_rim() -> None:
    assert rnd.chord(rnd.CENTER - 4, rnd.CENTER + 4) == 239
    assert rnd.chord(0, 8) == 0
    # A top line at y=60 (size 16) holds 12 characters, not 16.
    assert rnd.chord(60, 76) // rnd.FONT_SIZE == 12


def test_centered_text_refuses_a_line_the_round_crop_would_cut() -> None:
    s = rnd.Scene()
    with pytest.raises(ValueError, match="circle shows only"):
        rnd.centered_text(s, "SU13A-06 3/7", 20, rnd.WHITE)


def test_load_image_returns_rgb_and_closes_the_file() -> None:
    img = rnd.load_image(rnd.SAMPLE_PHOTO)
    assert img.mode == "RGB"
    assert getattr(img, "fp", None) is None, "the file handle must be closed"


def test_palette4_payload_packs_two_pixels_per_byte_and_never_uses_index_zero() -> None:
    photo = rnd.square_crop(rnd.load_image(rnd.SAMPLE_PHOTO), rnd.THUMB_SIDE)
    pixels, palette = rnd.palette4_payload(photo)
    assert len(pixels) == rnd.THUMB_SIDE * rnd.THUMB_SIDE // 2
    assert len(palette) == 16 * 3
    assert palette[:3] == b"\x00\x00\x00"
    nibbles = [n for b in pixels for n in ((b >> 4) & 0xF, b & 0xF)]
    assert 0 not in nibbles, "index 0 is transparent on hardware; a photo must not use it"


def test_round_disc_keeps_the_background_outside_the_optic() -> None:
    frame = Image.new("RGB", (rnd.SIZE, rnd.SIZE), (255, 255, 255))
    disc = rnd.round_disc(frame, 100, inset=10, background=(1, 2, 3))
    assert disc.size == (100, 100)
    assert _rgb(disc, (50, 50)) == (255, 255, 255)
    assert _rgb(disc, (0, 0)) == (1, 2, 3)
    assert _rgb(disc, (50, 5)) == (1, 2, 3), "the inset band is background"


@pytest.mark.parametrize(
    "draw",
    [rnd.draw_ambient, rnd.draw_ambient_report, rnd.draw_detail_thumb],
    ids=["ambient", "report", "detail"],
)
def test_every_scene_draws_only_inside_the_round_optic(draw) -> None:  # type: ignore[no-untyped-def]
    s = rnd.Scene()
    draw(s)
    lit = _lit_pixels(s.frame())
    assert lit, "the scene drew nothing"
    outside = [p for p in lit if not _inside_circle(*p)]
    assert not outside, f"{len(outside)} lit pixels fall outside the optic, e.g. {outside[:5]}"


def test_icons_are_a_coloured_disc_with_a_black_glyph() -> None:
    for icon, colour, rgb in (
        (rnd.check_icon, rnd.GREEN, (0x22, 0xC5, 0x5E)),
        (rnd.report_icon, rnd.AMBER, (0xF5, 0x9E, 0x0B)),
    ):
        s = rnd.Scene()
        s.lua("frame.display.clear(0x000000)")
        icon(s, rnd.CENTER, rnd.ICON_CY, rnd.ICON_R, colour)
        frame = s.frame()
        # The rim of the disc is the icon colour, and the glyph cuts black pixels into it.
        assert _rgb(frame, (rnd.CENTER + rnd.ICON_R - 3, rnd.ICON_CY)) == rgb
        inner = rnd.ICON_R - 4
        black_inside = [
            (x, y)
            for y in range(rnd.ICON_CY - inner, rnd.ICON_CY + inner)
            for x in range(rnd.CENTER - inner, rnd.CENTER + inner)
            if (x - rnd.CENTER) ** 2 + (y - rnd.ICON_CY) ** 2 <= inner**2
            and _rgb(frame, (x, y)) == (0, 0, 0)
        ]
        assert len(black_inside) > 50, f"{icon.__name__} drew no glyph on the disc"


def test_detail_view_shows_the_photo_thumbnail() -> None:
    s = rnd.Scene()
    rnd.draw_detail_thumb(s)
    frame = s.frame()
    # The thumbnail sits at x=73..184, y=72..183; its centre is a lit photo pixel.
    assert _rgb(frame, (rnd.CENTER, 128)) != (0, 0, 0)
    # The band above the thumbnail carries only the grey unit line.
    assert _rgb(frame, (rnd.CENTER, 40)) == (0, 0, 0)


def test_main_writes_the_eight_pngs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rnd, "OUT_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["glasses_display_rnd.py"])
    rnd.main()
    names = sorted(p.name for p in tmp_path.glob("*.png"))
    assert names == [
        "01_photo_rgb888_256.png",
        "02_photo_4bit_256.png",
        "03_detail_thumb_prompt.png",
        "04_ambient_line_icon.png",
        "05_ambient_report_filed.png",
        "06_first_person_mockup.png",
        "07_glasses_front.png",
        "08_pov_through_glasses.png",
    ]
    for name in names[:5]:
        with Image.open(tmp_path / name) as png:
            assert png.size == (rnd.SIZE * rnd.DECK_SCALE, rnd.SIZE * rnd.DECK_SCALE)


def test_main_with_window_opens_it_for_the_given_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_window(emulator: object, stop: threading.Event) -> None:
        seen["emulator"] = emulator
        seen["stopped_on_entry"] = stop.is_set()
        # The user closes the window at once; the timer must not keep the process alive.

    monkeypatch.setattr(rnd, "_pygame_window", fake_window)
    rnd.open_window(60)
    assert seen["stopped_on_entry"] is False
    assert hasattr(seen["emulator"], "get_framebuffer"), "the vendor loop gets the emulator"
    live_timers = [t for t in threading.enumerate() if isinstance(t, threading.Timer) and t.is_alive()]
    assert not live_timers, "open_window must cancel its timer when the window closes early"


def test_glasses_front_puts_the_display_in_the_wearers_right_lens_only() -> None:
    s = rnd.Scene()
    rnd.draw_ambient(s)
    out = rnd.glasses_front(s.frame())
    assert out.size == (1200, 560)
    # The green tick lights the wearer's right lens (viewer's left)...
    _r, g, _b = _rgb(out, (345, 233))
    assert g > 120, "the green disc must show in the viewer's-left lens"
    # ...and the other lens is plain lens fill.
    assert _rgb(out, (855, 233)) == (60, 70, 80)


def test_first_person_mockup_lets_the_room_show_through_black_pixels() -> None:
    s = rnd.Scene()
    rnd.draw_ambient(s)
    room = Image.new("RGB", (1600, 1200), (120, 90, 60))
    out = rnd.first_person_mockup(s.frame(), room)
    assert out.size == (1600, 900)
    # The display corner is black on the framebuffer, so the room colour survives there.
    side = int(1600 * rnd.MOCKUP_WINDOW_FRACTION)
    x0, y0 = 1600 - side - 160, 900 // 8
    assert _rgb(out, (x0 + 2, y0 + 2)) == (120, 90, 60)
    # The green tick at the display centre adds light on top of the room.
    # Sample the upper-left of the disc, clear of the black tick polygon.
    cx, cy = x0 + side // 2, y0 + int(side * rnd.ICON_CY / rnd.SIZE)
    r, g, _b = _rgb(out, (cx - int(side * 0.04), cy - int(side * 0.04)))
    assert g > 90 and g > r, "expected the green disc to light the room pixel"
    # The caption strip is the last thing drawn and is black under white text.
    assert _rgb(out, (0, 899)) == (0, 0, 0)


def test_pov_draws_rims_and_one_caption_over_the_mockup() -> None:
    s = rnd.Scene()
    rnd.draw_ambient(s)
    room = Image.new("RGB", (1600, 1200), (120, 90, 60))
    out = rnd.pov_through_glasses(s.frame(), room)
    assert out.size == (1600, 900)
    assert _rgb(out, (800, 300)) == rnd.RIM, "the bridge sits at w/2, h/3"
    assert _rgb(out, (0, 899)) == (0, 0, 0), "the caption strip is drawn last"
