# Smart Glasses for Hotel Cleaning & Maintenance Staff, Connected to Millia

Research completed 2026-08-26, for a 3-day hackathon (Wed 2026-08-26 →
Fri 2026-08-28).  All product facts are from vendor primary sources
fetched on 2026-08-26 unless marked **[secondary]** or
**[unverified]**. Store prices and stock change daily — re-check
before ordering.

**Hard constraints driving this document:**

- The team owns **zero glasses today** and the CEO has already
  promised a demo.
- **The developer is in the Philippines and will not have a device.**
  His realistic deliverable is a concept, mockups, and a phone-based
  simulator.
- **The CTO (Jason) is the only person who could hold real hardware**
  — he travels and can buy or receive in **Japan, Korea, Malaysia,
  Singapore or Cambodia**.
- **Prototype focus is the cleaner**: the per-step cleaning checklist
  with photo proof and CV verdicts (which the dev already built) comes
  first; maintenance task reporting second.

---

## Table of Contents

1. [Recommendation](#1-recommendation)
2. [What the Developer Can Build Without a
   Device](#2-what-the-developer-can-build-without-a-device)
3. [Availability by Country](#3-availability-by-country)
4. [Feasibility Matrix](#4-feasibility-matrix)
5. [Brilliant Labs](#5-brilliant-labs)
6. [Meta](#6-meta)
7. [Other Options](#7-other-options)
8. [Use Cases for Millia](#8-use-cases-for-millia)
9. [What Could Not Be Verified](#9-what-could-not-be-verified)
10. [Verification Pass — Asian and Other Vendors
    (2026-08-26)](#10-verification-pass--asian-and-other-vendors-2026-08-26)

---

## 1. Recommendation

### The short version

**The demo is a phone-based glasses simulator wired to the real
cleaning-checklist and CV pipeline, and it must not depend on hardware
arriving.** The developer builds that in the Phlippines with no
device.  In parallel, the CTO orders a **Brilliant Labs Halo ($399,
ships from Hong Kong)** — the only device in this survey that does
camera + mic + **speaker** + display over one open, documented SDK
that a Flutter app can drive. If it reaches him in time, the stage
demo gets real glasses; if not, the demo is unaffected.

### Why not Meta, given where this team lives

Meta's officially supported AI-glasses countries are **Australia,
Austria, Belgium, Canada, Denmark, Finland, France, Germany, Ireland,
Italy, Netherlands, Norway, Spain, Sweden, Switzerland, United
Kingdom, and the contiguous US plus Alaska and Hawaii** ([meta.com
help](https://www.meta.com/help/ai-glasses/4961066940605960/)).

**Not one of Jason's five countries is on that list. Neither is the
Philippines.** And Meta's FAQ is explicit that only developers in
supported countries get "the full capabilities of the toolkit,
including the Wearables Developers Center"
([FAQ](https://developers.meta.com/wearables/faq/)). So the entire
Meta path — hardware *and* SDK — is a grey-market gamble for this
team, whereas Brilliant Labs' checkout accepts addresses in Japan,
Korea, Singapore, Malaysia and the Philippines directly.  That
reverses the ranking you would give this brief anywhere in Europe or
North America.

If someone still wants Meta glasses on the presenter's face, there is
one honest 3-day use for them that dodges every gate: **wear them as a
plain Bluetooth headset.** Meta's own docs say the mic and speaker are
*not* DAT APIs — they are standard HFP and A2DP profiles
([llms.txt](https://wearables.developer.meta.com/llms.txt?full=true)). That
means voice in and TTS out work with *any* Flutter app, no SDK, no
Meta AI registration, no region check. Camera stays on the
phone. Ray-Ban Meta is stocked grey-market in KL at roughly
RM1,999–2,299 **[secondary]** ([Lazada
MY](https://www.lazada.com.my/tag/rayban-meta-smart/)) and in
Japan/Korea through import channels **[unverified]**.

### Three tracks, in order of who blocks whom

**Track A — the simulator (developer, Philippines, day 1–2, blocks
nothing).** §2 covers this in detail.  Nothing about it is throwaway:
the backend endpoints, the prompts, the checklist step machine, the CV
verdict path and the TTS reply are exactly what real glasses will
call. Only the transport changes.

**Track B — order a Halo (CTO, Wednesday).** $399, ships from Hong
Kong, which is the best possible origin for anywhere Jason will
be. Treat arrival as a bonus, not a plan — the vendor's own page and
FAQ contradict each other on shipping status (see §5).

**Track C — mockups and the story (developer, day 3).** What the
display shows, what the voice says, what the manager sees. This is
what the CEO actually promised; the working simulator is the proof
that it is buildable.

### What to show on stage in 3 minutes

Three beats, cleaner-first, one per Millia pipeline the audience
already knows:

- **0:00–1:15 — Clean a room hands-free.** Presenter (phone on a
  lanyard, or Halo if it arrived) hears the next checklist step read
  aloud, says *"done"*, and the step advances. On the next step the
  camera takes the proof photo automatically and the **CV verdict is
  spoken back**: *"Mirror has water spots — redo step 4."* The
  projected MOPS thread updates live. This is the core: the cleaner
  never touched a wet phone, and the checklist is the one the dev
  already built.
- **1:15–2:15 — Report a fault without stopping.** *"Millia, report:
  bedside lamp not working."*  A `maintenance` task appears in the
  MOPS chat thread with the photo attached and the unit resolved from
  context. Glasses answer: *"Logged. Maintenance ticket for SU28-06,
  bedside lamp."*
- **2:15–3:00 — Speak their language.** The same checklist step is
  read aloud in Bengali or Malay.  One sentence on why: Pureloft's
  crews are multilingual, MOPS already ships en/bn/ms/km, and the
  glasses just remove the screen.

Close on the fallback slide and say it out loud: *"today the camera is
a phone; the pipeline behind it is production Millia."* That converts
the only weakness into evidence that the hard part is done.

### What NOT to attempt in 3 days

- **Meta DAT camera streaming.** Developer preview, region-gated,
  registration deeplinks through the Meta AI app, no publishing. From
  Philippines or Tokyo this is a research spike, not a demo.
- **Meta Ray-Ban Display Web Apps.** They run on-glasses HTML/CSS/JS
  but have **no camera and no microphone** at launch
  ([FAQ](https://developers.meta.com/wearables/faq/)). Useless here.
- **Brilliant Frame.** No longer sold, and it has **no speaker** — the
  "AI voice out" half of the brief is physically impossible on it.
- **Live first-person streaming to a supervisor.** Halo does
  snapshots, not video (see §5).

---

## 2. What the Developer Can Build Without a Device

This is the deliverable. Everything below is buildable in Philippines with
no glasses.

### Option 1 (recommended) — "Glasses Mode" inside the existing MOPS Flutter app

A full-screen route in `cloa-app/` that behaves the way glasses
behave, against the **real** backend:

| Glasses behaviour | Phone stand-in |
|---|---|
| First-person camera | Rear camera preview, full-bleed, phone worn on a lanyard |
| Voice in | Push-to-talk button, or wake word; stream to the existing STT path |
| AI voice out | `flutter_tts` — already the natural fit for the existing en/bn/ms/km i18n |
| 256×256 monocular display | A small, deliberately cramped overlay card — one line of text, one icon. **Design to the real constraint, not to the phone screen**, or the mockups will lie |
| Tap / button input | Single big tap target; no scrolling, no keyboard |

Why this is the right choice: it reuses MOPS auth, the task-thread
model, the checklist step machine and the photo-upload path that
already exist, so the demo runs against production Millia rather than
a stub. And when a Halo does arrive, swapping the transport layer for
[`brilliant_ble`](https://pub.dev/packages/brilliant_ble) is a
contained change — MOPS is already Flutter, which is the single
strongest argument for Halo over everything else in this survey.

### Option 2 — a small web page that behaves like the glasses

If the CEO wants a link he can open on his own phone, a static page
using `getUserMedia`, `MediaRecorder` and `SpeechSynthesis`, POSTing
to the same checklist and inspection endpoints, is a few hours of work
and demos over a URL. Weaker for the real product, stronger for
sharing. Do this *after* Option 1, not instead of it.

### Vendor emulators that actually exist (verified)

- **Brilliant `halo-emulator` — real, and better than expected.** A
  Python package that embeds the same **Lua 5.4 VM** the glasses run
  (via `lupa`) and stubs every `frame.*` call, rendering the display
  to a **256×256 pixel buffer** you can inspect as a PIL image. It
  supports **event injection** (BLE data, button presses, IMU taps),
  captures BLE sends for assertions, gives a sandboxed filesystem for
  `frame.file.*`, and ships an **interactive REPL with a live pygame
  window** (`halo-emulator ./app/`). Install: `uv add halo-emulator`
  ([README](https://github.com/brilliantlabsAR/brilliant_sdk/tree/main/python/packages/halo_emulator)).
  **Its limit:** it emulates the *device-side Lua runtime* — display,
  BLE, buttons, IMU, files. It is not a camera or microphone
  simulator, so it proves your on-glasses UI and protocol, not your
  perception loop. Labelled experimental by the docs ([Python SDK
  docs](https://docs.brilliant.xyz/halo/halo-sdk-python/)).
- **Meta Mock Device Kit — real, and covers more sensors.** "A
  simulated device that mirrors the capabilities and behavior of Meta
  glasses, including camera streaming, photo capture, permissions, and
  device state changes… When Mock Device Kit is enabled, it simulates
  the entire SDK stack — including app connection (registration) and
  permission requests. Your app code works the same way regardless of
  whether it's talking to a real device or a mock device." Critically,
  **it can use the phone's own camera as the mock device feed** (the
  sample app's `Info.plist` asks for camera access precisely for this)
  ([llms.txt](https://wearables.developer.meta.com/llms.txt?full=true),
  §Mock Device Kit). Gradle artifact `mwdat-mockdevice`; iOS/Android
  testing guides exist.  **Unverified:** whether MDK is usable from a
  non-supported country. It simulates registration, so it plausibly
  bypasses the Meta AI app gate — but nobody has confirmed that, and
  the Wearables Developer Center (where SDK downloads live) is itself
  region-gated.
- **MentraOS** — miniapp development is enabled through a "Miniapp
  Developer Settings" toggle in the Mentra app
  ([docs](https://docs.mentra.glass/app-devs/getting-started/overview));
  no standalone hardware emulator was found **[unverified]**.

**Recommendation for the developer specifically:** build Option 1, and
if there is spare time, port the on-glasses UI to Lua and run it under
`halo-emulator` — that produces a screenshot of the *actual* 256×256
round display, which is worth more in the deck than any mockup, and it
is the exact code that runs when the hardware lands.

---

## 3. Availability by Country

| | Japan | Korea | Singapore | Malaysia | Cambodia | Philippines |
|---|---|---|---|---|---|---|
| **Meta Ray-Ban / Oakley — officially supported?** | No | No | No | No | No | No |
| **Meta DAT full capability (Developer Center)?** | No | No | No | No | No | No |
| **Brilliant Halo — checkout accepts address?** | Yes | Yes | Yes | Yes | Unclear | Yes |

Meta: none of these six countries appear on the [supported-countries
page](https://www.meta.com/help/ai-glasses/4961066940605960/), which
presents a single 17-market list. Grey-market import is the only
route, and it does not unlock the SDK.

Brilliant: the storefront is Shopify with `"countryCode":"HK"` —
**shipping originates in Hong Kong**, the best possible origin for all
six destinations. The checkout's shipping-rate endpoint accepts and
validates addresses (asking for the correct province/postcode format)
for Japan, Korea, Singapore, Malaysia and the Philippines; Cambodia
returned no province prompt. **Actual rates and transit times could
not be confirmed** — the endpoint returns no rates for an empty cart,
and `brilliant.xyz/policies/shipping-policy` is a 404. The Halo page
says only "Import taxes may apply at delivery and vary by country,"
which implies worldwide shipping. Treat lead time as **[unverified]**
until Jason has a tracking number.

---

## 4. Feasibility Matrix

Can a competent dev, in 3 days, get each capability working
end-to-end?

| Device / path | (a) Photo → backend | (b) Mic audio → backend | (c) TTS → wearer | (d) Text on display | (e) Phone bridge | 3-day verdict |
|---|---|---|---|---|---|---|
| **Phone as glasses** (MOPS route) | Trivial | Trivial | Trivial (`flutter_tts`) | Phone screen | n/a | **Certain.** Do this first |
| **Brilliant Halo** | Yes — 640 px JPEG over BLE | Yes — PCM/LC3, 8/16 kHz | Yes — `frame.speaker` | Yes — 256×256 colour | Yes — Flutter `brilliant_ble` | **High if it arrives** |
| **Halo under `halo-emulator`** | No (no camera sim) | No | No | **Yes** — real 256×256 framebuffer | n/a | **Certain.** Free display screenshots |
| **Ray-Ban Meta as BT headset** (no SDK) | No (use phone cam) | Yes — HFP, 8 kHz mono | Yes — A2DP/HFP | No display | Yes, implicit | **High** — but needs a device in hand |
| **Ray-Ban Meta + DAT** | Yes — stream + `capturePhoto` | Yes — HFP, outside the SDK | Yes — A2DP | Only on RB Display | Required (DAT is a phone SDK) | **Low** — region gate + preview |
| **Meta Mock Device Kit** | Yes — phone cam as mock feed | Simulated | Via phone | Simulated | n/a | **Medium** — region access unproven |
| **Brilliant Frame** | Yes — 720×720 YCbCr | Yes — PCM | **No — no speaker** | Yes — 640×400 | Yes | Moot: not sold |
| **Mentra Live** | Yes — SDK camera APIs | Yes — mic + transcription | Yes — speaker API | No display | Yes — MentraOS | **Medium** — shipping is the risk |
| **Meta RB Display Web App** | **No camera** | **No mic** | n/a | Yes — 600×600 | On-glasses web | Not applicable |

Reading of the matrix: **only Halo and Mentra Live do all of (a)–(d)
from one device with an open SDK.** Everything Meta ships splits the
job — camera through a preview SDK, audio through generic Bluetooth —
and gates the SDK half by country.

---

## 5. Brilliant Labs

### Product lineup as of 2026-08-26

The store's own product feed lists **exactly one product**:

```
$ curl -s https://brilliant.xyz/collections/all/products.json
Halo | halo | [('Black', '399.00', True)]
```

- **Halo — $399 USD, in stock.**
  [brilliant.xyz/products/halo](https://brilliant.xyz/products/halo)
- **Frame — no longer sold.** `https://brilliant.xyz/products/frame`
  returns **404**. Documentation is still live at
  [docs.brilliant.xyz/frame/frame/](https://docs.brilliant.xyz/frame/frame/)
  and the SDKs still support it, but you cannot buy one from the
  vendor.
- **Monocle — no longer sold.**
  `https://brilliant.xyz/products/monocle` returns **404**.

**Shipping status is self-contradictory on the vendor's own page.**
The body copy says "The first Halo units are rolling off the
production line now, with shipments beginning in early August," while
the FAQ on the same page still says "Halo will begin shipping soon
🚀". Do not plan around either.

### Halo hardware

From the [product page FAQ](https://brilliant.xyz/products/halo): just
over 40 g; all-day battery at normal use; colour display; low-power
optical sensor for AI inference; **dual mics with audio activity
detection**; low-power AI processor; **dual bone-conduction
speakers**; fully open source.  IPD range 58–72 mm; display optic
adjustable +2 to −6 diopters. Firmware is Zephyr RTOS on an Alif
Balletto with an on-device Lua runtime and BLE OTA
([halo-firmware](https://github.com/brilliantlabsAR/halo-firmware)). Earlier
pre-order pricing of $299 and a 14 h runtime figure are
**[secondary]** ([Road to
VR](https://roadtovr.com/brilliant-labs-halo-smart-glasses-price-release-date/)).

### Halo on-device Lua API

From the [Lua API
Reference](https://docs.brilliant.xyz/halo/halo-sdk-lua/).

| Subsystem | What you get |
|---|---|
| **Camera** | JPEG only, **640 px only**. `capture{quality=...}` → `image_ready()` → `read(n)`. A 640 px frame is ~80 / 47 / 25 / 16 KB at VERY_HIGH → LOW. Optional libmpix pipeline (debayer, white balance, gamma, crop, resize) |
| **Microphone** | `start{encoder="pcm"\|"lc3", sample_rate=8000\|16000, gain=-10..10}`. On-device **AEC**, voice-band mode (~300–3400 Hz), and an **Audio Activity Detection** callback with a dB-SPL threshold — a hardware VAD, exactly what "hey, log this" needs |
| **Speaker** | `frame.speaker.start/play/volume/stop`. PCM or LC3 streamed from the host — this is your TTS path. Plus `frame.sound` effects |
| **Display** | 256×256 **round**, `0xRRGGBB`, no double-buffer (draws are immediate). `text`, `char`, `set_font`, `bitmap`, `line`, `rect`, `circle`, `polygon`, `clear` |
| **Input** | Button (single/double/long) and IMU tap (single/double/triple) |
| **Bluetooth** | `send` / `receive_callback`, `max_length()` = MTU−1. Bonds up to 5 hosts |

**The bandwidth catch, stated in the vendor's own BLE spec:** there
are no dedicated characteristics for camera or microphone. Both ride
the same `LUA RX` notify characteristic as `print()` output, via
`frame.bluetooth.send()`; only speaker audio has its own `AUDIO TX`
characteristic. MTU is up to 512 bytes ([Bluetooth
specs](https://docs.brilliant.xyz/halo/halo-sdk-bluetooth-specs/)). So
Halo does **snapshots, not video streaming** — design for one JPEG per
checklist step or per utterance.

### Halo / Frame SDKs

Monorepo:
[github.com/brilliantlabsAR/brilliant_sdk](https://github.com/brilliantlabsAR/brilliant_sdk),
which supersedes the older `frame_sdk` and ships migration guides from
it.

- **Flutter**
  ([docs](https://docs.brilliant.xyz/halo/halo-sdk-flutter/)) —
  [`brilliant_ble`](https://pub.dev/packages/brilliant_ble),
  [`brilliant_msg`](https://pub.dev/packages/brilliant_msg) (images,
  streamed audio, rasterised text), the
  [`brilliant_sdk`](https://pub.dev/packages/brilliant_sdk)
  meta-package, and
  [`simple_brilliant_app`](https://pub.dev/packages/simple_brilliant_app)
  scaffolding. **This is the decisive one for Millia** — MOPS is
  already Flutter.
- **Python**
  ([docs](https://docs.brilliant.xyz/halo/halo-sdk-python/)) —
  `brilliant-ble` (Bleak-based, auto-detects `FRAME` vs `HALO`,
  `send_audio()`), `brilliant-msg`, and `halo-emulator` (see §2).
- **Web Bluetooth** — examples + TypeDoc at
  [brilliantlabsar.github.io/brilliant_sdk](https://brilliantlabsar.github.io/brilliant_sdk/).
- Legacy:
  [frame-sdk-python](https://github.com/brilliantlabsAR/frame-sdk-python).

### Frame (for the record — not purchasable)

From the [hardware
manual](https://docs.brilliant.xyz/frame/hardware/): Omnivision
**OV09734** camera, captured 1280×720 RGB cropped to **720×720**
YCbCr; 0.23″ micro-OLED **640×400** at 20° FOV, max 16 colours per
frame; single TDK **ICS-41351** MEMS mic, 4–16 bit, 4–20 kHz; two 105
mAh Li-ion cells.

**No speaker — confirmed two ways.** The hardware manual contains zero
occurrences of "speaker" or "audio"; and the [Frame Lua
API](https://docs.brilliant.xyz/frame/frame-sdk-lua/) namespace list
is `bluetooth, camera, compression, display, file, imu, microphone,
time` — there is no `frame.speaker`.  Brilliant's own Frame-vs-Halo
table lists Frame's audio output as "—".

### Monocle (retired) **[secondary, and dated]**

The review the manager supplied —
[blog.learnxr.io](https://blog.learnxr.io/extended-reality/brilliant-labs-monocle-review)
by Dilmer Valecillos — is a **secondary source from August 2023**,
three years stale, describing a product no longer sold. Its specs: 15
g, 720p (5 MP) camera, 640×400 OLED at 20° FOV, BLE 5.0, **~1 hour
battery**, microphone, MicroPython, $349. Background only.

---

## 6. Meta

### Meta Wearables Device Access Toolkit

Announced 2025-09-18; developer preview opened **2025-12-04**
([announcement](https://developers.meta.com/blog/introducing-meta-wearables-device-access-toolkit/)).
Docs:
[wearables.developer.meta.com/docs/develop/dat/](https://wearables.developer.meta.com/docs/develop/dat/).
Android SDK:
[github.com/facebook/meta-wearables-dat-android](https://github.com/facebook/meta-wearables-dat-android).

**DAT is a *mobile app* SDK, not an on-glasses runtime.** Your code
runs on iOS (Swift) or Android (Kotlin); the glasses are a sensor
peripheral. There is no way to put a custom app on Ray-Ban Meta.

- **Camera (`MWDATCamera`)** — video stream plus `capturePhoto` during
  a stream.  `StreamConfiguration` accepts `frameRate` ∈ {2, 7, 15,
  24, 30} and resolution `high` **720×1280**, `medium` **504×896**,
  `low` **360×640**. Transport is **Bluetooth Classic** through the
  phone, with an automatic degradation ladder — resolution drops a
  step first, then frame rate, never below 15 fps — and adaptive
  per-frame compression, so a frame reported as `high` may still look
  poor.
- **Display (`MWDATDisplay`)** — **Ray-Ban Meta Display
  only**. FlexBox/Text/Image/Button/Icon and MP4 playback, rendered at
  **600×600**.
- **Microphone and speaker — not SDK surfaces.** "Use mobile platform
  functions to access the device over Bluetooth." **HFP** is
  bidirectional at **8 kHz mono** (with beamforming that deliberately
  suppresses everyone but the wearer); **A2DP** is output-only at
  44.1/48 kHz stereo and is the right choice for TTS. **The two are
  mutually exclusive** — starting HFP drops output to 8 kHz mono for
  the session. Combining HFP with a DAT camera stream requires HFP to
  be configured *before* the stream starts.
- **Sessions** — one at a time per device; the wearer pauses/stops by
  tapping, removing the glasses, or closing the hinges. Registration
  is a one-time deeplink into the **Meta AI app**.
- **Mock Device Kit** — see §2.

Supported devices: Ray-Ban Meta (Gen 1 and Gen 2), Ray-Ban Meta
Optics, Ray-Ban Meta Display, Oakley Meta HSTN, Oakley Meta Vanguard.

**Gates.** Developer Mode is enabled by tapping the Meta AI app
version number five times.  "Developer Preview means you can build and
test experiences, but you cannot yet distribute them to end users" —
publishing is unavailable except to select partners
([FAQ](https://developers.meta.com/wearables/faq/)). **App Store
submission is not supported**: the SDK uses `ExternalAccessory`, which
triggers Apple MFi/privacy-manifest rejection. And full capabilities,
including the Wearables Developer Center, are restricted to supported
countries.

### Meta Ray-Ban Display "Web Apps"

A separate product journey: HTML/CSS/JS hosted over HTTPS, running
**on** Ray-Ban Display, fixed **600×600** viewport on an additive
waveguide (dark backgrounds; light is opaque), navigated with the
Neural Band and temple swipe. Available APIs at launch:
`DeviceMotionEvent`, `DeviceOrientationEvent`, `navigator.geolocation`
(phone GPS), `localStorage`/`sessionStorage`. Explicitly **no camera,
no microphone, no text input, no offline, no notifications**
([FAQ](https://developers.meta.com/wearables/faq/)). Dead end for this
brief.

### Availability and price

See §3 — none of the team's six countries is supported. US pricing on
[meta.com/ai-glasses](https://www.meta.com/ai-glasses/) starts at
**$224** for the entry Ray-Ban Meta configuration; per-model prices
could not be extracted from the client-rendered page **[unverified]**.
Malaysian grey-market listings sit at roughly **RM1,999–2,299**
**[secondary]**.

---

## 7. Other Options

One line each; dev access and price only.

- **Mentra Live — $449 USD, in stock** ([mentra.glass products
  feed](https://mentra.glass/products.json); Single Vision RX lens
  $349). Camera glasses, **no display**. The [MentraOS Miniapp
  SDK](https://docs.mentra.glass/) (beta, `@mentra/miniapp`) plus a
  Bluetooth SDK for Android/iOS/React Native document **camera
  photos/videos/streaming, microphone, speaker, transcription and
  translation** as first-class APIs — on paper the richest SDK surface
  here, and the closest fit to the checklist use case after
  Halo. Ships from the US; **transit to Asia [unverified]**, which is
  the reason it ranks below Halo for this team.
- **Even Realities G1 / G2**
  ([evenrealities.com/g1](https://www.evenrealities.com/g1)) —
  display-only HUD eyewear, iOS + Android companion app. **No
  camera**, which kills the CV verdict half of every use case in
  §8. No public developer SDK found on the official site
  **[unverified]**.
- **Vuzix M400**
  ([vuzix.com](https://www.vuzix.com/products/vuzix-m400-smart-glasses))
  — monocular **Android** device, so you can side-load a normal APK:
  the lowest-effort "our own app running on the glasses" path in this
  list. Price not extractable from the storefront **[unverified]**;
  historically enterprise-tier **[secondary]**.
- **RealWear Navigator 500**
  ([realwear.com](https://www.realwear.com/navigator-500/)) —
  industrial, voice-first, Android, purpose-built for noisy hands-busy
  frontline work. The most *product-appropriate* device in the survey
  and the least hackathon-appropriate: demo-request gated, no public
  price, no walk-in purchase **[unverified]**.
- **Xreal** ([xreal.com](https://www.xreal.com/us/dev)) — tethered
  display glasses; no forward-camera story for this use case. Dev page
  returned no extractable content **[unverified]**.

---

## 8. Use Cases for Millia

Cleaner-first, ranked by 3-day feasibility. Every one is provable on
the §2 simulator — that is the point of the simulator.

| # | Use case | Millia pipeline it rides | Feasibility |
|---|---|---|---|
| 1 | **Checklist step read aloud, advanced by voice** ("done", "next", "skip") — the cleaner never touches a wet phone | checklist template snapshots on the cleaning task | **Highest.** The core of the demo |
| 2 | **Photo proof captured hands-free at the right moment**, then the **CV verdict spoken back**: "mirror has water spots, redo step 4" | per-step `cv_prompt` → `inspection_specialist` typed actions (dismiss / queue_redo / create_maintenance_task / flag_for_human_review) | **Highest.** Pipeline already exists; glasses add only camera + TTS |
| 3 | **"Report: broken lamp"** → spoken report + photo becomes a `maintenance` task in the MOPS chat thread, unit resolved from context | `task_expert` → `create_task` → `tasks`; MOPS reads via `get_maintenance_tasks_rpc` | **High.** The second demo beat |
| 4 | **Live multilingual relay** — the same step spoken in bn / ms / km; the cleaner replies in their language, the thread records English | MOPS already ships en/bn/ms/km i18n | **High**, and the most persuasive beat on stage |
| 5 | **Hands-free Start Work / Complete** — the FSM's only door out of `pending` is Start Work; say it instead of tapping | v5 status machine, role-gated | **High.** Small, and it makes the whole thing feel real |
| 6 | **Guest request read aloud in-room** — an inbound GR reaches the cleaner where they stand | `guest_request` task thread + push deep-link | **High.** Notification → TTS |
| 7 | **Redo loop closed on the spot** — a failed verdict re-reads the failed step and re-shoots without leaving the room | inspection redo path | **Medium.** Pure orchestration on top of #1 and #2 |
| 8 | **Glance-to-identify inventory** — point at an appliance, hear its service history / last AC service date | digital-twin `area_items` (AC servicing lives here, not in `tasks`) | **Medium.** Needs recognition or a QR/label crutch — use the room's existing labels |
| 9 | **Photo-verified checkout capture** — key photo, meter reading, minibar state, captured where the eyes already are | checkout key-photo flow | **Medium** |
| 10 | **Escalation heard, not missed** — rings the wearer's ear directly; "on my way" acknowledges by voice | escalation ladder; event line "Escalated to {name} by System" | **Medium.** Depends on push plumbing more than on glasses |
| 11 | **Supervisor sees what the cleaner sees** — live first-person stream during a disputed inspection | new surface; needs real streaming | **Low.** Halo can't stream (snapshots only); DAT can but is region-gated. **Cut it** |

Two things worth saying to the CEO: nothing here is a new AI
capability — **every one of these pipelines already exists in
Millia**, and the checklist-plus-CV one was built by this same
developer.  The glasses are a new input/output surface on work the
backend already does, which is exactly why it can be demoed in three
days. And #4 is the one a hotel operator will actually pay for.

---

## 9. What Could Not Be Verified

- **Halo transit time to Japan, Korea, Singapore, Malaysia or the
  Philippines.** No shipping-policy page exists
  (`/policies/shipping-policy` → 404). The Shopify checkout accepts
  and validates addresses in all five (Cambodia was inconclusive), and
  the shop's country code is HK, but the rate endpoint returns nothing
  for an empty cart so **no rate or ETA was confirmed**. The product
  page also **contradicts its own FAQ** on shipping status — treat any
  arrival date as unknown until there is a tracking number.
- **Whether Meta's Mock Device Kit is usable from the Philippines or
  Japan.** MDK simulates the full SDK stack including registration, so
  it plausibly bypasses the Meta AI app gate — but the Wearables
  Developer Center that hosts the SDK is itself region-gated, and
  nobody has tested this. **This is the highest-value unknown if
  anyone wants a Meta path**; it costs one afternoon to settle.
- **Whether a non-supported-country Meta account can complete DAT
  registration against imported glasses.** The FAQ says such
  developers lose "full capabilities", but does not say basic
  Developer-Mode registration fails.
- **Per-model Meta pricing.** Only a `$224` entry price was
  extractable; Ray-Ban Meta Display, Oakley HSTN and Vanguard prices
  unconfirmed from a primary source.
- **Grey-market Ray-Ban Meta availability in Japan, Korea, Singapore
  and Cambodia.** Only Malaysia was checked, and only via
  search-result summaries of Lazada/Carousell/Facebook listings
  (RM1,999–2,299) — not a fetched vendor page. **[secondary]**
- **Singapore's status.** Meta's supported-country list omits
  Singapore, yet `meta.com/sg/ai-glasses/` serves a live regional
  page. Contradictory; do not plan a Singapore purchase run on it.
- **Mentra Live shipping to Asia**, Vuzix M400 price, RealWear
  Navigator 500 price, Even Realities SDK existence, Xreal developer
  access, and any MentraOS hardware emulator — all unconfirmed.
- **Halo battery runtime.** The official page says only "all-day
  battery life at estimated normal use"; the 14-hour figure is
  **[secondary]**.

---

## 10. Verification Pass — Asian and Other Vendors (2026-08-26)

A second sweep aimed at the CTO's actual buying geography (Japan, Korea,
Singapore, Malaysia, Cambodia) plus every 2025–26 AI-glasses vendor with a
plausible SDK. Same rules as the rest of this document: a fetched URL per
claim, or the claim is tagged.

| Vendor / model | Camera | Mic | Speaker | Display | Open SDK | Bridge or standalone | Price | Buyable JP/KR/SG/MY/PH | Source |
|---|---|---|---|---|---|---|---|---|---|
| **Rokid Glasses** (RV101) | 12 MP, 3024×4032, 3K30 video | 4-mic array | Dual linear speakers | 480×400 green Micro-LED, 30°, 1500 nit | Portal exists, contents **[unverified]** | Standalone Android (SD AR1, 32 GB) **[secondary]** | **$699** (from $799), in stock | "Ships to most countries"; `ja-jp` storefront live | [global.rokid.com](https://global.rokid.com/products/rokid-glasses) |
| **RayNeo X3 Pro** | 12 MP Sony IMX681 + spatial cam, 4K | 3-mic beamforming | Not in spec table **[unverified]** | 640×480 full-colour Micro-LED, 30°, 3500 nit | "Developer Mode: Creator Mode with **Unity ARDK / Android ARDK**" | Standalone Android (SD AR1) | $1,099 — **Sold Out** | Store origin HK; item unavailable | [rayneo.com](https://www.rayneo.com/products/x3-pro-ai-display-glasses) |
| **INMO GO3** | Yes (photos, 60 s video) | Yes, 360° pickup | **No** — audio via phone or $49 INMO Speaker | Yes, on-lens | None found (`/pages/developer` → 404) | Phone companion app (iOS/Android) | $599 | Seller is INMO International, Wan Chai **Hong Kong** | [inmoxr.com](https://www.inmoxr.com/products/inmo-go3) |
| **Solos AirGo V2** | **Yes** — video streaming + recording | Yes | Yes (open-ear) | **No** | Official iOS/Android SDK (camera + mic + sensors + touch, BLE control / Wi-Fi data) but **gated behind a US$1,999 kit currently marked "Unavailable"** | Phone bridge | $299 glasses / **$1,999 SDK kit** | Shop origin HK; storefront offers **only United States (USD)** | [solosglasses.com/pages/developers](https://solosglasses.com/pages/developers) |
| **Snap SPECS 27** | Yes — `CameraModule` frame + still API | Yes | Stereo speakers | Yes | Lens Studio / Snap OS only — **not drivable from Flutter** | On-glasses Lens | **$2,195**, refundable deposit | Pre-order gated per country; **ships Fall 2026** | [specs.com](https://www.specs.com/smart-glasses/specs-27) |
| **Android XR glasses** | n/a | n/a | n/a | n/a | SDK at **Developer Preview 4** | n/a | n/a | **Not purchasable — "coming soon"** | [android.com/xr](https://www.android.com/xr/) |
| **Vuzix M400** | 13 MP, 1080p60 | 3 noise-cancelling | Speaker (97 dB) | nHD OLED monocular | Android 13 → sideload a normal APK | Standalone | **$1,499.99** | Shipping to Asia **[unverified]** | [vuzix.com](https://www.vuzix.com/products/m400-smart-glasses) |
| **Vuzix Z100** | **No camera** on the base config | Yes | Yes | Ultralite monochrome waveguide | **Yes** — `Vuzix/ultralite-sdk-android` + iOS, live on the official org | Phone bridge | No consumer SKU on the live store | Now the **"Ultralite OEM Platform"** — partner programme, not a product | [vuzix.com](https://www.vuzix.com/products/vuzix-z100-smart-glasses), [github.com/Vuzix](https://github.com/Vuzix) |
| **RealWear Navigator 520** | 50 MP | 4-mic ANC array | Dual 94 dBA | Yes | **Yes** — public dev programme + [github.com/realwear](https://github.com/realwear) | Standalone Android | **$3,150** | Demo/quote gated **[unverified]** | [shop.realwear.com](https://shop.realwear.com/products/realwear-navigator-520) |
| **Looktech** / **Loomos** / **Halliday G2** | 13 MP / 16 MP / **none** | Yes | Yes | No / No / "DigiWindow" | **None found** for any of the three | Phone app | $249 / n-a / $599 | **[unverified]** | looktech.ai, loomos.ai, hallidayglobal.com **[secondary]** |
| **Xiaomi AI Glasses** | 12 MP IMX681 | 5-mic | Yes | **No** | None found | Phone app | ¥1,999 **[secondary]** | China only **[secondary]** | mi.com returns **403**; [gizmochina](https://www.gizmochina.com/2025/06/26/xiaomi-launches-its-first-ai-glasses-with-2k-video-recording-voice-assistant-and-a-1999-yuan-price-tag/) **[secondary]** |
| **Alibaba Quark S1 / G1** | S1: 12 MP, 3K | **[unverified]** | **[unverified]** | S1 waveguide; G1 none | None — MCP support promised "in future" | — | ¥3,799 / ¥1,899 **[secondary]** | China only **[secondary]** | [ithome](https://www.ithome.com/0/900/714.htm) **[secondary]** |
| **Baidu Xiaodu Pro** | Yes | 4-mic | Open-ear | No | None found | Phone app | ¥2,299 **[secondary]** | China only (JD/Tmall) | [technode](https://technode.com/2024/11/13/baidu-unveils-xiaodu-ai-glasses-its-first-ai-glasses-powered-by-a-large-language-model/) **[secondary]** |
| **Meizu StarV Air2** | **Contradictory** — absent from Meizu's own spec page | **[unverified]** | **[unverified]** | 640×480 Micro-LED, 30° | None found | Flyme XR 2.0 | ~$489 **[secondary]** | **[unverified]** | [meizu.com](https://www.meizu.com/global/product/starv-air2/specs) |
| **Huawei AI Glasses** | 12 MP | Yes | Yes | **No** | None found | HarmonyOS phone | ¥2,499 **[secondary]** | China launch only **[secondary]** | press only, **[secondary]** |
| **Lenovo AI Glasses** | ~2 MP concept | — | — | No | **Concept only, CES 2026** | Needs a phone | No price | Not shipping | press only, **[secondary]** |

### Notes per vendor

**Rokid Glasses** is the strongest new find. The spec table on the official
product page confirms all four capabilities in one 49 g device — 12 MP camera,
4-mic array, **dual linear speakers**, and a 480×400 binocular Micro-LED
display — for **$699, in stock**, with "Rokid ships to most countries and
regions" and a live `ja-jp` storefront (`global.rokid.com/ja-jp/products/rokid-glasses`
returns 200). The catch is the SDK: `developer.rokid.com` and `ar.rokid.com/developer`
both redirect to **open.rokid.com**, which is entirely JS-rendered — the page
body is the string "Rokid AR Platform" and nothing else, so **no SDK capability
list, no pricing, no registration terms could be extracted [unverified]**. The
official `github.com/rokid` org is alive (`armazpro-module-sdk-sample`, pushed
2026-08-14) but has nothing for this model; `github.com/RokidGlass` is stale
(2023). A GitHub search does return a dense cluster of *third-party* Rokid
Glasses apps updated within the last week — camera+mic streaming, HUD apps,
plugin platforms, a "CXR-L SDK" agent skill — which is strong practical evidence
that on-glasses Android apps are possible, but it is community, not vendor,
evidence **[secondary]**.

**RayNeo X3 Pro** would be the other candidate and is **sold out** at $1,099
(`/products/x3-pro-ai-display-glasses.js` → `available: false`), which settles
it for a 3-day build. Worth recording anyway: its own spec table names
"Developer Mode: Creator Mode with **Unity ARDK / Android ARDK**" on a
Snapdragon AR1 — the clearest vendor-stated on-glasses SDK in this pass —
and `rayneo.com/pages/developer` redirects to a real **open.rayneo.com** portal
(also JS-only, no extractable content). The store's Shopify origin is **HK**.

**INMO** ships only the **GO3** internationally — `inmoxr.com/collections/all`
lists the GO3 ($599) and accessories, nothing else; Air 3 and GO 2 are not on
the international store. It has a camera and an on-lens display, but the page
states audio is "spoken aloud through your phone speaker or INMO Speaker" (a
separate $49 accessory), so **there is no speaker in the glasses** — which
fails the hands-free-TTS half of every §8 use case. No developer page exists.

**Solos AirGo V2** looked like the bargain of the sweep and is not.
`solosglasses.com/pages/developers` documents a real **Solos Smartglasses SDK**
for iOS and Android exposing "on-device sensors, microphones, touch, and the
camera" over BLE control + Wi-Fi data, with video APIs on V2 — but the same page
prices access as an **SDK Developer Program kit at US$1,999**, listed
**"Unavailable"**, not as a free download. The glasses alone are $299; the SDK
is not. Add no display and a storefront whose only selectable market is
**United States (USD)** (Shopify country code HK), and it is out for a 3-day
build.

**Snap** has moved to `specs.com`: SPECS 27 is **$2,195**, pre-order with a
refundable deposit, "expected to ship starting **Fall 2026**", and the cart is
hidden in countries where pre-order is not open. The camera API is real and
well documented (`CameraModule.requestCamera` / `requestImage`), but it is
Lens Studio TypeScript running inside Snap OS — a Flutter app cannot drive it.
Dead on both timeline and integration path; the older 5th-gen Spectacles
Developer Program at $99/month covered the US and six European countries and has
**no 2026 primary re-confirmation [unverified]**. **Android XR** is the same
story without the hardware: SDK at Developer Preview 4 and **emulator-only for
glasses form factors**, Samsung's Galaxy Glasses announced as **audio-only, no
display**, "later this fall" 2026, no market named **[secondary]**. **Vuzix
Z100** is no longer a purchasable product — that URL now serves the "Ultralite
OEM Platform" page — but its SDK genuinely is open (`Vuzix/ultralite-sdk-android`
and the iOS twin on the official org, alongside `sdk-speechrecognitionservice`
pushed 2026-08-13); the base config has **no camera**, which ends it here.
**RealWear Navigator 520** ($3,150) is the only device found with a mature
public developer programme *and* a real GitHub org — and it is five times
Halo and quote-gated. **Vuzix M400** remains the easiest
"our own APK on the glasses" path (Android 13, 13 MP, speaker, 3 mics) at
**$1,499.99**, four times Halo's price for a device with a 16.8° monocular
display.

### Does this change the recommendation?

**Not the plan, but the hardware ranking, yes.** Halo ($399) still wins on
price plus a documented Flutter path, and Mentra Live ($449) still has the
richest SDK surface. What changed is the middle of the list. **Rokid Glasses
displaces Mentra Live as the second hardware bet**: it is the only device found
in either pass that has camera + mic + **speaker** + display in one frame, is
**in stock today**, and ships from a store with a live Japanese storefront —
which directly answers §9's open question about getting a device into the CTO's
hands in Asia. Its one hole is the exact hole Halo does not have: the SDK is
behind a JS-only portal nobody has read, so "a Flutter app can drive it" is
**[unverified]**. Concretely: if Jason is in Japan, ordering a Rokid ($699)
alongside the Halo ($399) buys a second, independent chance at real hardware on
stage for less than the price of one M400. **No new cheap insurance emerged**:
Solos AirGo V2's glasses are $299 but its SDK is a $1,999 kit currently marked
unavailable. Everything else verified here is disqualified for this hackathon:
RayNeo sold out, Snap ships Fall 2026 and is Lens-Studio-only, Android XR has no
device and is emulator-only, Vuzix Z100 is now an OEM programme with no camera,
RealWear is $3,150 and quote-gated, and every Chinese vendor (Xiaomi, Quark,
Xiaodu, Huawei) is China-market-only with no public SDK. **The phone-simulator-first plan in §1 is
unaffected and remains the deliverable.**

### Not verified in this pass

- **Rokid's SDK surface and terms.** `open.rokid.com` renders nothing to a
  plain fetch. Whether a third-party app can read the camera and write the
  display, and whether registration is region-gated, is unknown.
- **RayNeo's ARDK.** Named in the vendor spec table; `open.rayneo.com` is
  equally JS-only, so its actual APIs were never read. Moot while sold out.
- **Whether Solos ships to any of the five countries.** Its shipping page names
  Hong Kong and a generic "100+ countries" tier; none of JP/KR/SG/MY/PH is
  named, and the storefront only offers the US market.
- **Whether the $1,999 Solos SDK kit can be bought at all** — the listing says
  "Unavailable".
- **Rokid, RayNeo, INMO and Vuzix transit times** to any of the five countries.
  No rate or ETA was fetched for any of them — same gap as Halo in §9.
- **RayNeo X3 Pro speaker.** Absent from the spec table; not confirmed either way.
- **Snap's current Spectacles Developer Program price and country list**, and
  whether SPECS 27 pre-order is open anywhere in Asia (US/UK/France confirmed).
- **Samsung Galaxy Glasses price, ship date, camera specs and launch markets** —
  all press-sourced.
- **Vuzix M400 and RealWear country-level availability in Asia.** Vuzix names an
  APAC distributor in its own IR release but enumerates no countries.
- **Meizu StarV Air2's camera** — Meizu's own spec page omits it while retail
  listings claim one. Unresolved.
- **Xiaomi, Quark, Xiaodu and Huawei specs and prices** are press-sourced only;
  `mi.com` answers HTTP 403 to a plain fetch and no official Xiaomi, Alibaba,
  Baidu or Huawei product page was successfully read.

### Correction (2026-08-26, later the same day)

`open.rokid.com` is JavaScript-rendered; a plain fetch returned only the page title, which
this pass recorded as "no SDK could be read". Loaded in a browser it links a public SDK
overview at [developerdoc.rokid.com/sdk](https://developerdoc.rokid.com/sdk?lang=en):

- **CXR-L SDK** (Android + iOS, v1.0.4, updated 2026-06-25, public, Maven
  `com.rokid.cxr:client-l:1.0.4`) — runs on the phone through the Rokid AI App (≥1.9.0
  mainland) or "Hi Rokid" (overseas): auth token, CustomView (layout JSON + icons) /
  CustomApp sessions, **PCM audio stream**, **remote JPEG photo capture**, bidirectional
  custom commands (CustomApp only), brightness and volume 0–15. No audio-out / TTS call in
  its capability table.
- **Bare-metal development** (v1.0.0, updated 2026-06-05, public) — a standard Android app
  on the glasses (YodaOS-Sprite, Android 12 Go, API 31, minSdk 31): 480×640 single-green
  display via Compose/Views, temple key + touch panel, **8-channel raw audio via
  `AudioRecord`**, **photo/video via CameraX**, 6-axis IMU. Debug needs a dedicated dev cable
  plus the Rokid AI App to enable glasses ADB. Sample `GlassesBareDevSample`.
- **CXR-M SDK** (Android, v1.1.0) — business-only via Glasses.BD@rokid.com: real-time
  audio/video streaming, Wi-Fi P2P, glasses-side custom pages, **TTS**, push, custom
  commands; cannot coexist with the Rokid AI App.
- Separate: **Rokid Sprite Enterprise SDK** for Glass3 Enterprise at
  [x-docs.rokid.com](https://x-docs.rokid.com/docs/en/) (glasses SDK + phone SDK + cloud
  OpenAPI), and **AIUI** ([js.rokid.com](https://js.rokid.com/AIUI/guide/runtime-js?lang=en-US)),
  a JS agent framework for AR glasses.

Ranking unchanged: Halo first (price, Flutter package, open source), Rokid second with the
strongest hardware and a public SDK. Still unverified: speaker playback from CXR-L (no
audio-out call listed), and whether the Rokid AI App / Hi Rokid is available in every store
region.
