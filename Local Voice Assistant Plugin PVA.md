# Local Voice Callouts Plugin — Plan of Approach

## Problem

RotorHazard uses browser TTS for spoken race callouts. In Chrome, some voices are remote services that silently fail when the race network has no internet access, while beeps and MP3 sounds continue to work. The goal is to move spoken callout generation to a fully local speech service running server-side.

## Concrete Goal

An RHAPI-only RotorHazard plugin that:

- Listens to race events on the RotorHazard host (server-side Python only).
- Builds its own audio queue for voice callouts and indicator sounds.
- Uses Piper as the local TTS engine to generate speech fully offline.
- Caches generated WAV files so predictable race phrases do not need synthesis during critical moments.
- Sends audio to a Sendspin player on the local network as the primary output target.
- Requires no RotorHazard core changes.

**Not in scope:** replacing browser-finalized lap callouts (assembled in JS), injecting JavaScript into existing pages, or voice command input.

**Minimum Python version:** 3.12 (required by Sendspin).

---

## RHAPI Limitations

- Lap callouts are assembled in browser JS from `phonetic_data` using per-browser localStorage settings. A server-side plugin cannot intercept the final phrase.
- The plugin cannot edit the built-in Audio Control tab or disable browser TTS automatically on other clients.
- The plugin cannot inject JavaScript into existing RotorHazard pages.

Consequence: **duplicate prevention is operational**, not automatic. The operator must manually set Voice Volume to 0 on all regular RotorHazard browser clients when the plugin is active.

---

## Missing RH Features (Post-MVP wishlist for upstream)

Things that would make the plugin significantly easier or more capable, but don't exist in RotorHazard today. These are explicitly **Post-MVP** items: they are not required for Phase 2 or Phase 3 completion. Each item includes the ideal upstream fix and the current workaround.

### Race clock countdown events

**Problem:** No server-side events for race time warnings ("30 seconds remaining", "10 seconds remaining", etc.). The countdown is handled entirely in browser JS via a local timer.

**Ideal fix:** Add `Evt.RACE_CLOCK_WARNING` fired by the RH race thread at configurable thresholds (e.g. 60s, 30s, 10s remaining), with payload `{'seconds_remaining': int}`. This would let any plugin — not just audio plugins — react to race time milestones without reimplementing a parallel timer.

**Status: Post-MVP / deferred.** Not implemented in the plugin until RH provides a proper server-side event. Race clock callouts are skipped for now.

---

### Staging tone events

**Problem:** The staging beeps ("3... 2... 1...") before race start are generated in browser JS. There is no `Evt.RACE_ARM_TONE` or similar server event. Plugin cannot reproduce the countdown sequence without reimplementing the staging logic.

**Ideal fix:** Fire `Evt.RACE_ARM_TONE` from `RHRace.stage()` at each staging beep interval, with payload `{'tone_index': int, 'tones_remaining': int}`. This decouples the audio signal from the browser and lets server-side plugins (LED, audio, video) stay in sync with the actual staging sequence.

**Status: Post-MVP / deferred.** Not implemented in the plugin until RH fires server-side arm tone events. Staging beeps are skipped for now.

---

### Structured race-tied / overtime events

**Problem:** Race Tied and Overtime announcements go through `emit_phonetic_text()` with translated strings. There is no dedicated `Evt.RACE_TIED` or `Evt.RACE_OVERTIME`. The plugin must either hook `Flt.EMIT_PHONETIC_TEXT` and parse translated text (fragile), or inspect `win_status` inside `Evt.RACE_WIN`.

**Ideal fix:** Fire dedicated `Evt.RACE_TIED` and `Evt.RACE_OVERTIME` events from `check_win_condition()` in addition to the existing `Evt.RACE_WIN`. This mirrors the pattern already used for `Evt.RACE_PILOT_DONE` vs `Evt.RACE_WIN` and makes win outcome handling explicit for plugins.

**Status: Post-MVP / deferred.** Not implemented until RH fires dedicated events. Race Tied and Overtime callouts are skipped for now.

---

### Race leader callout via unified filter

**Problem:** `Evt.RACE_PILOT_LEADING` fires correctly, but the phonetic text is assembled in `emit_phonetic_leader()` and emitted as a separate `phonetic_leader` socket event — bypassing `Flt.EMIT_PHONETIC_TEXT`. Plugins that want to intercept all voice callouts must register a second filter (`Flt.EMIT_PHONETIC_LEADER`) separately.

**Ideal fix:** Route `emit_phonetic_leader()` through `emit_phonetic_text()` with a `domain='race_leader'` parameter, just like winner announcements use `domain='race_winner'`. This unifies all voice output behind a single filter point and makes `Flt.EMIT_PHONETIC_TEXT` truly the single interception point for audio plugins.

**Status: Post-MVP / deferred.** Not implemented until RH routes leader callouts through the unified `Flt.EMIT_PHONETIC_TEXT` filter. Race leader callouts are skipped for now.

---

## A. Local TTS Engine

### piper-tts Python package (MVP)

Install `piper-tts` from PyPI directly into the RotorHazard virtualenv. Call it in-process — no subprocess, no binary to locate.

```python
from piper import PiperVoice

voice = PiperVoice.load("en_GB-alan-medium.onnx")
with wave.open("out.wav", "wb") as f:
    voice.synthesize("Pilot 1, Lap 3", f)
```

**Pro:** no subprocess startup overhead, no binary path to manage, same install path as other Python dependencies.
**Model download:** the plugin downloads the selected voice model automatically from the Hugging Face `rhasspy/piper-voices` repository on first use (or when the model is changed). Models are cached in `~/rh-data/local_voice_cache/models/`. Internet is only needed once per model; race operation is fully offline after that.

**Supported languages:** English, Dutch, and German to start. Recommended default models: `en_GB-alan-medium` (English) and `nl_NL-mls-medium` (Dutch). The plugin setting shows a dropdown of available models; the operator picks one per installation.
**Mitigation for synthesis latency:** cache generated phrases by normalized text and synthesis parameters. The plugin pre-generates predictable pilot/lap phrases at heat load (`[name], Lap 1–15`). Real-time synthesis remains necessary for dynamic lap times and unexpected text.

### Wyoming Piper (upgrade path)

Piper as a persistent TCP service. Plugin sends text, receives WAV back. Can run on a separate LAN machine if the Pi is underpowered for synthesis.

**Recommendation:** start with the `piper-tts` Python package + WAV caching. Add Wyoming Piper as an optional backend in Phase 5.

---

## B. Audio Output — Sendspin

Sendspin separates a **server/source** (orchestrates streams, accepts audio input) from a **player/client** (receives audio, plays through a local audio device). The current plugin starts an in-process Sendspin server and streams generated WAV audio to connected clients on the local network. Named player targeting remains planned work.

```
RotorHazard plugin
  → generates WAV via Piper
  → Sendspin server/source
  → Sendspin protocol over LAN
  → Sendspin player (any device with a speaker: NUC, laptop, Pi, ...)
  → speaker / mixer
```

The Sendspin server can run anywhere — on the Pi itself, as a sidecar service, or in the cloud. The player runs on whatever device is connected to the speakers. These are deployment choices, not separate code paths. The plugin has one Sendspin integration; the operator configures where the server and players are.

### Sendspin server placement

**On the RotorHazard host (in-process or sidecar)**

Requires Python 3.12+ on the host. The simplest setup: everything local, no internet needed.

- In-process: plugin drives Sendspin directly (Python 3.12+ required in the RH virtualenv).
- Sidecar: Sendspin runs as a separate systemd service, plugin talks to it over local HTTP/WS. Useful when you cannot upgrade the RH Python environment or want to restart Sendspin independently.

**In the cloud**

Sendspin server runs on a VPS or Sendspin's own hosted service. The plugin sends audio over the internet (a mobile hotspot is enough). Anyone at the event can scan a QR code and hear callouts on their own phone — no dedicated audio device or PA needed.

```
RotorHazard plugin → internet → Sendspin cloud server → phone (QR code)
```

This works as a standalone setup for small events, or in parallel with a local player for events that have both a PA and want a spectator feed.

### Player placement

The Sendspin player can run on any device with an audio output: Intel NUC, laptop, Raspberry Pi, phone. The operator installs the Sendspin player daemon, names it (e.g. `Race Speakers`), and the plugin targets that name. Multiple players can be active simultaneously.

### Deployment examples

| Situation | Sendspin server | Player |
|---|---|---|
| Simple local setup, Python 3.12 on Pi | In-process on Pi | NUC or laptop at speakers |
| Existing Pi on Python 3.10/3.11 | Sidecar service on Pi | NUC or laptop at speakers |
| Small event, no PA | Cloud | Pilots' and spectators' phones via QR code |
| Full event setup | Local (for PA) + Cloud (for phones) | NUC at PA + any phone |


### Browser player: current implementation

The plugin-served browser player is now a Vite / Preact / TypeScript app in the root-level `player/` directory. It uses the official `@sendspin/sendspin-js` SDK for playback instead of maintaining custom WebAudio timing, buffering, correction, and reconnect logic in a hand-written HTML file.

The production build is written to `custom_plugins/local_voice/player/`, and the RotorHazard plugin serves that directory at `/player`. Operator-facing URLs therefore stay stable while the browser player is maintained as a normal frontend app.

#### Source and build output

```text
rh-local-voice/
  player/                         # Vite/Preact source app
    package.json
    package-lock.json
    vite.config.ts
    tsconfig.json
    index.html
    src/
      index.tsx
      style.css
  custom_plugins/local_voice/player/
    index.html                    # generated build output, served by plugin
    assets/...                    # generated build output
```

#### Current design

- Vite + Preact + TypeScript.
- Router: **No**. The app is a single runtime page served at `/player`; routing adds no value.
- Prerender / SSG: **No**. The app depends on WebSocket, WebAudio, user gestures, and runtime Sendspin state.
- ESLint: **Yes**. Realtime audio and connection-state code benefits from catching simple mistakes early.
- Build output: `custom_plugins/local_voice/player/`.
- Plugin route: `GET /player` returns the built `index.html`; static assets are served from the same directory.

#### Runtime dependency

```json
{
  "dependencies": {
    "@sendspin/sendspin-js": "^3.1.0"
  }
}
```

The app instantiates `SendspinPlayer` from `@sendspin/sendspin-js` and lets the SDK handle:

- Sendspin protocol handshake
- time sync
- reconnect behavior
- decoding / scheduling
- drift correction / resync
- volume and mute state

Player construction follows this shape:

```ts
new SendspinPlayer({
  baseUrl,
  playerId,
  clientName: "Local Voice Browser Player",
  codecs: ["pcm"],
  correctionMode,
  reconnect: {
    baseDelayMs: 1000,
    maxDelayMs: 15000,
    maxAttempts: Infinity,
  },
  onStateChange: updateUiFromSdkState,
});
```

`baseUrl` should be a HTTP(S) origin, not the websocket endpoint path. The UI accepts values like `localhost:8927`, `http://host:8927`, or `ws://host:8927/sendspin`, and normalizes them to the SDK `baseUrl` form before constructing `SendspinPlayer`.

#### Browser UI

- Connect / disconnect button.
- Server URL input, persisted in `localStorage`.
- Volume slider and mute toggle.
- Correction mode selector.
- Status states: disconnected, connecting, connected, playing, error; reconnect attempts are logged and shown as connecting.
- Compact sync diagnostics from `player.syncInfo` and `player.timeSyncInfo` for debugging browser hiccups.
- Activity log for connection events and SDK state changes.

The browser player should continue to avoid local audio scheduling code. Timing, correction, reconnects, and decoding belong in the Sendspin SDK.

#### Build / dev scripts

```json
{
  "scripts": {
    "dev": "vite --host 0.0.0.0",
    "build": "tsc --noEmit && vite build",
    "check": "tsc --noEmit",
    "lint": "eslint .",
    "preview": "vite preview --host 0.0.0.0"
  }
}
```

`vite.config.ts` uses a small `fromConfig()` helper and writes production output to `../custom_plugins/local_voice/player`.

#### Validation checklist

- [x] `npm run check` passes in `player/`.
- [x] `npm run build` emits `custom_plugins/local_voice/player/index.html` and assets.
- [x] RotorHazard `/player` route is implemented for the built app and static assets.
- [x] Hard refresh / clean localStorage computes a usable default URL from the current host.
- [x] Browser player connects to `aiosendspin` on `8927`.
- [x] Test phrase plays in sync with a native Sendspin player.
- [x] Stop button clears playback on native and browser players.
- [x] MacBook/browser hiccup does not create persistent delay after recovery.
- [x] Reconnect after Sendspin server restart works without page refresh.

### Known Sendspin risks to validate before race day

- **Public preview:** APIs may still change.
- **Browser/network hiccups:** validate the `/player` browser client on the actual race network and speaker device before relying on it for an event.

---

## Architecture

```
RotorHazard server
  └── Local Voice Plugin (Python 3.12+, RHAPI)
        ├── Event listeners
        │     Evt.HEAT_SET, CROSSING_ENTER/EXIT
        ├── Flt.EMIT_PHONETIC_DATA  (lap data snapshots)
        ├── Flt.EMIT_PHONETIC_TEXT  (server-originated text callouts)
        ├── Async audio queue (FIFO, priority levels)
        ├── TTS: piper-tts (in-process) → WAV cache
        │     ~/rh-data/local_voice_cache/tts/
        └── Sendspin output
              Variant A: in-process source
              Variant B: HTTP client → sidecar service
```

### Playback worker

- Single async worker, FIFO queue.
- Priority: Race Start / Winner / Interrupt > lap callouts > crossing beeps.
- Callouts expire after ~5 seconds — a stale lap callout should never play.
- Sendspin output appends queued WAVs to the active stream so normal lap callouts do not reset playback when another lap arrives.
- All synthesis is async; never blocks RotorHazard event handling.

### Audio cache

Cache path: `{model_name}/{sha1(normalized_text)}_{speed}_{noise}_{noise_w}.wav`

Current heat-load behavior:
- Clears ephemeral lap-time WAV files for the selected model.
- Pre-generates "[name], Lap [n]" for pilots in the selected heat, laps 1–15.
- Stores pre-generated lap phrases under `tts/<model>/precache/`.

---

## Integration with Built-In RotorHazard Audio

The plugin cannot take over the built-in Audio Control tab. The operating model is:

1. Install and enable the plugin.
2. Configure Piper in the plugin panel.
3. Run a Sendspin player on the device connected to the speakers and connect it to the RotorHazard host on port `8927`.
4. On every regular RotorHazard browser client: set Voice Volume to 0 and disable browser beeps if the plugin handles beeps.

**Built-in Audio Control → used only to silence browser clients**
**Plugin Audio Profile → planned place to decide what the speakers announce**

MVP plugin audio profile mirrors the familiar RH categories that can be implemented with current RHAPI hooks:
- Pilot callsign, lap number, lap time on/off
- Winner and pilot-finished callouts
- Crossing enter/exit beeps
- Voice volume, beep volume, speech speed, voice model

Post-MVP profile additions:
- Race clock callouts
- Staging tone beeps
- Race tied / overtime callouts
- Race leader callouts

---

## Plugin Settings

Implemented:
- Enable plugin audio: on/off
- Voice model selector: 12 models across English, Dutch, and German
- Speech speed, noise scale, phoneme width noise
- Test phrase field and quick button
- Play audio check quick button
- Stop audio quick button
- Clear TTS cache quick button
- Duplicate prevention warning for browser Voice Volume
- Model download/load status surfaced to UI as notifications

MVP planned / not implemented yet:
- Announcement options per component: Pilot Callsign, Pilot Lap Number, Pilot Lap Time — each selectable as Never / Always / Only on Non-Team/Non-Co-op Races. Use Python enums for option values.
- Output volume and beep volume in the plugin panel
- Pre-generate on heat load: on/off

Known issues / deferred fixes:
- Sendspin reconnect silence: after a client reconnects, no audio is heard until the next new stream; likely a stream state issue in `SendSpinServer`
- Speed setting effectiveness: speed=2.0 produces little noticeable change; investigate whether `length_scale` is being applied correctly or whether medium-quality Piper models simply have a narrow effective range

Post-MVP planned / not implemented yet:
- TTS engine selector: piper-tts / Wyoming Piper / disabled
- Wyoming Piper host and port
- Sendspin mode: in-process / sidecar / disabled
- Sendspin sidecar URL

---

## MVP Implementation Phases

The MVP is Phase 1 through Phase 3: local Piper synthesis, race-callout queueing, and local Sendspin/browser playback. A phase is done when every checkbox is ticked and the success criteria are met — not before.

Deferred RHAPI-dependent features, sidecar/cloud output, QR codes, Wyoming Piper, mDNS, and broader polish are tracked separately under **Post-MVP Phases**.

---

### Phase 1 — Foundation: Plugin Scaffold + Piper TTS

**Goal:** A working plugin that generates a valid WAV file from text using the `piper-tts` Python package. Proves the TTS pipeline and cache end to end.

#### Plugin structure
- [x] Create `custom_plugins/local_voice/__init__.py` with `initialize(rhapi)` entry point
- [x] Register a settings panel via `rhapi.ui.register_panel()`
- [x] Add "Enable plugin audio" toggle via `rhapi.fields.register_option()`
- [x] Add voice model selector setting (12 models: EN-GB, EN-US, NL, DE)
- [x] Add speech speed setting
- [x] Add "Test phrase" quick button via `rhapi.ui.register_quickbutton()`

#### piper-tts integration
- [x] Add `piper-tts` to plugin dependencies
- [x] On first use (or model change): auto-download selected voice model from Hugging Face into `~/rh-data/local_voice_cache/models/`
- [x] Handle download failure with a clear error message (status logged; no panel field — see note below)
- [x] Load `PiperVoice` lazily on first synthesis; reload when the model changes
- [x] Synthesize text to WAV using `voice.synthesize_wav(text, wav_file, syn_config)` (piper-tts >= 1.4 API)
- [x] Handle synthesis errors gracefully (log, skip, no crash)

#### Audio cache
- [x] Create cache directory: `~/rh-data/local_voice_cache/tts/`
- [x] Cache key: `{sha1(normalized_text)}_{speed}_{noise}_{noise_w}.wav` under a per-model directory
- [x] On cache hit: return existing WAV path, skip synthesis
- [x] On cache miss: synthesize, write to cache, return WAV path

#### Event hook
- [x] Register `Flt.EMIT_PHONETIC_TEXT` handler
- [x] Schedule intercepted callout text for synthesis/playback to verify hook fires correctly
- [x] Hook does not modify or block the callout payload

#### Status display
- [x] Status logged via RotorHazard logger (visible in RH log panel)

**Success criteria:**
- [x] Clicking "Test phrase" generates a WAV in the cache directory with correct size and a valid WAV header
- [x] Second click on "Test phrase" returns the cached file without re-synthesizing (log confirms cache hit)
- [x] `Flt.EMIT_PHONETIC_TEXT` handler is registered and schedules text callouts without modifying the payload
- [x] Model not found / download failure logs a clear status and does not crash RotorHazard

---

### Phase 2 — Race Events + Audio Queue

**Goal:** Lap/text callout filters are wired. Async queue has priority and expiry. Pilot phrases are pre-cached on heat load.

#### Current callout inputs
- [x] `Flt.EMIT_PHONETIC_DATA` → "Pilot [callsign], Lap [n]" + optional lap time
- [x] `Flt.EMIT_PHONETIC_TEXT` → server-originated text callouts via TTS
- [x] Winner callouts are covered and manually validated through `Flt.EMIT_PHONETIC_TEXT` (`domain='race_winner'`, `winner_flag=True` gets high priority)
- [x] `Evt.HEAT_SET` → clear ephemeral lap-time WAVs + pre-cache pilot phrases for the loaded heat
- [x] `Evt.DATABASE_RESET` → clear event-specific `tmp/` and `precache/` WAVs after Archive/New Event or Clear Data Only

#### Async audio queue
- [x] Single `queue.PriorityQueue` with a dedicated daemon worker thread (`audio_queue.py`)
- [x] `AudioJob` dataclass: `text`, `wav_paths`, `priority`, `expires_at`
- [x] Priority levels: `HIGH` (race start / winner / interrupt) > `NORMAL` (lap callout) > `LOW` (beep)
- [x] Expiry: drop jobs where `time.monotonic() > expires_at` (default: 5 seconds)
- [x] Lap callouts use a 10-second expiry to tolerate multiple pilots crossing together while still dropping stale audio
- [x] Single worker draining the queue in priority order; expired jobs dropped and logged
- [x] Sendspin appends queued WAVs to the active stream; normal lap callouts do not intentionally stop/reset current playback

#### Audio profile settings
- [x] All implemented toggles exposed in plugin settings panel

#### Heat-load cache handling
- [x] Hook into `Evt.HEAT_SET`
- [x] Clear ephemeral lap-time WAV files when a heat loads
- [x] Pre-synthesize "[name], Lap [n]" for all pilots in the loaded heat (n=1–15)
- [x] Pre-caching runs in the synth thread pool; does not block heat load or event handling
- [x] Log how many new WAVs were generated and how long it took

#### Duplicate prevention UI
- [x] Plugin panel shows two separate markdown warnings (Voice Volume + browser beeps)

#### Error handling
- [x] Piper fails → log error with phrase text, skip callout, continue
- [x] Event handler never raises an unhandled exception
- [x] No race event is delayed or dropped because of plugin audio work

**Success criteria:**
- [x] A full simulated race (stage → start → laps → winner → stop) produces the correct callouts in the log
- [x] Pilot names and lap numbers are pre-generated when a heat loads; generation time logged
- [x] Piper crash mid-race does not affect RotorHazard timing or results
- [x] Expired callouts are dropped and logged, never played late

---

### Phase 3 — Sendspin Integration

**Goal:** Audio leaves the Pi and plays on a remote browser player via Sendspin. Local Pi playback is retired as the primary path.

#### Sendspin source setup
- [x] Add `aiosendspin` to plugin dependencies; keep server-only extras explicit in `manifest.json` (`av`, `numpy`, `pillow`) because RotorHazard plugin install flows may not preserve extras reliably
- [x] Sendspin source/server starts when plugin initializes
- [x] Sendspin source accepts WAV input from the plugin audio queue worker
- [x] In-process mode: plugin drives `aiosendspin` directly (Python 3.12+)

#### Test phrase through Sendspin
- [x] Test button sends phrase through the full stack: Piper → cache → in-process `aiosendspin` → connected player(s)

#### Browser player rewrite
- [x] Browser player served at `/player`
- [x] Root-level `player/` Vite/Preact app scaffolded
- [x] Add `@sendspin/sendspin-js` to the root-level player app
- [x] Configure Vite build output to `custom_plugins/local_voice/player/`
- [x] Replace template UI with `SendspinPlayer`-based app
- [x] Add compact diagnostics for sync drift, correction mode, reconnects, and player state
- [x] Plugin panel links to `/player`; live connection state is owned by the browser player UI, not the RotorHazard settings panel

**Success criteria:**
- [x] "Test phrase" plays audibly through the browser player on a remote device
- [x] Back-to-back lap callouts play without an audible stream reset
- [x] Browser player disconnect does not crash the plugin
- [x] Disconnecting and reconnecting the browser player recovers playback automatically

---

## Post-MVP Phases

Post-MVP work starts after the local MVP is race-day usable: full local race callouts, caching/pre-generation, in-process Sendspin, and browser player playback. This section includes upstream-dependent RotorHazard features, deployment modes, live status polish, and formal latency measurements that are useful but not required for the first stable release.

---

### Phase 4 — Deferred RH Features, Sidecar, Cloud, and QR Code

**Goal:** Track RHAPI-dependent callouts outside the MVP, and let Sendspin run as an independent sidecar service or cloud path for spectator/pilot phone feeds.

#### Deferred RH / RHAPI-dependent callouts
- [ ] `Evt.RACE_PILOT_DONE` → "[callsign] finished"
- [ ] Race clock callouts via upstream `Evt.RACE_CLOCK_WARNING`
- [ ] Arm sequence countdown beeps via upstream `Evt.RACE_ARM_TONE`
- [ ] Last-5-seconds countdown beeps (one `stage.wav` per second for the final 5s) and `buzzer.wav` at race end — mirrors browser behaviour; needs per-second `Evt.RACE_CLOCK_WARNING` thresholds (5, 4, 3, 2, 1) or a dedicated end-of-race countdown mechanism
- [ ] Scheduled race start callouts ("Next race begins in 30 seconds" etc.)
- [ ] Race tied / overtime via upstream `Evt.RACE_TIED` / `Evt.RACE_OVERTIME`
- [ ] Race leader via `Flt.EMIT_PHONETIC_LEADER` (payload: `pilot`, `callsign`; already hookable today — deferred to keep MVP scope small)
- [ ] Audio profile toggles for race clock, arm sequence, race tied/overtime, and race leader callouts
- [ ] Split pass callouts via `Flt.EMIT_PHONETIC_SPLIT` (payload: `pilot_name`, `split_id`, `split_time`, `split_speed`; only relevant on tracks with split sensors)

#### Sendspin sidecar service
- [ ] Provide `local-voice-sendspin.service` systemd unit file with the plugin
- [ ] Plugin setting: Sendspin mode (in-process / sidecar / disabled)
- [ ] Plugin setting: sidecar URL (default: `http://localhost:8766`)
- [ ] Sidecar mode: plugin sends WAV jobs to local sidecar via HTTP/WS
- [ ] Plugin health check pings sidecar status endpoint
- [ ] Sidecar mode works without Python 3.12+ in the RotorHazard virtualenv
- [ ] Document sidecar installation steps (pip install in separate venv, enable service)

#### Cloud Sendspin target
- [ ] Cloud server URL supported as a player target (same target list as local)
- [ ] Plugin sends same audio jobs to cloud target alongside any local targets
- [ ] No change required to the audio queue or TTS pipeline

#### QR code for spectator/pilot feed
- [ ] Generate QR code from the Sendspin player join URL (cloud target)
- [ ] Display QR code image in plugin settings panel
- [ ] QR code downloadable as PNG (for printing or sharing on screen)
- [ ] Panel note: "Requires internet access from RotorHazard host (hotspot is sufficient)"

#### Reconnect handling
- [ ] Auto-reconnect all targets on disconnect (exponential backoff: 2 s → 4 s → 8 s → max 60 s)
- [ ] Log each reconnect attempt and success
- [ ] Reconnect does not require plugin restart or RotorHazard restart

**Success criteria:**
- Phone hears race callouts after scanning QR code (cloud path)
- Sidecar restarts independently without restarting RotorHazard; reconnects within 10 seconds
- Local player and cloud player both receive audio simultaneously
- Install from scratch on a Pi with Python 3.10 works using the sidecar path

---

### Phase 5 — Wyoming Piper + Polish

**Goal:** Wyoming Piper as a lower-latency TTS option. mDNS player discovery. Cache management UI. Installation guide complete.

#### Wyoming Piper backend
- [ ] Wyoming protocol TCP client: connect to `host:port`, send synthesis request, receive WAV
- [ ] Plugin setting: Wyoming Piper host and port
- [ ] Setting: TTS engine selector (piper-tts / Wyoming Piper)
- [ ] Fallback: if Wyoming unreachable on startup, fall back to in-process piper-tts and show warning
- [ ] Health check: Wyoming service reachable; shown in plugin panel
- [ ] Cache works identically for both backends (same cache key format)

#### mDNS player discovery
- [ ] Discover Sendspin players on local network via mDNS/Zeroconf
- [ ] Show discovered players in plugin panel as selectable targets
- [ ] Manual URL entry remains available and takes precedence
- [ ] mDNS discovery failure is non-fatal (race networks may block mDNS)

#### Cache management UI
- [ ] Show: total cached files, total cache size
- [ ] Button: clear all cached WAVs
- [ ] Button: pre-generate for current heat (manual trigger)
- [ ] Show: list of most recently generated phrases
- [ ] Setting: maximum cache size (MB); evict oldest files when exceeded

#### Installation guide (in this document, final section)
- [ ] Piper: install steps for Raspberry Pi (arm64) and x86_64
- [ ] Piper: download and configure a voice model
- [ ] Wyoming Piper: run as a systemd service
- [ ] Sendspin player: install on NUC / laptop / Pi
- [ ] Sendspin sidecar: install on Pi for Python 3.10/3.11 setups
- [ ] RotorHazard browser clients: how to set Voice Volume to 0
- [ ] End-to-end test checklist for a new installation

**Success criteria:**
- Wyoming Piper produces callouts with measurably lower latency than in-process piper-tts for uncached phrases
- mDNS discovers the Sendspin player without manual URL entry on a standard home/club network
- A new user following the installation guide has audio working within 30 minutes
- Cache size stays bounded; old files evicted automatically when limit is reached

---

## Technical Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Sendspin browser playback hiccups on race network | Medium | Validate `/player` on actual event network and speaker hardware before race day |
| Sendspin public preview API changes | Medium | Pin version, document upgrade path |
| Python 3.12 not available on Pi | Medium | Use sidecar variant B |
| piper-tts too slow on Pi for uncached callouts | High | WAV caching now; planned heat-load pre-caching; Wyoming Piper on separate machine as fallback |
| Browser audio not disabled on clients | Duplicate audio | Setup checklist in UI |
| mDNS unreliable on race network | Medium | Manual player URL as primary config |
| Browser WebAudio scheduling drifts after tab or MacBook hiccup | Medium | Use official `@sendspin/sendspin-js` scheduler instead of custom scheduling; expose sync diagnostics |

---

## Data Flow

1. RotorHazard triggers a race event.
2. Plugin event handler builds an audio job (text + priority).
3. Plugin checks cache; on miss, calls piper-tts in-process to generate WAV.
4. Audio job enters the async playback queue.
5. Playback worker sends WAV to the Sendspin source.
6. Sendspin streams audio to connected clients on the local network.
7. Player outputs audio through the connected speaker/mixer.
8. Built-in browser audio remains disabled on normal clients.

---

## References

- [RotorHazard Plugin docs](doc/Plugins.md)
- [RHAPI docs](doc/RHAPI.md)
- [Piper TTS](https://github.com/rhasspy/piper)
- [Wyoming protocol](https://www.home-assistant.io/integrations/wyoming/)
- [Sendspin](https://www.sendspin-audio.com/)
