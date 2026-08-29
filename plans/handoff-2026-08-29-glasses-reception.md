# Handoff 2026-08-29 — the reception scene on the glasses (overnight build)

> Written in the `millia` monorepo before the client half was split out (2026-08-29). Backend
> paths here (`services/…`, `src/…`, `tests/api/…`, `scripts/deploy.sh`, worktrees) are relative
> to that checkout, `../millia`; the client paths are this repo's.

Branch `feat/glasses-polish`, worktree `.claude/worktrees/glasses-polish`. Design:
`plans/glasses-reception-2026-08-29.md`. How to run it: `README.md` § "The
reception scene". The take: `glasses/shot-list-reception.txt`.

## What is done

- `POST /api/v1/glasses/guest` — the session turn. Names the guest from the in-house
  list (room first, then name), asks in red (needed) or orange (optional), files on
  `close`. `services/glasses/guest.py` holds the in-house read, the one model call, the
  guest match and the question policy.
- The MOPS FAB door `POST /api/v1/maintenance/tasks` takes `reservation_id` (tenant-
  checked), `due_by` (ISO, tz required) and `origin`; `origin=guest_request` writes
  `source=guest_request` — without that the My Tasks board hid both tasks, because the
  room is occupied (measured, see below).
- The host: the button (Space, `@button`, the Halo's own) opens and closes a session;
  the ear is held open; nothing is spoken; the guest view is `0x0F` with the question in
  colour; 20 s of silence closes the session; `guest:` / `wearer:` prefixes are the crib's.
- Later the same day (three commits after `da40bfd11`):
  - Power-on no longer speaks the greeting; it is on the console only.
  - The prompt says the lines carry no speaker labels (the host strips the crib's
    prefixes; one microphone hears both people), that a repeat-back is the receptionist
    confirming and not a new request, and that an unsupported ambiguous line is not filed.
  - **"Millia, dismiss"**: the receptionist can end a session by voice with nothing filed
    — they will do it in the app. `GuestSession.dismissed` (one boolean the model sets in
    the same call), the route answers `intent: "dismissed"`, files nothing even on a
    close, asks no question; the host drops the session on that cue, sends no close, and
    the glass shows "Dismissed". A guest withdrawing one item is not a dismissal. Proven
    on the route, on the host, and on the prompt/schema; not yet against a live model.
  - Known gap, not built: two guests in one session. The schema has one room for the
    whole session, so a second guest's words before the close are filed under the first
    guest. The button between guests is the guard; a per-request room is the fix if it
    is ever needed.
- `main.lua` draws the guest view. `scripts/glasses_guest_reset.py` seeds the guests
  and removes the take's tasks.
- `--login` can mint more than one wearer per process now (the admin client used to
  become the first wearer after `verify_otp`).

## What ran, and what it measured

Hermetic: 213 tests green across the glasses set (`tests/api/test_glasses_*`,
`tests/api/test_maintenance_create_guest_fields.py`, `tests/services/glasses`,
`tests/scripts/test_glasses_*`, `tests/glasses`). The scripted-session test runs the
real route and the real Lua app and reads the red pixels off the framebuffer.

Live, against millia-dev's database through a local backend (`--api
http://127.0.0.1:8011`), headless, no TTS, wearer Ry Receptionist:

| run | result |
|---|---|
| the take (`shot-list-reception.txt`) | 1013 Mark Robelo named on the first line; red "How many towels?" (it read "Confirm number of towels" until fix 5); orange "When to deliver?"; clear; close → **2 filed**: a `maintenance` ticket and an unassigned `delivery` task, both linked to Mark's stay, `origin=guest_request`, `due_by` on the delivery |
| the boards | both tasks on Ry's and on Maria's guest-request board; **Maria claimed the delivery** (`POST /staff-tasks/{id}/claim` → `claimed: true`) and both boards show her as assignee |
| audio | three clips synthesised with OpenAI TTS at 16 kHz through `file=`: "room ten thirteen" → 1013 Mark Robelo; the questions as above; 3.0–4.6 s per turn (transcribe 0.9–1.5 s) |
| name only ("it's Robelo, the tap is dripping") | Mark Robelo, 1 filed (maintenance) |
| wrong room (9999) | "Which room?" in red, 0 filed |
| "Millia is a lovely name. I'm in 0712 …" three requests | Amira Hassan; make up the room / 2 bottles of water right now / TV remote → 3 filed: housekeeping, delivery, maintenance |
| red question open at close (hangers, no count) | 0 filed, the red line stays |
| silence (`--guest-silence 3`) | the session closed itself; the ticket filed once `stop()` waited for the close (a fix from this run). Re-proven against Fly at the end: "shower cold" on 2008 filed by the clock, the wearer's late line dropped with a console note. The clock starts with the first answer on the glass, not at the button |

Timing per text turn from the laptop: context ~700 ms (three reads over the laptop's
link), parse 1.3–2.3 s (gpt-5-mini, reasoning off), total 2.1–3.4 s.

**Against the deployed millia-dev (the demo's backend, deploy 4 = the branch tip's backend), after the review fixes:** a text
turn 1.6–2.2 s; the close **3.1 s for two tasks, 4.2 s for three** (it was 4.4 / 6.2
before the summariser was kept out of the path — see fix 6 below). The door is ~1 s per
task on Fly and its Supabase calls are synchronous, so the tasks file one after another
even under `asyncio.gather`. If the closing beat must be faster, the change is to run
each door call off the loop; the door itself is the FAB's and is not this branch's.

## What was found and fixed on the way

1. The first live close 500ed: `client_request_id` is a uuid column, and the per-request
   suffix `<uuid>:0` is not one. Each request now gets `uuid5(turn id, n)`.
2. Both tasks filed and neither reached a board: `_guest_request_scope_rows` returned
   them, then the occupied-room gate dropped every `source != 'guest_request'` row —
   the FAB door hard-codes `source='manual'`. The door now derives it from `origin`.
3. `mint_session` worked once per process: `verify_otp` made the wearer's session the
   admin client's own, so the next `generate_link` ran as the wearer ("User not
   allowed"). The local session is dropped after the mint.
4. A piped take ended while the silence clock's close was still posting; nothing was
   filed. `stop()` awaits it.

A review pass over the branch (02:30) found six more, all fixed and covered:

5. "Confirm number of towels" at the foot of the optic drew as "Confirm" / "numb.." — a
   16 px row at y=188 holds 9 glyphs, at 208 six. The question is on two rows at 160/180
   (12 and 10 glyphs) and the copy is short: "How many towels?", "When to deliver?",
   "Which room?". A test mirrors the Lua wrap and proves every question fits whole. A
   long guest name ends in ".." instead of running off the rim.
6. A description over 60 characters on its first line makes the door call gpt-5-nano
   for the card's headline — a 7 s outlier on the close. The description is now two
   lines: a short headline ("Deliver 4 towels — by six"), then the guest and the room.
7. A button press while a line was still posting raised on the swapped-out session and
   lost the line. Turns and the close share a lock: the press waits, the line is in the
   close. A line that arrives as the session closes is dropped with a console note.
8. A refused close (a 409, say) discarded the whole session. It keeps the words and the
   clock; the button can be pressed again. `stop()` waits for the button's close too, not
   only the clock's. The close's id is minted when the session opens, so a retried close
   reuses it.
9. One refused lane (a tenant without tasks-v2 — not Sun & Moon) aborted the close and
   lost the rest. Each request files on its own; a refusal is logged and the count is of
   what filed.
10. A negative or zero count from the model blanked the session through a validation
    error. It is "not said" now.

A second review pass over those fixes (02:50) found five more, all fixed and covered:

11. Two fast presses: the second overwrote the first close's task, so `stop()` waited
    for the wrong one. Every toggle is kept in a set until done; `stop()` gathers them
    all. The open-or-close decision is under the lock, so a press during a close is the
    next guest's open, never a swallowed second close.
12. A 5xx or a dead link on the close raised out with the clock stopped and the ear held
    open. It is a refusal cue: the words stay, the clock re-arms, Millia says "The
    backend did not answer. Try again."
13. The silence clock was armed before the round trip and counted it. It starts when the
    answer is on the glass and does not run while the guest's words are up.
14. Every request refused for the same reason (the wearer not clocked in: 409) came back
    as "0 tasks created". The door's own sentence is raised instead — spoken and shown.
15. A count outside 1..99 is "not said" (a thousand towels is a misread); "ASAP" keeps its
    case; the name row moved to y=78 (12 glyphs — "Priya Sharma" whole).

A live run of the CLEANING scene at the end (03:00) found one more, the only regression
this branch introduced, and fixed it:

16. The cleaning scene's `report:` beats refused with "Invalid origin: annotation=…".
    `_act_report` calls the door as a plain function and did not name the three new
    fields, so their `Form(None)` defaults arrived as field objects. Every parameter is
    named now, and the door fakes in both endpoint test files refuse a field object as a
    value (that test was red before the fix). The cleaning take's other beats ran
    through the reworked host as before. Re-run on the deployed backend after the fix
    (02:39): "Logged. Maintenance ticket for room 0712: Bedside lamp not working." and
    "Noted. Housekeeping task for room 0712: Two extra towels." Both scenes reset.

Note for the cleaning take: the two seeded stays (Mark in 1013, Amira in 0712) put
Departure cleans for 0712 and 1013 on today's board, and today's board no longer holds
the 1213/1607 cleans `glasses/shot-list.txt` was measured against on the 28th. Re-measure
the board before that take (`glasses_reset_clean.py` with today's rooms).

**Morning decision (Ryan, 2026-08-29 ~03:00): the occupied-room hide is retired.** The
My Tasks board dropped every `source != 'guest_request'` task in a room with a guest in it
until checkout (Jason's 2026-07-19 canon, written before the desk filed housekeeping and
delivery cards and before Millia's project fan-out — both `source='manual'`). That was the
"source=manual never shows in My Tasks" bug. The gate is gone; `is_occupied` stays on the
card. Red-first test: `tests/api/test_guest_request_endpoints.py::
test_list_shows_a_staff_filed_task_in_an_occupied_room`. The door's `source` derivation
from `origin` (fix 2 above) stays as a truthful stamp, no longer as a workaround. **Tell
Jason**: it was his rule. `source='manual'` is NOT retired as a value — see
`/tmp/handoff-2026-08-29-retire-source-manual.md` for the writer map if that is ever wanted.

**Not re-proven live:** the board results in the table above were measured *before* the gate
was retired, with the `source=guest_request` stamp doing the work. The retirement is backed
by the hermetic route test only; nobody has re-run the two-board check against a deployed
backend carrying `b7cde6cf5`. Do that before the demo.

Not changed, noted by the review: `api/in_stay_endpoints.py:126` counts only transfer /
cleaning / maintenance on the In-Stay card's chips, so a desk `delivery` is not counted
there (the maintenance ticket is). The `client_request_id` cache is keyed by route now.

## Not done / open

- The close latency on Fly is 3.1 s for two tasks (above). Acceptable for the take; if
  it must be faster, run each door call off the loop — do not change the door.
- No face recognition (out of scope, Ryan 2026-08-29). The room, else the name.
- In a session the lens window's subtitle is the open question, in its colour (the glass
  has it at 16 px; a recording needs it large). Nothing is spoken.
- Jason's script was not in Downloads at 01:00; the shot list is Mo's beats. When it
  arrives, its lines replace the `guest:` / `wearer:` lines; the mechanism stays.
- Pre-existing red, not this branch's: `tests/api/test_mops_guest_endpoints.py` (6),
  `tests/api/test_maintenance_create_idempotency.py` (2) — both fail identically on
  `c47e7bd03`.

## Look before you run

`.scratch/glasses-reception-frames/` (untracked) holds the glass and the lens for each
beat as PNG — `3-red-how-many-glass.png` is the hero frame. Rendered from the real Lua app
in the emulator and the real window code, headless.

## The morning

```bash
(cd ../millia && uv run python scripts/glasses_guest_reset.py --yes)
uv run python scripts/glasses_host.py --login ry.chrisdemo@millia.test --script glasses/shot-list-reception.txt
```

Click Start, press Enter through the lines (Space is the button too). MOPS as Ry on one
phone, as Maria on the other; Maria's Start Work on the delivery card is beat 8.
