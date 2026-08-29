# Glasses endpoints — design (2026-08-26)

Trello card 155, *FEAT/Smart glasses demo thing*, item "Ready the endpoints for what the
eventual glasses will communicate with on the app". Settled in a grilling session with Ryan
on 2026-08-26; the CTO's later rulings amend this file. Decision record: ADR 0036. Vocabulary:
`CONTEXT.md` § "Glasses (hands-free MOPS)". Research: `docs/research/smart-glasses-hotel-staff-2026-08-26.md`.

## The shape

```
glasses ──BLE──> phone (MOPS, logged in) ──HTTPS──> backend ──HTTPS──> phone ──BLE──> glasses
                                           ▲
                        Supabase Realtime ──┘  (task_events / task_messages / tasks row — unsolicited)
```

- The glasses have no network (Halo: Bluetooth only). The phone is the only route.
- The phone is a pipe: mic → audio → `say` → cue → speaker/display. No intent logic on the phone.
- No new socket, no webhook, no server-side conversation state.

## Routes (both under `/api/v1/glasses`, `verify_staff_auth`, 409 unless `mops_config.glasses.enabled`)

### `POST /say` — one utterance in, one cue out

Multipart: `file` (audio, same formats as `/voice-notes/split-requests-audio`) **or** `transcript`
(text, for tests and the CEO's web page); `client_request_id` (UUID, **required**); `task_id`
(optional); `device_id` (optional, logged on the `glasses_say` line); `prior_transcript`
(optional — the previous utterance when the last cue said `needs`); `step_id` (optional — the
step the phone is showing after a skip); `photo_url` (optional — the inspector's shot, already
uploaded through the inspection photo route, sent with `pass` / `redo`).

Response (`Cue`):

```json
{
  "intent": "done | next | skip | repeat | where_am_i | start_work | complete |
             counts | shoot | pass | redo | report | show | hide | unknown",
  "task_id": "…", "mode": "cleaner | inspector | none",
  "step": {"id": "…", "index": 4, "total": 12, "name": "Wipe the mirror", "proof": "tick|photo", "kind": "form|null"},
  "say": "Step four, wipe the mirror.",
  "language": "ms",
  "display": {"ambient": "4/12 · Wipe the mirror",
              "detail": {"text": "…", "image_url": "…", "items": [{"name": "toothbrush", "expected": 2, "replenished": 2}]}},
  "capture": false,
  "needs": null | "unit_code" | "confirm_counts" | "counts"
}
```

Replays of the same `client_request_id` return the stored cue and perform nothing (per-process cache keyed `(client_id, staff_id, client_request_id)` — per wearer, so two phones in one tenant never read each other's cue; the doors are idempotent for a repeated tick, so no table).

`step_id` (optional) is the step the phone is showing after a skip — the backend holds no cursor.

### `GET /context?task_id=` — who am I, what am I on, what is next

`{me: {name, role, can_inspect, locale}, mode, current: {task_id, unit_code, cleaning_type, status, mode, step},
next: {task_id, unit_code, cleaning_type, status} | null, pending_count, last_action: {line, at} | null,
display: {...}, say}`. `say` (the route) calls the same function; the two never disagree — the
`say` field here is the where-am-I sentence the glasses speak on wake.

## Resolution rules

- **Task**: `task_id` from the client if given (the phone sends it whenever a thread is open — an
  unassigned pending clean, or an unrostered completed one, resolves no other way); else the
  caller's one `in_progress` clean; for an inspector with none, the `completed` clean rostered to
  them; else none. "Start work" with nothing in progress starts the next clean. "What am I on" with none in progress answers with `next` (the first pending clean
  assigned to the caller) and its count.
- **Mode**: `pending`/`in_progress` clean → cleaner; `completed` clean and `can_inspect` → inspector;
  anything else → none (the cue explains: "This clean is done — it needs an inspector").
- **Open step**: first checklist step with `done == false` (cleaner); first step without a verdict
  (inspector). Derived every call; nothing stores a cursor.
- **Language**: Whisper's detected language; fallback the staff profile locale.

## Intent → existing door (nothing new is written by the glasses layer)

| intent | mode | door |
|---|---|---|
| done | cleaner | `PATCH /cleaning/tasks/{id}/checklist/steps/{step}` `{done: true}` — the first tick starts the task |
| counts | cleaner | same door, `{items: [{id, replenished}]}` — **read back first**, tick on the confirm (`needs: confirm_counts`) |
| next / repeat / skip / show / hide / where_am_i | any | no write; cue only (skip = the cue names the following open step; the phone sends it back as `step_id`) |
| start_work | cleaner | `PATCH /api/v5/tasks/{id}/status` `{status: in_progress}` |
| complete | cleaner | `PATCH /api/v5/tasks/{id}/status` `{status: completed}` — refused unless every step is done |
| shoot | inspector | cue `capture: true`; the phone posts to `POST …/inspection/steps/{step}/photo` and sends the URL as `photo_url` with the verdict |
| pass / redo | inspector | `PATCH /cleaning/tasks/{id}/inspection/steps/{step}` `{verdict, note, photo_url}` |
| report | any | `POST /api/v1/maintenance/tasks` semantics via `task_service.create_task` — `unit_code` from the task; none → `needs: unit_code` |

Fast path: an exact match on a short per-language table (done / next / skip / repeat / pass /
show / hide) skips the LLM. Everything else is one structured-output call
(`method="json_schema", strict=True`).

## Also in this ticket: `cleaning_v2.claim_on_first_touch`

One tenant flag, default **on**. On: the first tick on an unassigned clean sets `assigned_to`
to the ticker (new — it also closes the pool-completion trap in the cleaning-expert skill), and
the first verdict on a clean with no inspector sets `supervisor_id` to the inspector (already
`92866704b`, now behind the flag). Off: both doors refuse an unassigned clean — 403 "Not
assigned to you" — and the assignment board is the only way in. "Millia done" and a thumb then
behave the same on an unassigned clean.

## Out of scope (this ticket)

- The phone UI (Glasses Mode route, wake word, `flutter_tts`, BLE) — next Trello item.
- Computer-vision verdicts — not planned (ADR 0036).
- A device/pairing table — deferred.
- "What is everyone doing" (hotel-wide view) — a manager's read, later.

## Proof

- `tests/api/test_glasses_endpoints.py` — `TestClient` against the real app, `verify_staff_auth`
  overridden, Whisper and the LLM faked, a filtering Supabase fake: flag off → 409; context with
  none/one/two tasks; done ticks the open step and starts a pending clean; counts read back then
  write on confirm; complete refused with open steps; pass/redo through the verdict door with
  `can_inspect` gate; report with and without a room; replay of `client_request_id`.
- `scripts/glasses_demo.sh` — the three stage beats over `curl` with `transcript=`.
