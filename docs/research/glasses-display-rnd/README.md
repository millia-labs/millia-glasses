# Halo 256×256 display R&D — ruling (2026-08-27)

Trello card 155, checklist "R&D — the 256×256 display". Answers Jason's worry from
2026-08-26: *"256×256 sounds great on paper, but I am worried that it's pixel, so we can only
display text."*

Every image here comes from `scripts/glasses_display_rnd.py`. `01`–`05` are the framebuffer
of the vendor's `halo-emulator` 2.0.1 — the same Lua 5.4 VM and `frame.display` calls the
glasses run — shown behind the round crop the optic applies (radius 120 px, as the vendor's
own window draws it). `06`–`08` are Pillow mockups that take that framebuffer and blend it into
a room photo and a schematic glasses frame; the display content in them is real, the
surroundings are drawn. Re-run the script to regenerate.

## Ruling: pictures on the glass = **yes, as a thumbnail inside a text frame**

| Scene | What it proves | Payload over BLE |
|---|---|---|
| `01_photo_rgb888_256.png` | A full-frame photo in true colour (`bitmap` format 0). The panel is full colour, not "pixel text". | 196,608 B = **384 chunks** of 512 B |
| `02_photo_4bit_256.png` | The same photo in 16 colours (format 16 + custom palette, dithered). Still recognisable. | 32,768 B = **64 chunks** |
| `03_detail_thumb_prompt.png` | **The detail view we will ship**: unit code, a 112-px 16-colour thumbnail, the verdict prompt. | 6,272 B = **13 chunks** |
| `04_ambient_line_icon.png` | The ambient view: one line, one icon, the open step, the verb to say. Pure vector + text, no transfer. | 0 |
| `05_ambient_report_filed.png` | Ambient after "Millia, report": the task went to the dashboard. | 0 |
| `06_first_person_mockup.png` | **What the wearer sees** — the ambient scene screen-blended over a real staff photo, as an OLED would show it. **Mockup**: the window size (22 % of the view) is assumed; Halo's field of view is not published. | 0 |
| `07_glasses_front.png` | A pair of glasses from the front, the display small in the **wearer's right lens only**. The frame is schematic; the display content is the real emulator output. | 0 |
| `08_pov_through_glasses.png` | `06` with the lens rims drawn in the periphery, so the display reads as "in the right lens", not "a circle". | 0 |

| `09_lua_app_ambient.png` · `10_lua_app_wrapped.png` · `11_lua_app_detail.png` | **The real app** (`glasses/main.lua`) drawing the three views through the vendor's message layer — not the R&D script. `10` shows the wrap limit: three rows, then `..`. | 13 for `11` |

**For the card, post `07` and `08`** (then `03` for the photo thumbnail). `01`–`05` are the
framebuffer — the panel's own pixels — not what the wearer sees. `09`–`11` are what the
shipped Lua app draws; regenerate them by running the tests in `tests/glasses/`.

**Why a circle, and does it fill their vision?** The vendor's, not ours: Halo's 0.2-inch
micro-OLED (640×480 physical) is shown through an optic as a round 256×256 drawable area in
one eye (hardware manual, "Key features"; Lua docs, "256×256 circular screen"). It does not
fill vision — it is a small floating window; the vendor does not state the angle, and
Frame's was about 20°, so treat `06`'s size as a guess. On an OLED **black is transparent**:
the room shows through everything that is not lit.

Two findings from `06` that the framebuffer pictures hide:

- **Grey does not read.** Over a white wall the 50 % grey lines vanish; only white and the
  green disc survive. The Lua app must draw text in white only, and use colour for icons.
- **"Task filed" reads as "Task failed"** in an 8-px pixel font (Ryan, 2026-08-27). The copy
  is now "Reported". Check every word of glass copy for this: short pixel text is misread.

So:

- **The panel is not the limit. The transport is.** Halo images ride the same 512-byte
  BLE characteristic as `print()` output (research doc, "bandwidth catch"). A full-frame
  RGB888 photo is 384 writes; a 112-px 16-colour thumbnail is 13. Ship the thumbnail.
- **The round crop is the real layout constraint, not 256 px.** At the vendor's 8-px Dogica
  font doubled (16 px, the smallest size that reads at arm's length in the emulator), a line
  near the top or bottom of the circle holds **10–12 characters**; only the middle band holds
  14. The script refuses any line the crop would cut (`centered_text` → `chord`), which is
  how scenes 03–05 were laid out. The first render cut every edge line; do not lay out to the
  square.
- **One line of text, one icon** (research doc line 161) stands. The detail view adds the
  thumbnail and a prompt, and nothing else fits.

## Where detail lives

- **Glass**: the ambient line (unit · step index · a few words) and, on "Millia show" or a
  photo step, the detail view above — a thumbnail and one prompt. Never the whole step
  text, never a list.
- **Phone (MOPS) and dashboard**: the full step text, the full-size sample photo, the form
  items and counts, the task thread. The glass is a pointer into them, not a copy.

Recorded in `CONTEXT.md` § Glasses ("Ambient line / Detail view").

## Not verified here

- Real hardware. The emulator mirrors firmware 0.8.8's `lua_display.c`; the vendor labels it
  experimental. Brightness, the optic's actual visible radius, and BLE throughput are
  unmeasured until a Halo arrives.
- Whether format 0 (RGB888) is accepted by the firmware's `bitmap` at all — the emulator
  accepts it; the shipped path uses format 16 either way.

The handoff's "confirm the window opens" is done: `--window 3` opened the vendor's pygame
window with the ambient scene on macOS (2026-08-27, pygame 2.6.1 / SDL 2.28.4) and closed it
after 3 s. The window is a vendor loop on the main thread; it is not tested headless.
