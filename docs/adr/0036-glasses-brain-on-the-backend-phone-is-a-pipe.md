---
status: accepted
date: 2026-08-26
---

# Smart glasses: the backend decides, the phone is a pipe, HTTP plus the existing live channel

The smart-glasses demo (Trello card 155) puts a cleaner's and an inspector's checklist on a pair of glasses driven by voice. The device we plan to order (Brilliant Labs Halo) has **no network** — camera, mic, speaker and display all ride Bluetooth to a host phone. So the phone that already runs MOPS is the only route to the backend, and the design question is where the thinking lives and how the phone and the backend talk.

We put **all interpretation on the backend**. The phone records audio after a wake word ("Millia") or a button press and posts it to `POST /api/v1/glasses/say` with the MOPS bearer JWT. The backend transcribes it (the same Whisper path the maintenance mic drafts use), decides the intent with a structured-output LLM call, **performs the action through the existing doors** (checklist tick, inspection verdict, v5 status change, maintenance task creation), and returns a **cue**: the words to speak, the ambient line and detail view to show, and whether to take a photo. `GET /api/v1/glasses/context` answers "who am I, what am I on, what is next" from the same code. The glasses mode — cleaner or inspector — is derived from the task's status and the wearer's `can_inspect`, never chosen. The reply is spoken in the language the wearer used, falling back to their profile locale. Both routes sit behind `clients.mops_config.glasses.enabled` and return 409 with a sentence when it is off (the house pattern for a flag that is off; no route here 404s on a flag).

Transport is **request/response HTTP for commands** and the **Supabase Realtime channels MOPS already holds** (`task_messages`, `task_events`, the `tasks` row) for anything that arrives on its own. No new socket, no webhook, no server-side session state: when the backend needs one more fact ("which room?"), the cue says so and the phone sends the next utterance with the previous transcript attached.

## Considered options

- **Brain on the phone** — Flutter matches "done"/"next" and calls the checklist routes itself. Rejected: it is English-and-keyword only, the free-text fault report and the multilingual reply need the LLM on the backend anyway, and every other client (a Halo Lua app, a web page for the CEO, a Wi-Fi Android glass) would re-implement it. One endpoint that any client can drive is the smaller total.
- **A "constant webhook" or WebSocket between glasses and backend** — rejected because the glasses cannot receive anything from the internet, and the phone cannot receive a webhook either. A new WebSocket route buys nothing over HTTP for a one-utterance-one-reply exchange: one HTTPS round trip is ~100–300 ms, and speech-to-text plus text-to-speech dominate. Unsolicited events already have a push channel.
- **Backend-rendered speech (an audio clip per cue)** — rejected for the demo: it adds ~1 s and a cost per utterance, and the phone can speak text on-device (`flutter_tts`) in the same locales MOPS ships. The cue is text; a client that wants audio renders it.
- **A device identity or pairing table** — deferred. The BLE bond is glasses↔phone and the phone is already logged in as the wearer, so every action is attributed to that staff member exactly as a tap would be. The phone sends a `device_id`; it is logged on the `glasses_say` line, not stamped on an event line — `task_events` has no metadata column, a step tick writes no event at all, and the doors own their own event lines. A hardware-inventory table is a later migration if a tenant asks.
- **A computer-vision verdict on the inspector's photo** — deferred, and not planned. The v2 inspection is human (`92866704b`: the assigned inspector owns the verdicts); nothing in the v2 lane calls a vision model, the snapshot drops `samplePhoto`, and the founder does not want a model second-guessing a senior inspector. Recorded so nobody re-audits it.

## Consequences

- The endpoints do nothing a thumb cannot: every write goes through the same door with the same gates (`can_inspect`, status transitions, attendance gate, `client_request_id` idempotency). A behaviour that differs between "Millia done" and a tap is a bug in the glasses layer, not a feature.
- `client_request_id` is mandatory on `say`. Bluetooth and mobile radio retry; a "done" that arrives twice ticks once.
- The backend owns language: the client passes no locale. Whisper's detected language drives the reply; the profile locale is the fallback.
- A standalone Wi-Fi glass (Rokid, Vuzix) could call the same routes with its own MOPS login; nothing in the contract assumes a phone except the deferred pairing story.
- The cue's display content is data (`ambient`, `detail{text, image_url, items}`); layout, font size and the 256-pixel constraint belong to the client. Changing what the glass shows must not change the endpoint.
- "Claim on first touch" (the first tick claims the cleaner, the first verdict claims the inspector — the second half already shipped in `92866704b`) becomes one tenant flag, default on, shipped with the glasses routes, so an unassigned clean answers "Millia done" the way it answers a tap.
