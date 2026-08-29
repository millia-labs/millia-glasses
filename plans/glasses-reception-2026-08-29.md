# Glasses: the reception scene (2026-08-29, overnight build)

> Written in the `millia` monorepo before the client half was split out (2026-08-29). Backend
> paths here (`services/…`, `src/…`, `tests/api/…`, `scripts/deploy.sh`, worktrees) are relative
> to that checkout, `../millia`; the client paths are this repo's.

Source: EoD transcript 2026-08-28 (Mo, Jason, Ryan). Mo's ruling at 20:46–20:50: the
glasses demo is **reception**, not cleaning. The cleaning beats stay in the code and in
`glasses/shot-list.txt`; this scene is added beside them. Submission is the 30th.

## The scene (Mo's words, in order)

1. The wearer is a receptionist, face to face with a guest.
2. Guest: "Hi, I'm in room 1208." The glass shows the guest's name and the room.
3. The glass shows "Listening to guest request".
4. Guest: "The AC is a bit too noisy, and can I have some more towels?"
5. A question **in red** on the glass: "Confirm number of towels". The wearer asks the
   guest aloud; the guest answers.
6. A question **in orange**: "When would you like it delivered?" The guest answers.
7. The exchange ends: the glass shows "2 tasks created" with the tick.
8. Phone 1 (the wearer): the two tasks are there. Phone 2 (another staff member) accepts
   the delivery task.

Decisions taken with Ryan (01:00): extend, do not overhaul; the button (Space in the
window) opens and closes the session; text only — Millia does not speak during a guest
session; red = a fact she needs before she files, orange = optional; both tasks land in the
pool, unassigned; the guest comes from the in-stay reservation on the spoken room, or by
name; no face recognition; "Millia" said inside a session changes nothing; a long silence
(20 s after the guest's first line — the open itself starts no clock) also closes the session; an unanswered red question skips that request, an
unanswered orange one takes "as soon as possible"; English only; stateless backend — the
host sends the whole session transcript each turn; test with two or three in-stay guests so
the matching is proven.

## Backend

`POST /api/v1/glasses/guest` (staff JWT, `mops_config.glasses.enabled`), form fields:
`client_request_id`, `transcript` | `file`, `prior_transcript` (every earlier line of the
session, newline-joined), `close` (the button: file now), `device_id`.

`services/glasses/guest.py`:
- `in_stay_guests(supabase, client_id, today)` → `[{reservation_id, unit_code, guest_name}]`
  — the tenant's in-house list, the same rows MOPS's guest list reads.
- `parse_guest_session(transcript, candidates, now_local, ...)` — ONE strict
  structured-output call: the room as said, the name as said, and the requests, each with
  `kind` (maintenance | delivery | housekeeping), `summary`, `item`, `quantity`,
  `deliver_when`, `deliver_by_local`.
- `resolve_guest(session, candidates)` — room first, then name (a candidate whose name
  shares a word with what was said; exactly one, else none); none → the red question
  "Which room?".
- `open_question(guest, session)` — deterministic, not the model's: no guest → red "Which
  room?"; a delivery with no quantity → red "How many <item>?"; a delivery with quantity
  and no time → orange "When to deliver?"; nothing open → None. The copy is short because
  the two question rows on the optic hold 12 and 10 glyphs.
- `_file_guest_requests(...)` (in the route) on close: every complete request goes through
  `create_maintenance_task` (the MOPS FAB door) with `task_type` maintenance | delivery |
  housekeeping, unassigned, `origin=guest_request` (which makes `source=guest_request`),
  `reservation_id`, `due_by`; `client_request_id` = `uuid5(<close id>, n)`; the delivery
  description names the guest, the room, the count and the time.

The cue: `{guest, requests, question:{text, level}, filed:[...], display:{unit_code,
guest_name, requests, question, level, filed}, say:"", heard, timing}`. `say` is always
empty: Mo's passive observer. Layout is the host's (ADR 0036).

## Glass

New message `0x0F` (host → glass): a colour byte (0 white, 1 red, 2 orange, 3 green),
then `unit\nname\nrequests\nquestion`. The room large, the name under it, three rows of
requests, the question in the colour on two rows at 160/180 (not the foot: a row at 208
holds six glyphs). `main.lua` only draws; `tests/glasses/test_lua_app.py` proves the red
pixels and that every question the backend writes fits its rows whole.

## Host (`scripts/glasses_host.py`)

- The button (`0x0C` single; Space in the window) toggles a guest session. Open: the ear
  is held open (no wake word), the glass shows "Guest · listening". Close: the session is
  posted with `close=true`, the glass shows "N tasks created".
- Every utterance while a session is open goes to `/glasses/guest` with the session so
  far as `prior_transcript`. Nothing is spoken.
- 20 s without an utterance closes the session (the fallback). The clock starts with the
  guest's first line, not at the button: the wearer opened the session on purpose, and a
  guest may take a moment.
- Script mode: a line `@button` plays the press; `guest:` / `wearer:` prefixes are the
  crib sheet's and are stripped.

## Data on millia-dev (Sun & Moon, chrisdemo)

`scripts/glasses_guest_reset.py`: seeds the demo guests as in-stay reservations (idempotent
on `pms_stay_code` `GLASSES-DEMO-<n>`), and removes the take's tickets and delivery tasks
(filed by the receptionist today on those rooms). Dev-only guard, as the clean reset.

## Proof

- Hermetic: `tests/services/glasses/test_guest.py`, `tests/api/test_glasses_guest.py`
  (the real route over TestClient, FakeSupabase with three in-stay guests and one from
  another tenant on the same room number), host and Lua tests.
- Live, headless, no TTS: a local uvicorn against the dev database, the reception shot
  list through `--script --headless --no-speak`, the rows checked in the database, then
  the reset. Variations: room only, name only, wrong room, guest says "Millia", one
  request, three requests, silence close.
- Then `./scripts/deploy.sh` to millia-dev and the same run against the deployed backend.
