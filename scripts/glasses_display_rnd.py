"""R&D for the Halo 256x256 round display (Trello card 155, handoff 2026-08-26).

Answers one question: can the glass show a photo, or only text?

Renders eight pictures into ``docs/research/glasses-display-rnd/``:

- ``01``-``05`` go through the vendor emulator (``halo-emulator``, the same
  Lua 5.4 VM + ``frame.display`` stubs the glasses run) and show the
  framebuffer behind the round crop the real optic applies.
- ``06``-``08`` are Pillow mockups of what the wearer sees: the emulator's
  framebuffer screen-blended into a room photo and a schematic glasses frame.

Also prints the payload size and BLE chunk count for each bitmap format,
because the limit is transport, not the panel.

    uv run python scripts/glasses_display_rnd.py                # write PNGs
    uv run python scripts/glasses_display_rnd.py --window 10   # also open the
                                                               # emulator window
                                                               # for 10 s
"""

from __future__ import annotations

import argparse
import threading
from pathlib import Path

from halo_emulator import HaloEmulator  # type: ignore[import-untyped]
from halo_emulator.cli import _pygame_window  # type: ignore[import-untyped]
from halo_emulator.gfx_fonts import FONT_LIST  # type: ignore[import-untyped]
from PIL import Image
from PIL import ImageChops
from PIL import ImageDraw
from PIL import ImageFont

REPO = Path(__file__).resolve().parent.parent
SAMPLE_PHOTO = REPO / "assets/sample-room.jpg"  # a unit photo from the monorepo's portal fixtures, downscaled
OUT_DIR = REPO / "docs/research/glasses-display-rnd"

SIZE = 256
CENTER = SIZE // 2
OPTIC_INSET = 8  # the vendor's window mask is inset 8 px (halo_emulator/cli.py)
RADIUS = CENTER - OPTIC_INSET  # the round optic: 120 px
BLE_CHUNK = 512  # bytes per BLE write on Halo (MTU 512, research doc line 335)

FONT_SIZE = 16  # Dogica 8 px doubled: the smallest size that reads at arm's length
FONT_MULT = FONT_SIZE // 8
THUMB_SIDE = 112  # the detail-view thumbnail: 13 BLE chunks in 16 colours
ICON_CY = 122  # the ambient icon sits on the centre band
ICON_R = 26
DECK_SCALE = 2  # framebuffer PNGs are saved at 2x for the deck

# One brand colour, one white, one grey — enough for a HUD.
WHITE = 0xFFFFFF
GREY = 0x808080
GREEN = 0x22C55E
AMBER = 0xF59E0B
BLACK_RGB = (0, 0, 0)


def lua_bytes(data: bytes) -> str:
    """Encode bytes as a Lua 5.4 string literal (``\\xNN`` escapes)."""
    return '"' + "".join(f"\\x{b:02x}" for b in data) + '"'


def ble_chunk_count(n_bytes: int) -> int:
    """How many 512-byte BLE writes a payload of ``n_bytes`` costs."""
    return -(-n_bytes // BLE_CHUNK)


def load_image(path: Path) -> Image.Image:
    """Open a file, decode it to RGB, and close the handle."""
    with Image.open(path) as f:
        img: Image.Image = f.convert("RGB")
    return img


def square_crop(img: Image.Image, side: int) -> Image.Image:
    w, h = img.size
    s = min(w, h)
    box = ((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2)
    return img.crop(box).resize((side, side), Image.Resampling.LANCZOS).convert("RGB")


def rgb888_payload(img: Image.Image) -> bytes:
    return img.tobytes()


def palette4_payload(img: Image.Image) -> tuple[bytes, bytes]:
    """Quantise to 15 colours (index 0 stays VOID/transparent), pack 2 px/byte.

    Returns ``(pixel_data, palette_data)`` in the shape ``frame.display.bitmap``
    takes for format 16 with ``opts.palette_data``.
    """
    q = img.quantize(colors=15, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
    pal = (q.getpalette() or [])[: 15 * 3]
    # Shift every index up by one so 0 is never used (0 = transparent on hardware).
    idx = bytes(p + 1 for p in q.tobytes())
    packed = bytearray()
    for i in range(0, len(idx), 2):
        packed.append((idx[i] << 4) | idx[i + 1])
    palette_data = bytes([0, 0, 0]) + bytes(pal)
    return bytes(packed), palette_data


def round_disc(
    frame: Image.Image,
    side: int,
    inset: int = 0,
    background: tuple[int, int, int] = BLACK_RGB,
    resample: Image.Resampling = Image.Resampling.LANCZOS,
) -> Image.Image:
    """The framebuffer resized to ``side`` px, ``background`` outside the round optic."""
    disp = frame.convert("RGB").resize((side, side), resample)
    mask = Image.new("L", disp.size, 0)
    ImageDraw.Draw(mask).ellipse([inset, inset, side - 1 - inset, side - 1 - inset], fill=255)
    return Image.composite(disp, Image.new("RGB", disp.size, background), mask)


def round_view(frame: Image.Image) -> Image.Image:
    """What the deck shows: the framebuffer behind the vendor's round window, at 2x."""
    return round_disc(
        frame,
        SIZE * DECK_SCALE,
        inset=OPTIC_INSET * DECK_SCALE,
        background=(40, 40, 40),
        resample=Image.Resampling.NEAREST,
    )


class Scene:
    """One emulator session: run Lua, read the framebuffer, save the deck PNG."""

    def __init__(self) -> None:
        self.emu = HaloEmulator(print_handler=None)
        self.emu.connect()

    def lua(self, code: str) -> None:
        self.emu.execute_lua(code)

    def frame(self) -> Image.Image:
        frame: Image.Image = self.emu.get_framebuffer()
        return frame

    def save(self, name: str) -> None:
        round_view(self.frame()).save(OUT_DIR / f"{name}.png")
        print(f"wrote {name}.png")


def text_width(txt: str) -> int:
    """Width in px of ``txt`` in the vendor's Dogica font at ``FONT_SIZE``."""
    font = FONT_LIST[0][1]
    return int(sum(font.glyphs[ord(c) - font.first].x_advance for c in txt)) * FONT_MULT


def chord(y_top: int, y_bottom: int) -> int:
    """Visible width of the round display across the band y_top..y_bottom."""
    dy = max(abs(y_top - CENTER), abs(y_bottom - CENTER))
    if dy >= RADIUS:
        return 0
    return int(2 * (RADIUS**2 - dy**2) ** 0.5)


def centered_text(s: Scene, txt: str, y: int, color: int, bold: bool = False) -> None:
    """Draw one centred line, and refuse a line the round crop would cut."""
    width = text_width(txt)
    visible = chord(y, y + FONT_SIZE)
    if width > visible:
        raise ValueError(
            f"{txt!r} at y={y} size={FONT_SIZE} is {width} px wide, "
            f"but the circle shows only {visible} px there "
            f"({visible // FONT_SIZE} chars)"
        )
    x = (SIZE - width) // 2 + 1
    s.lua(f"frame.display.set_font({1 if bold else 0}, {FONT_SIZE}, 1)")
    s.lua(f'frame.display.text("{txt}", {x}, {y}, {color})')


def disc(s: Scene, cx: int, cy: int, r: int, color: int) -> None:
    s.lua(f"frame.display.circle({cx}, {cy}, {r}, {color}, true)")


def check_icon(s: Scene, cx: int, cy: int, r: int, color: int) -> None:
    """A coloured disc with a black tick."""
    disc(s, cx, cy, r, color)
    pts = [
        cx - r // 2, cy,
        cx - r // 2 + 4, cy - 4,
        cx - r // 8, cy + r // 3,
        cx + r // 2, cy - r // 2,
        cx + r // 2 + 4, cy - r // 2 + 4,
        cx - r // 8, cy + r // 3 + 8,
    ]
    s.lua(f"frame.display.polygon({{{', '.join(map(str, pts))}}}, 0x000000)")


def report_icon(s: Scene, cx: int, cy: int, r: int, color: int) -> None:
    """A coloured disc with a black exclamation mark."""
    disc(s, cx, cy, r, color)
    bar_w = 7
    s.lua(f"frame.display.rect({cx - bar_w // 2}, {cy - 18}, {bar_w}, 22, 0x000000, true)")
    s.lua(f"frame.display.rect({cx - bar_w // 2}, {cy + 9}, {bar_w}, {bar_w}, 0x000000, true)")


def scene_photo_rgb888(photo: Image.Image) -> None:
    s = Scene()
    data = rgb888_payload(photo)
    print(f"RGB888 256x256: {len(data):,} bytes = {ble_chunk_count(len(data))} BLE chunks")
    s.lua(f"frame.display.bitmap(1, 1, {SIZE}, 0, 0, {lua_bytes(data)})")
    s.save("01_photo_rgb888_256")


def scene_photo_4bit(photo: Image.Image) -> None:
    s = Scene()
    pixels, pal = palette4_payload(photo)
    print(f"4-bit  256x256: {len(pixels):,} bytes = {ble_chunk_count(len(pixels))} BLE chunks")
    s.lua(
        f"frame.display.bitmap(1, 1, {SIZE}, 16, 0, {lua_bytes(pixels)}, "
        f"{{palette_data = {lua_bytes(pal)}}})"
    )
    s.save("02_photo_4bit_256")


def draw_detail_thumb(s: Scene) -> None:
    """The detail view: the unit line, a 4-bit thumbnail, and the verdict prompt."""
    thumb = square_crop(load_image(SAMPLE_PHOTO), THUMB_SIDE)
    pixels, pal = palette4_payload(thumb)
    print(
        f"4-bit  {THUMB_SIDE}x{THUMB_SIDE}: {len(pixels):,} bytes = "
        f"{ble_chunk_count(len(pixels))} BLE chunks"
    )
    s.lua("frame.display.clear(0x000000)")
    centered_text(s, "SU13A-06", 48, GREY)
    x = (SIZE - THUMB_SIDE) // 2 + 1
    s.lua(
        f"frame.display.bitmap({x}, 72, {THUMB_SIDE}, 16, 0, {lua_bytes(pixels)}, "
        f"{{palette_data = {lua_bytes(pal)}}})"
    )
    centered_text(s, "pass / redo", 192, WHITE, bold=True)


def scene_photo_thumb_with_prompt() -> None:
    s = Scene()
    draw_detail_thumb(s)
    s.save("03_detail_thumb_prompt")


def draw_ambient(s: Scene) -> None:
    """The ambient view: one line of text and one icon. Nothing else."""
    s.lua("frame.display.clear(0x000000)")
    centered_text(s, "SU13A-06 3/7", 60, GREY)
    check_icon(s, CENTER, ICON_CY, ICON_R, GREEN)
    centered_text(s, "Wipe mirror", 160, WHITE, bold=True)
    centered_text(s, "say done", 188, GREY)


def scene_ambient() -> None:
    s = Scene()
    draw_ambient(s)
    s.save("04_ambient_line_icon")


def draw_ambient_report(s: Scene) -> None:
    """Ambient after 'Millia, report': the task went to the dashboard."""
    s.lua("frame.display.clear(0x000000)")
    centered_text(s, "SU13A-06", 60, GREY)
    report_icon(s, CENTER, ICON_CY, ICON_R, AMBER)
    # Not "Task filed": in an 8-px pixel font it reads as "Task failed" (Ryan, 2026-08-27).
    centered_text(s, "Reported", 160, WHITE, bold=True)
    centered_text(s, "bedside lamp", 184, GREY)


def scene_ambient_report() -> None:
    s = Scene()
    draw_ambient_report(s)
    s.save("05_ambient_report_filed")


# What the wearer sees is NOT the framebuffer: it is a small see-through window in
# one eye, floating over the room. Halo's field of view is not published on the
# vendor pages fetched 2026-08-27; Frame's was ~20 deg. This mockup assumes the
# window spans 22 % of a ~90 deg first-person frame. Assumed, not measured.
MOCKUP_WINDOW_FRACTION = 0.22
MOCKUP_BACKGROUND = REPO / "assets/mockup-room.jpg"  # a building photo from the monorepo's guest portal
MOCKUP_ASPECT = 16 / 9  # a first-person frame, landscape
MOCKUP_WINDOW_RIGHT_MARGIN = 10  # window sits 1/10 of the width in from the right edge…
MOCKUP_WINDOW_TOP_MARGIN = 8  # …and 1/8 of the height down: a top-mounted monocular optic
MOCKUP_CAPTION = "MOCKUP: window size assumed, field of view unverified"
RIM = (30, 30, 30)


def _screen_onto(bg: Image.Image, disc_img: Image.Image, x0: int, y0: int) -> None:
    """Screen-blend a disc onto ``bg`` in place: black pixels emit nothing on an OLED."""
    region = bg.crop((x0, y0, x0 + disc_img.width, y0 + disc_img.height))
    bg.paste(ImageChops.screen(region, disc_img), (x0, y0))


def _label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], txt: str, fill: tuple[int, int, int]) -> None:
    draw.text(xy, txt, fill=fill, font=ImageFont.load_default(size=26))


def _caption(img: Image.Image, txt: str) -> None:
    """A black strip along the bottom edge with white text, drawn last."""
    w, h = img.size
    d = ImageDraw.Draw(img)
    d.rectangle((0, h - 30, w, h), fill=BLACK_RGB)
    d.text((12, h - 26), txt, fill=(255, 255, 255), font=ImageFont.load_default(size=18))


def window_over_room(frame: Image.Image, background: Image.Image) -> Image.Image:
    """The round display screen-blended over a first-person photo, upper right.

    Only lit pixels appear: the room shows through everything black.
    """
    bg = background.convert("RGB")
    w, h = bg.size
    bg = bg.crop((0, 0, w, min(h, int(w / MOCKUP_ASPECT))))
    side = int(bg.width * MOCKUP_WINDOW_FRACTION)
    x0 = bg.width - side - bg.width // MOCKUP_WINDOW_RIGHT_MARGIN
    y0 = bg.height // MOCKUP_WINDOW_TOP_MARGIN
    _screen_onto(bg, round_disc(frame, side), x0, y0)
    return bg


def first_person_mockup(frame: Image.Image, background: Image.Image) -> Image.Image:
    """``window_over_room`` with the mockup caption."""
    bg = window_over_room(frame, background)
    _caption(bg, f"{MOCKUP_CAPTION} ({MOCKUP_WINDOW_FRACTION:.0%} of view)")
    return bg


def scene_first_person_mockup() -> None:
    s = Scene()
    draw_ambient(s)
    first_person_mockup(s.frame(), load_image(MOCKUP_BACKGROUND)).save(OUT_DIR / "06_first_person_mockup.png")
    print("wrote 06_first_person_mockup.png")


def glasses_front(frame: Image.Image) -> Image.Image:
    """A pair of glasses seen from the front, the display in the wearer's RIGHT lens.

    Seen from the front the wearer's right eye is on the viewer's left. Drawn,
    not a photo of Halo: the frame shape is schematic, the display is real.
    """
    w, h = 1200, 560
    img = Image.new("RGB", (w, h), (236, 236, 236))
    d = ImageDraw.Draw(img)
    lens_fill = (60, 70, 80)
    left = (150, 140, 540, 400)  # wearer's right eye
    right = (660, 140, 1050, 400)  # wearer's left eye
    for box in (left, right):
        d.rounded_rectangle(box, radius=70, fill=lens_fill, outline=RIM, width=12)
    d.line([(540, 230), (660, 230)], fill=RIM, width=14)  # bridge
    d.line([(150, 200), (40, 190), (30, 330)], fill=RIM, width=12)  # temples
    d.line([(1050, 200), (1160, 190), (1170, 330)], fill=RIM, width=12)
    side = 130
    x0, y0 = left[0] + (left[2] - left[0] - side) // 2, left[1] + 40
    _screen_onto(img, round_disc(frame, side), x0, y0)
    d = ImageDraw.Draw(img)
    d.line([(x0 + side // 2, y0 + side + 8), (x0 + side // 2, 470)], fill=RIM, width=3)
    _label(d, (x0 - 120, 480), "256x256 round display, wearer's right eye only", RIM)
    _label(d, (20, 20), "Halo (schematic frame, real display output)", (90, 90, 90))
    return img


def pov_through_glasses(frame: Image.Image, background: Image.Image) -> Image.Image:
    """First-person view with the lens rims in the periphery, display in the right lens."""
    bg = window_over_room(frame, background)
    w, h = bg.size
    d = ImageDraw.Draw(bg)
    # Two lens rims at the edge of vision, bridge in the middle, wearer's right on the right.
    d.rounded_rectangle((-60, -40, w // 2 - 16, h + 40), radius=220, outline=RIM, width=12)
    d.rounded_rectangle((w // 2 + 16, -40, w + 60, h + 40), radius=220, outline=RIM, width=12)
    d.line([(w // 2 - 16, h // 3), (w // 2 + 16, h // 3)], fill=RIM, width=12)
    _caption(bg, f"wearer's view; the right lens has the display. {MOCKUP_CAPTION}")
    return bg


def scene_glasses_frames() -> None:
    s = Scene()
    draw_ambient(s)
    frame = s.frame()
    glasses_front(frame).save(OUT_DIR / "07_glasses_front.png")
    print("wrote 07_glasses_front.png")
    pov_through_glasses(frame, load_image(MOCKUP_BACKGROUND)).save(OUT_DIR / "08_pov_through_glasses.png")
    print("wrote 08_pov_through_glasses.png")


def open_window(seconds: float) -> None:
    """Prove the vendor window opens on this machine, using the vendor's own loop.

    The window closes after ``seconds``, or sooner if the user closes it; the
    timer is cancelled either way so the process does not linger.
    """
    s = Scene()
    draw_ambient(s)
    stop = threading.Event()
    timer = threading.Timer(seconds, stop.set)
    timer.daemon = True
    timer.start()
    try:
        _pygame_window(s.emu, stop)
    finally:
        timer.cancel()
    print(f"window opened and stayed up for {seconds:.0f} s")


def main() -> None:
    ap = argparse.ArgumentParser(description="Render the Halo 256x256 display R&D pictures.")
    ap.add_argument("--window", type=float, default=0, metavar="SECONDS",
                    help="also open the emulator window for this many seconds")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    photo = square_crop(load_image(SAMPLE_PHOTO), SIZE)
    print(f"sample photo: {SAMPLE_PHOTO.relative_to(REPO)}")
    print(f"Dogica advance at size {FONT_SIZE}: {text_width('M')} px -> "
          f"{SIZE // text_width('M')} chars across the full width")

    scene_photo_rgb888(photo)
    scene_photo_4bit(photo)
    scene_photo_thumb_with_prompt()
    scene_ambient()
    scene_ambient_report()
    scene_first_person_mockup()
    scene_glasses_frames()

    if args.window:
        open_window(args.window)


if __name__ == "__main__":
    main()
