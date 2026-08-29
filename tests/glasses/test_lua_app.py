"""glasses/main.lua — the app that runs ON the glasses (and, unchanged, in the emulator).

USER-VISIBLE ARTIFACT: the 256×256 framebuffer after a message arrives over
Bluetooth, seen through the round optic (radius 120 px). Every test drives the
real Lua file inside the vendor's emulator through the vendor's own message
layer (`EmulatorBrilliantMsg` + `data.lua` + `sprite.lua`) — the same bytes a
phone would send a real Halo. Nothing here calls `frame.display` from Python.

The rules under test come from docs/research/glasses-display-rnd/README.md:
white copy only, nothing drawn outside the optic, a step name wraps instead
of running off the rim, the thumbnail sits in the detail view.
"""

from __future__ import annotations

import asyncio
import io
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from halo_emulator import EmulatorBrilliantMsg  # type: ignore[import-untyped]
from halo_emulator import HaloEmulator
from PIL import Image

import scripts.glasses_host as host

pytestmark = pytest.mark.unit

APP = Path(__file__).parents[2] / "glasses" / "main.lua"
CENTER, RADIUS = 128, 120


@asynccontextmanager
async def running_app() -> AsyncIterator[EmulatorBrilliantMsg]:
    emu = HaloEmulator(print_handler=None)
    frame = EmulatorBrilliantMsg(emu)
    await frame.connect()
    await frame.upload_stdlua_libs(lib_names=["data", "sprite"])
    await frame.upload_frame_app(str(APP))
    await frame.start_frame_app()
    try:
        yield frame
    finally:
        await frame.stop_frame_app()
        assert emu.get_error() is None, f"Lua raised: {emu.get_error()}"


async def settle(frame: EmulatorBrilliantMsg) -> Image.Image:
    await asyncio.sleep(0.25)  # the Lua loop polls every 50 ms; sprites take longer
    return frame.get_framebuffer().convert("RGB")


def lit(frame: Image.Image) -> list[tuple[int, int, tuple[int, int, int]]]:
    return [
        (x, y, frame.getpixel((x, y)))
        for y in range(256)
        for x in range(256)
        if frame.getpixel((x, y)) != (0, 0, 0)
    ]


def outside_optic(pixels: list[tuple[int, int, tuple[int, int, int]]]) -> list[tuple[int, int]]:
    return [(x, y) for x, y, _ in pixels if (x - CENTER) ** 2 + (y - CENTER) ** 2 > RADIUS**2]


def rows_lit(pixels: list[tuple[int, int, tuple[int, int, int]]], y0: int, y1: int) -> bool:
    return any(y0 <= y <= y1 for _, y, _ in pixels)


def test_the_app_touches_only_the_hardware_api_a_real_halo_has() -> None:
    """Portability guard: the same file must run on the glasses. Only the
    vendor's Lua API and the two vendor libraries, nothing emulator-only."""
    src = APP.read_text()
    used = set(re.findall(r"frame\.(\w+)", src))
    assert used <= {"display", "bluetooth", "button", "sleep", "HARDWARE_VERSION"}, used
    assert set(re.findall(r"require\('([\w.]+)'\)", src)) == {"data.min", "sprite.min"}


@pytest.mark.asyncio
async def test_ambient_view_draws_white_copy_and_the_icon_inside_the_optic() -> None:
    async with running_app() as frame:
        await frame.send_message(
            host.MSG_AMBIENT, host.pack_view("tick", "0712  3/7", "Wipe the mirror", "say done")
        )
        img = await settle(frame)
    pixels = lit(img)
    assert pixels, "nothing was drawn"
    assert not outside_optic(pixels), f"{len(outside_optic(pixels))} pixels outside the optic"
    colours = {c for _, _, c in pixels}
    assert (255, 255, 255) in colours, "copy must be white"
    assert any(g > 150 and r < 100 for r, g, _ in colours), "the tick icon is green"
    assert (128, 128, 128) not in colours, "grey vanishes over a white wall — never grey"
    assert rows_lit(pixels, 40, 64), "top line"
    assert rows_lit(pixels, 124, 148), "main line"
    assert rows_lit(pixels, 196, 224), "hint line"


@pytest.mark.asyncio
async def test_the_room_is_large_and_progress_is_a_ring_on_the_rim() -> None:
    """The room number is the largest thing on the glass (32 px for four
    digits), progress is a white arc from 12 o'clock clockwise — 3/7 lights the
    rim on the right and not on the left — and "3/7" sits at the foot."""
    async with running_app() as frame:
        await frame.send_message(host.MSG_AMBIENT, host.pack_view("none", "0712  3/7", "Wipe the mirror", ""))
        img = await settle(frame)
    pixels = lit(img)
    assert not outside_optic(pixels)
    unit_rows = sorted({y for x, y, c in pixels if c == (255, 255, 255) and 44 <= y < 80})
    assert unit_rows and unit_rows[-1] - unit_rows[0] >= 24, "four digits at 32 px stand taller than 24 px"
    rim = lambda x, y: (x - CENTER) ** 2 + (y - CENTER) ** 2 >= 113**2  # noqa: E731
    right = [(x, y) for x, y, _ in pixels if rim(x, y) and x > CENTER]
    left = [(x, y) for x, y, _ in pixels if rim(x, y) and x < CENTER - 8]
    assert right and not left, "3 of 7 is 154 degrees: the right rim is lit, the left is dark"
    assert rows_lit(pixels, 200, 220), "3/7 at the foot"

    async with running_app() as frame:
        await frame.send_message(host.MSG_AMBIENT, host.pack_view("none", "SU28-06  7/7", "All steps done", ""))
        img = await settle(frame)
    pixels = lit(img)
    assert not outside_optic(pixels), "a long room code shrinks to fit; nothing leaves the optic"
    assert [(x, y) for x, y, _ in pixels if rim(x, y) and x < CENTER - 8], "7 of 7 closes the ring"


@pytest.mark.asyncio
async def test_a_long_step_name_wraps_onto_more_lines_and_never_leaves_the_optic() -> None:
    async with running_app() as frame:
        await frame.send_message(
            host.MSG_AMBIENT,
            host.pack_view("none", "0712  1/7", "Strip the bed and remake with fresh linen", "say done"),
        )
        img = await settle(frame)
    pixels = lit(img)
    assert not outside_optic(pixels)
    assert rows_lit(pixels, 124, 148) and rows_lit(pixels, 148, 172) and rows_lit(pixels, 172, 196), (
        "41 characters need three lines at 16 px"
    )


@pytest.mark.asyncio
async def test_a_new_view_replaces_the_old_one() -> None:
    async with running_app() as frame:
        await frame.send_message(host.MSG_AMBIENT, host.pack_view("tick", "0712  3/7", "Wipe the mirror", "say done"))
        await settle(frame)
        await frame.send_message(host.MSG_AMBIENT, host.pack_view("alert", "0712", "Reported", "say done"))
        img = await settle(frame)
    colours = {c for _, _, c in lit(img)}
    assert not any(g > 150 and r < 100 for r, g, _ in colours), "the tick must be gone"
    assert any(r > 200 and 100 < g < 200 and b < 80 for r, g, b in colours), "the alert is amber"


@pytest.mark.asyncio
async def test_detail_view_shows_the_thumbnail_between_top_line_and_prompt() -> None:
    photo = Image.new("RGB", (400, 300), (30, 120, 200))
    buf = io.BytesIO()
    photo.save(buf, format="JPEG")
    async with running_app() as frame:
        await frame.send_message(host.MSG_DETAIL, host.pack_view("none", "0712", "Wipe the mirror", "pass / redo"))
        await frame.send_message(host.MSG_SPRITE, host.sprite_payload(buf.getvalue()))
        img = await settle(frame)
    pixels = lit(img)
    assert not outside_optic(pixels)
    r, g, b = img.getpixel((128, 124))
    assert b > 150 and r < 100, f"the thumbnail's blue must sit at the centre, got {(r, g, b)}"
    assert rows_lit(pixels, 40, 64), "top line above the thumbnail"
    assert rows_lit(pixels, 188, 212), "prompt below the thumbnail"


def _dot_lit(img: Image.Image) -> bool:
    return any(img.getpixel((x, 236)) != (0, 0, 0) for x in range(120, 137))


@pytest.mark.asyncio
async def test_state_dot_shows_listening_then_thinking_and_a_drawn_view_clears_it() -> None:
    async with running_app() as frame:
        await frame.send_message(host.MSG_AMBIENT, host.pack_view("none", "0712  3/7", "Wipe the mirror", "say done"))
        await settle(frame)
        assert not _dot_lit(frame.get_framebuffer().convert("RGB")), "no dot at rest"
        await frame.send_message(host.MSG_STATE, bytes([host.STATES["listening"]]))
        img = await settle(frame)
        assert _dot_lit(img), "listening shows the dot"
        assert img.getpixel((128, 236)) == (0, 0, 0), "listening is a hollow dot"
        await frame.send_message(host.MSG_STATE, bytes([host.STATES["thinking"]]))
        seen = set()
        for _ in range(8):
            await asyncio.sleep(0.15)
            seen.add(_dot_lit(frame.get_framebuffer().convert("RGB")))
        assert seen == {True, False}, "thinking pulses"
        await frame.send_message(host.MSG_AMBIENT, host.pack_view("tick", "0712  4/7", "Replace towels", "say done"))
        img = await settle(frame)
        assert not _dot_lit(img), "the cue's view clears the dot and stops the pulse"
        assert not outside_optic(lit(img))


@pytest.mark.asyncio
async def test_button_press_reaches_the_host_as_a_message() -> None:
    got: list[bytes] = []
    async with running_app() as frame:
        frame.register_data_response_handler(None, [host.MSG_BUTTON], got.append)
        frame.inject_button_single()
        await asyncio.sleep(0.2)
        frame.inject_button_long()
        await asyncio.sleep(0.2)
    assert got == [bytes([host.MSG_BUTTON, 1]), bytes([host.MSG_BUTTON, 3])]


@pytest.mark.asyncio
async def test_the_badge_is_a_small_amber_bell_over_the_view_and_clears_without_it() -> None:
    """A notification on the phone is a silent badge on the glass: amber,
    upper right, inside the optic, over the ambient view — the copy stays —
    and gone again on the off byte, the copy still there."""
    async with running_app() as frame:
        await frame.send_message(host.MSG_AMBIENT, host.pack_view("none", "1213  3/7", "Replace towels", ""))
        before = await settle(frame)
        await frame.send_message(host.MSG_BADGE, bytes([1]))
        on = await settle(frame)
        await frame.send_message(host.MSG_BADGE, bytes([0]))
        off = await settle(frame)
    def amber(px: list[tuple[int, int, tuple[int, int, int]]]) -> list[tuple[int, int, tuple[int, int, int]]]:
        return [(x, y, c) for x, y, c in px if c[0] > 200 and 100 < c[1] < 200 and c[2] < 80]

    copy_before = {(x, y) for x, y, c in lit(before) if c == (255, 255, 255)}
    mark = amber(lit(on))
    assert mark and not outside_optic(mark), "amber, inside the optic"
    assert all(186 <= x <= 206 and 85 <= y <= 108 for x, y, _c in mark), "small, upper right: a 20 px bell"
    assert copy_before <= {(x, y) for x, y, c in lit(on) if c == (255, 255, 255)}, "the view's copy is not pushed off"
    assert not amber(lit(off)), "off: the mark is gone"
    assert copy_before <= {(x, y) for x, y, c in lit(off) if c == (255, 255, 255)}, "and the copy still stands"


@pytest.mark.asyncio
async def test_the_guest_view_draws_the_question_in_its_colour_inside_the_optic() -> None:
    """0x0F: the room large, the name under it, the requests in the middle, the
    question at the foot in red (needed) or orange (optional) — and nothing
    outside the round optic. White copy everywhere else."""
    async with running_app() as frame:
        red = host.GuestView("red", "1013", "Mark Robelo", "AC too noisy; extra towels", "How many towels?")
        await frame.send_message(host.MSG_GUEST, host.pack_guest(red))
        img = await settle(frame)
        pixels = lit(img)
        assert pixels and not outside_optic(pixels)
        assert rows_lit(pixels, 44, 70), "the room"
        assert rows_lit(pixels, 78, 94), "the name"
        assert rows_lit(pixels, 96, 112), "the requests"
        ask = {c for _x, y, c in pixels if 160 <= y <= 196}
        assert ask and all(c == (0xEF, 0x44, 0x44) for c in ask), f"the question is red and only red: {ask}"
        above = {c for _x, y, c in pixels if y < 156}
        assert above <= {(255, 255, 255)}, f"copy above the question is white: {above}"

        orange = host.GuestView("orange", "1013", "Mark Robelo", "4 towels", "When to deliver?")
        await frame.send_message(host.MSG_GUEST, host.pack_guest(orange))
        pixels = lit(await settle(frame))
        ask = {c for _x, y, c in pixels if 160 <= y <= 196}
        assert ask == {(0xF9, 0x73, 0x16)}

        listening = host.GuestView("white", "", "", "Listening..", "")
        await frame.send_message(host.MSG_GUEST, host.pack_guest(listening))
        pixels = lit(await settle(frame))
        assert pixels and {c for *_xy, c in pixels} == {(255, 255, 255)}
        assert not rows_lit(pixels, 160, 196), "no question, nothing in the question rows"

        long_name = host.GuestView("white", "1013", "Christopher Andersson-Whitfield", "Listening..", "")
        await frame.send_message(host.MSG_GUEST, host.pack_guest(long_name))
        pixels = lit(await settle(frame))
        assert pixels and not outside_optic(pixels), "a long name ends in '..' inside the optic, never off the rim"


def _capacity(y: int, inner: int = 110, font: int = 16) -> int:
    """`main.lua` chord()/capacity(): glyphs a 16 px row at `y` holds inside the ring."""
    import math

    dy = max(abs(y - CENTER), abs(y + font - CENTER))
    return 0 if dy >= inner else int(2 * math.sqrt(inner * inner - dy * dy)) // font


def _wrap(text: str, rows: list[int]) -> list[str]:
    """`main.lua` wrap(): greedy, one word too long is cut, a remainder ends the last row with '..'."""
    words, lines, i = text.split(), [], 0
    for y in rows:
        cap, line = _capacity(y), ""
        while i < len(words):
            candidate = words[i] if not line else f"{line} {words[i]}"
            if len(candidate) > cap:
                if not line:
                    line, words[i] = words[i][:cap], words[i][cap:]
                break
            line, i = candidate, i + 1
        lines.append(line)
        if i >= len(words):
            break
    if i < len(words) and lines:
        lines[-1] = lines[-1][: max(0, _capacity(rows[len(lines) - 1]) - 2)] + ".."
    return lines


def test_every_question_the_backend_asks_fits_its_two_rows_whole() -> None:
    """The question rows (160, 180) hold 12 and 10 glyphs. The copy the backend
    writes must fit them without '..' — 'Confirm number of towels' at the foot
    (188, 208) drew as 'Confirm' / 'numb..' (2026-08-29)."""
    rows = [160, 180]
    assert [_capacity(y) for y in rows] == [12, 10]
    for question in ("How many towels?", "How many items?", "How many pillows?", "When to deliver?", "Which room?"):
        lines = _wrap(question, rows)
        assert "".join(lines).replace(" ", "") == question.replace(" ", ""), (question, lines)
        assert all(not ln.endswith("..") for ln in lines), (question, lines)
    assert _wrap("Confirm number of towels", [188, 208]) == ["Confirm", "numb.."], "the fault the rows were moved for"
    assert _capacity(78) == 12, "the name row"
    for name in ("Mark Robelo", "Amira Hassan", "Priya Sharma", "Wei Zhang", "Hana Sato"):
        assert _wrap(name, [78]) == [name], name
    assert _wrap("Christopher Andersson", [78]) == ["Christophe.."], "longer ends in '..', never off the rim"
