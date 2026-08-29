# Handoff — Glasses demo: emulator recording + display R&D (2026-08-26)

> Written in the `millia` monorepo before the client half was split out (2026-08-29). Backend
> paths here (`services/…`, `src/…`, `tests/api/…`, `scripts/deploy.sh`, worktrees) are relative
> to that checkout, `../millia`; the client paths are this repo's.

Trello card 155, *FEAT/Smart glasses demo thing*. Branch `feat/mops-smart-glasses-demo`, PR open.
The backend half is done (`df1cfe392`, ADR 0036). Tonight the CTO (Jason) settled **how the demo
is shown**, and raised one worry that needs R&D before anything is recorded. Both are below, so
nobody re-derives them.

## What Jason decided (chat, 2026-08-26 18:49–18:59)

- **The demo is a screen recording of the vendor emulator** (`halo-emulator`), not a phone UI.
  "We will screen record on the emulator. Talking to millia in the glasses to create a task."
- **Staged and scripted is fine.** Mo plays the recording and narrates. Nobody drives it live.
- **The beats he wants:** talk to Millia to create a task; "looking at things and the checklist is
  ticking off".
- **His worry:** "256×256 sounds great on paper, but I am worried that it's pixel, so we can only
  display text." Ryan agreed the sample photo would be thumbnail-only. Ruling: "we need R&D there."
  Ryan: "will look into it and actually try tomorrow."

This replaces the three open card items ("UI / demo on the phone", "UI for the glasses screen",
"Screen recording") with the checklist at the bottom.

## Facts already established — do not re-research

- `halo-emulator` is real and verified (`docs/research/smart-glasses-hotel-staff-2026-08-26.md:180-195`):
  a Python package embedding the same Lua 5.4 VM the glasses run (`lupa`), every `frame.*` call
  stubbed, the display rendered to a real 256×256 buffer (PIL image / live window:
  `halo-emulator ./app/`). Event injection: BLE data, button presses, IMU taps. Install:
  `uv add halo-emulator`. Vendor labels it experimental.
- **The emulator has no microphone and no camera.** Voice and photos must come from outside it.
  The laptop plays the phone: mic → `POST /api/v1/glasses/say` → Cue → inject over emulated BLE →
  Lua app draws it → macOS `say` speaks `cue.say`. No Flutter work is needed for the recording.
- **The display is not text-only.** 256×256, round, full colour (`0xRRGGBB`), no double-buffer.
  Lua API: `text`, `char`, `set_font`, `bitmap`, `line`, `rect`, `circle`, `polygon`, `clear`
  (research doc line 327). Images reach the glass over BLE in ≤512-byte chunks (`brilliant_msg`,
  line 350). The limit is size and the round crop, not a text-only display. The research doc's
  own design ruling (line 161): "one line of text, one icon. Design to the real constraint."
- The backend contract already separates content from layout: `cue.display.ambient` (one line)
  and `cue.display.detail{text, image_url, items}`; the client owns layout and the 256-px
  constraint (ADR 0036 Consequences; `CONTEXT.md` § Glasses). **Changing what the glass shows
  must not change the endpoint.**
- **"Looking at things and the checklist ticks" is NOT a vision tick.** ADR 0036 rules out a CV
  verdict — the v2 inspection is human, and the founder does not want a model second-guessing an
  inspector. In the recording a step ticks on a spoken "done"; a photo step shows the picture and
  the inspector speaks the verdict. If Jason expects the camera alone to tick a step, that is a
  scope change against the ADR — ask, do not build.
- Everything the recording needs on the backend exists and is tested: `POST /api/v1/glasses/say`
  (intents `done`, `next`, `report` → maintenance task, `shoot` → `capture: true`, `pass`/`redo`),
  `GET /api/v1/glasses/context`, `scripts/glasses_demo.sh` (the three beats over curl with
  `transcript=`), `tests/api/test_glasses_endpoints.py` (26, real route through `TestClient`).
  Both routes 409 unless `clients.mops_config.glasses.enabled` is true; `client_request_id` is
  mandatory on `say`.

## Recording script (all beats supported today)

1. `GET /context` — "who am I, what am I on" (the ambient line appears)
2. "Millia, start work"
3. "Millia, done" → the step ticks, the next step is read aloud
4. "Millia, next step"
5. "Millia, report: the bedside lamp is not working" → a maintenance task appears on the dashboard
6. "Millia, take the photo" → `capture: true`; the staged photo shows on the glass
7. "Millia, redo — water spots on the mirror" (with `photo_url`) → verdict written

Optional: "Millia, seterusnya" — with audio the reply comes back in Malay.

## Checklist for the Trello card

**R&D — the 256×256 display (do this first; it decides the Lua app)**
- [ ] Install `halo-emulator` (`uv add halo-emulator`) and confirm the window opens
- [ ] Draw one sample photo as a `bitmap` at 256×256 in the emulator; screenshot it
- [ ] Draw the ambient line + one icon; screenshot it
- [ ] Post both screenshots on the card with a ruling: pictures on the glass = yes / thumbnail only / no
- [ ] Record where detail lives (phone + dashboard vs. glass) in `CONTEXT.md` § Glasses

**Build — the glasses app**
- [ ] Lua app for the Halo display: draws `cue.display.ambient` and `cue.display.detail`
- [ ] Host Python driver in the emulator process: laptop mic or scripted lines → `POST /glasses/say`
      → Cue over emulated BLE → macOS `say` for `cue.say`
- [ ] Capture beat: on `capture: true`, show a staged photo and send its URL as `photo_url` with the verdict

**Data — millia-dev**
- [ ] Set `mops_config.glasses.enabled = true` on the demo tenant (deliberate, user-requested write;
      read the row first)
- [ ] Seed one cleaning task with a checklist and one staff member with `can_inspect`
- [ ] Run `scripts/glasses_demo.sh` against dev end to end

**Screen recording**
- [ ] Write the script (above) as the shot list
- [ ] Record the emulator window with laptop audio (QuickTime or OBS)
- [ ] Hand the recording to Mo with one paragraph of talking points

**Confirm with Jason**
- [ ] "Looking at things and the checklist ticks" = spoken "done" + photo shown, not a vision tick.
      Get a yes, or a scope change against ADR 0036, before recording.

## Not done tonight

No code was changed after `df1cfe392`. The emulator is not installed. No screenshot exists yet.
