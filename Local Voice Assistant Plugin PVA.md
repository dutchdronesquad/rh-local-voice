# Local Voice Callouts Plugin — Plan of Approach

## Problem

RotorHazard uses browser TTS for spoken race callouts. In Chrome, some voices are remote services that silently fail when the race network has no internet access, while beeps and MP3 sounds continue to work. The goal is to move spoken callout generation to a fully local speech service running server-side.

## Concrete Goal

An RHAPI-only RotorHazard plugin that:

- Listens to race events on the RotorHazard host (server-side Python only).
- Builds its own audio queue for voice callouts and indicator sounds.
- Uses Piper as the local TTS engine to generate speech fully offline.
- Caches generated WAV files so predictable race phrases do not need synthesis during critical moments.
- Sends audio to a SendSpin player on the local network as the primary output target.
- Requires no RotorHazard core changes.

**Not in scope:** replacing browser-finalized lap callouts (assembled in JS), injecting JavaScript into existing pages, or voice command input.

**Minimum Python version:** 3.12 (required by SendSpin).

---

## RHAPI Limitations

- Lap callouts are assembled in browser JS from `phonetic_data` using per-browser localStorage settings. A server-side plugin cannot intercept the final phrase.
- The plugin cannot edit the built-in Audio Control tab or disable browser TTS automatically on other clients.
- The plugin cannot inject JavaScript into existing RotorHazard pages.

Consequence: **duplicate prevention is operational**, not automatic. The operator must manually set Voice Volume to 0 on all regular RotorHazard browser clients when the plugin is active.

---

## Missing RH Features (wishlist for upstream)

Things that would make the plugin significantly easier or more capable, but don't exist in RotorHazard today. Each item includes the ideal upstream fix and the current workaround.

### Race clock countdown events

**Problem:** No server-side events for race time warnings ("30 seconds remaining", "10 seconds remaining", etc.). The countdown is handled entirely in browser JS via a local timer.

**Ideal fix:** Add `Evt.RACE_CLOCK_WARNING` fired by the RH race thread at configurable thresholds (e.g. 60s, 30s, 10s remaining), with payload `{'seconds_remaining': int}`. This would let any plugin — not just audio plugins — react to race time milestones without reimplementing a parallel timer.

**Status: deferred.** Not implemented in the plugin until RH provides a proper server-side event. Race clock callouts are skipped for now.

---

### Arm sequence countdown events

**Problem:** The staging beeps ("3... 2... 1...") before race start are generated in browser JS. There is no `Evt.RACE_ARM_TONE` or similar server event. Plugin cannot reproduce the countdown sequence without reimplementing the staging logic.

**Ideal fix:** Fire `Evt.RACE_ARM_TONE` from `RHRace.stage()` at each staging beep interval, with payload `{'tone_index': int, 'tones_remaining': int}`. This decouples the audio signal from the browser and lets server-side plugins (LED, audio, video) stay in sync with the actual staging sequence.

**Status: deferred.** Not implemented in the plugin until RH fires server-side arm tone events. Staging beeps are skipped for now.

---

### Structured race-tied / overtime events

**Problem:** Race Tied and Overtime announcements go through `emit_phonetic_text()` with translated strings. There is no dedicated `Evt.RACE_TIED` or `Evt.RACE_OVERTIME`. The plugin must either hook `Flt.EMIT_PHONETIC_TEXT` and parse translated text (fragile), or inspect `win_status` inside `Evt.RACE_WIN`.

**Ideal fix:** Fire dedicated `Evt.RACE_TIED` and `Evt.RACE_OVERTIME` events from `check_win_condition()` in addition to the existing `Evt.RACE_WIN`. This mirrors the pattern already used for `Evt.RACE_PILOT_DONE` vs `Evt.RACE_WIN` and makes win outcome handling explicit for plugins.

**Status: deferred.** Not implemented until RH fires dedicated events. Race Tied and Overtime callouts are skipped for now.

---

### Race leader callout via unified filter

**Problem:** `Evt.RACE_PILOT_LEADING` fires correctly, but the phonetic text is assembled in `emit_phonetic_leader()` and emitted as a separate `phonetic_leader` socket event — bypassing `Flt.EMIT_PHONETIC_TEXT`. Plugins that want to intercept all voice callouts must register a second filter (`Flt.EMIT_PHONETIC_LEADER`) separately.

**Ideal fix:** Route `emit_phonetic_leader()` through `emit_phonetic_text()` with a `domain='race_leader'` parameter, just like winner announcements use `domain='race_winner'`. This unifies all voice output behind a single filter point and makes `Flt.EMIT_PHONETIC_TEXT` truly the single interception point for audio plugins.

**Status: deferred.** Not implemented until RH routes leader callouts through the unified `Flt.EMIT_PHONETIC_TEXT` filter. Race leader callouts are skipped for now.

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
**Mitigation for synthesis latency:** cache generated phrases by normalized text and synthesis parameters. Planned follow-up: pre-generate predictable phrases at heat load (pilot names, lap numbers 1–20, "Race Start", "Race Stop", "Winner is"). Real-time synthesis remains necessary for dynamic lap times and unexpected text.

### Wyoming Piper (upgrade path)

Piper as a persistent TCP service. Plugin sends text, receives WAV back. Can run on a separate LAN machine if the Pi is underpowered for synthesis.

**Recommendation:** start with the `piper-tts` Python package + WAV caching. Add Wyoming Piper as an optional backend in Phase 5.

---

## B. Audio Output — SendSpin

SendSpin separates a **server/source** (orchestrates streams, accepts audio input) from a **player/client** (receives audio, plays through a local audio device). The current plugin starts an in-process SendSpin server and streams generated WAV audio to connected clients on the local network. Named player targeting remains planned work.

```
RotorHazard plugin
  → generates WAV via Piper
  → SendSpin server/source
  → SendSpin protocol over LAN
  → SendSpin player (any device with a speaker: NUC, laptop, Pi, ...)
  → speaker / mixer
```

The SendSpin server can run anywhere — on the Pi itself, as a sidecar service, or in the cloud. The player runs on whatever device is connected to the speakers. These are deployment choices, not separate code paths. The plugin has one SendSpin integration; the operator configures where the server and players are.

### SendSpin server placement

**On the RotorHazard host (in-process or sidecar)**

Requires Python 3.12+ on the host. The simplest setup: everything local, no internet needed.

- In-process: plugin drives SendSpin directly (Python 3.12+ required in the RH virtualenv).
- Sidecar: SendSpin runs as a separate systemd service, plugin talks to it over local HTTP/WS. Useful when you cannot upgrade the RH Python environment or want to restart SendSpin independently.

**In the cloud**

SendSpin server runs on a VPS or SendSpin's own hosted service. The plugin sends audio over the internet (a mobile hotspot is enough). Anyone at the event can scan a QR code and hear callouts on their own phone — no dedicated audio device or PA needed.

```
RotorHazard plugin → internet → SendSpin cloud server → phone (QR code)
```

This works as a standalone setup for small events, or in parallel with a local player for events that have both a PA and want a spectator feed.

### Player placement

The SendSpin player can run on any device with an audio output: Intel NUC, laptop, Raspberry Pi, phone. The operator installs the SendSpin player daemon, names it (e.g. `Race Speakers`), and the plugin targets that name. Multiple players can be active simultaneously.

### Deployment examples

| Situation | SendSpin server | Player |
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
- Prerender / SSG: **No**. The app depends on WebSocket, WebAudio, user gestures, and runtime SendSpin state.
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

- SendSpin protocol handshake
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

The browser player should continue to avoid local audio scheduling code. Timing, correction, reconnects, and decoding belong in the SendSpin SDK.

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
- [x] Test phrase plays in sync with a native SendSpin player.
- [x] Stop button clears playback on native and browser players.
- [x] MacBook/browser hiccup does not create persistent delay after recovery.
- [x] Reconnect after SendSpin server restart works without page refresh.

### Known SendSpin risks to validate before race day

- **Latency per short WAV:** SendSpin is designed for synchronized music streaming. Stream setup overhead for many short event-driven callouts must be measured. A persistent stream or keep-alive source connection may be required.
- **Public preview:** APIs may still change.
- **mDNS discovery** may be unreliable on isolated race networks. Manual player URL config must always be available as fallback.

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
        └── SendSpin output
              Variant A: in-process source
              Variant B: HTTP client → sidecar service
```

### Playback worker

- Single async worker, FIFO queue.
- Priority: Race Start / Winner / Interrupt > lap callouts > crossing beeps.
- Callouts expire after ~5 seconds — a stale lap callout should never play.
- All synthesis is async; never blocks RotorHazard event handling.

### Audio cache

Cache path: `{model_name}/{sha1(normalized_text)}_{speed}_{noise}_{noise_w}.wav`

Current heat-load behavior:
- Clears ephemeral lap-time WAV files for the selected model.

Planned pre-generation at heat load:
- Pilot callsigns from the current heat.
- Lap numbers 1–20.
- Fixed phrases: "Race Start", "Race Stop", "Winner is", "Finished", "First place".

---

## Integration with Built-In RotorHazard Audio

The plugin cannot take over the built-in Audio Control tab. The operating model is:

1. Install and enable the plugin.
2. Configure Piper in the plugin panel.
3. Run a SendSpin player on the device connected to the speakers and connect it to the RotorHazard host on port `8927`.
4. On every regular RotorHazard browser client: set Voice Volume to 0 and disable browser beeps if the plugin handles beeps.

**Built-in Audio Control → used only to silence browser clients**
**Plugin Audio Profile → planned place to decide what the speakers announce**

Plugin audio profile mirrors the familiar RH categories:
- Pilot callsign, lap number, lap time on/off
- Race clock callouts
- Winner / race leader callouts
- Crossing enter/exit beeps
- Voice volume, beep volume, speech speed, voice model

---

## Plugin Settings

Implemented:
- Enable plugin audio: on/off
- Voice model selector: 12 models across English, Dutch, and German
- Speech speed, noise scale, phoneme width noise
- Crossing enter/exit beeps: on/off
- Test phrase field and quick button
- Play audio check quick button
- Stop audio quick button
- Clear TTS cache quick button
- Duplicate prevention warnings for browser Voice Volume and browser beeps

Planned / not implemented yet:
- TTS engine selector: piper-tts / Wyoming Piper / disabled
- Wyoming Piper host and port
- SendSpin mode: in-process / sidecar / disabled
- SendSpin sidecar URL
- SendSpin player target list or named player selection
- Output volume and beep volume in the plugin panel
- Pre-generate on heat load: on/off
- Per-event audio profile toggles beyond crossing beeps
- Panel status display for TTS, SendSpin source, and connected players

---

## Implementation Phases

Each phase has a clear goal, a concrete checklist, and success criteria. A phase is done when every checkbox is ticked and the success criteria are met — not before.

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
- [ ] ~~Show in plugin panel: model loaded / loading / error~~ — removed; RotorHazard input fields are not suitable for read-only display. Status available in logs.
- [ ] ~~Show: last generated phrase + WAV file size + synthesis duration~~ — removed (same reason)
- [ ] ~~Show: cache directory path + number of cached files~~ — removed (same reason)

**Success criteria:**
- [x] Clicking "Test phrase" generates a WAV in the cache directory with correct size and a valid WAV header
- [x] Second click on "Test phrase" returns the cached file without re-synthesizing (log confirms cache hit)
- [x] `Flt.EMIT_PHONETIC_TEXT` handler is registered and schedules text callouts without modifying the payload
- [x] Model not found / download failure logs a clear status and does not crash RotorHazard

---

### Phase 2 — Race Events + Audio Queue

**Goal:** Lap/text callout filters and crossing events are wired. Async queue has priority and expiry. Heat-load cache handling exists; full pre-caching remains backlog.

#### Current callout inputs
- [x] `Flt.EMIT_PHONETIC_DATA` → "Pilot [callsign], Lap [n]" + optional lap time
- [x] `Flt.EMIT_PHONETIC_TEXT` → server-originated text callouts via TTS
- [x] `Evt.CROSSING_ENTER` / `Evt.CROSSING_EXIT` → programmatically generated sine-tone beep WAV
- [x] `Evt.HEAT_SET` → clear ephemeral lap-time WAVs for the selected model

#### Direct race event listeners
- [ ] `Evt.RACE_STAGE` → "Ready"
- [ ] `Evt.RACE_START` → "Race start"
- [ ] `Evt.RACE_PILOT_DONE` → "[callsign] finished"
- [ ] `Evt.RACE_WIN` → "Winner is [callsign]" (currently covered only if RotorHazard emits winner text through `Flt.EMIT_PHONETIC_TEXT`)
- [ ] Race Tied / Overtime — deferred pending upstream `Evt.RACE_TIED` / `Evt.RACE_OVERTIME`
- [ ] Race leader — deferred pending unified `Flt.EMIT_PHONETIC_TEXT` routing
- [ ] `Evt.RACE_STOP` / `Evt.RACE_FINISH` → "Race stopped" / "Race finished"
- [ ] `Evt.MESSAGE_STANDARD` / `Evt.MESSAGE_INTERRUPT` → spoken message text via TTS (currently covered only if RotorHazard emits message text through `Flt.EMIT_PHONETIC_TEXT`)

#### Async audio queue
- [x] Single `queue.PriorityQueue` with a dedicated daemon worker thread (`audio_queue.py`)
- [x] `AudioJob` dataclass: `text`, `wav_paths`, `priority`, `expires_at`
- [x] Priority levels: `HIGH` (race start / winner / interrupt) > `NORMAL` (lap callout) > `LOW` (beep)
- [x] Expiry: drop jobs where `time.monotonic() > expires_at` (default: 5 seconds)
- [x] Single worker draining the queue in priority order; expired jobs dropped and logged
- [x] Worker plays one item at a time; previous item must finish before next starts

#### Audio profile settings
- [ ] Pilot callsign: on/off — not separately configurable yet
- [ ] Lap number: on/off — not separately configurable yet
- [ ] Lap time: on/off — not separately configurable yet
- [ ] Race clock callouts: on/off — deferred pending upstream `Evt.RACE_CLOCK_WARNING`
- [ ] Winner callout: on/off — not separately configurable yet
- [ ] Race tied / overtime callout: on/off — deferred pending upstream fix
- [ ] Race leader callout: on/off — deferred pending upstream fix
- [ ] Pilot finished callout: on/off — not separately configurable yet
- [x] Crossing enter/exit beeps: on/off
- [x] All implemented toggles exposed in plugin settings panel

#### Heat-load cache handling
- [x] Hook into `Evt.HEAT_SET`
- [x] Clear ephemeral lap-time WAV files when a heat loads
- [ ] Generate WAVs for all pilot callsigns in the loaded heat
- [ ] Generate WAVs for lap numbers 1–20
- [ ] Generate WAVs for all fixed phrases
- [ ] Pre-caching runs in a background thread; does not block heat load or event handling
- [ ] Log how many files were generated and how long it took

#### Duplicate prevention UI
- [x] Plugin panel shows two separate markdown warnings (Voice Volume + browser beeps)

#### Error handling
- [x] Piper fails → log error with phrase text, skip callout, continue
- [x] Event handler never raises an unhandled exception
- [x] No race event is delayed or dropped because of plugin audio work

**Success criteria:**
- [ ] A full simulated race (stage → start → laps → winner → stop) produces the correct callouts in the log
- [ ] Pilot names and lap numbers are pre-generated when a heat loads; generation time logged
- [x] Piper crash mid-race does not affect RotorHazard timing or results
- [x] Expired callouts are dropped and logged, never played late

---

### Phase 3 — SendSpin Integration

**Goal:** Audio leaves the Pi and plays on a remote device via SendSpin. Latency validated. Local Pi playback retired as primary path.

#### SendSpin source setup
- [x] Add `aiosendspin` to plugin dependencies; keep server-only extras explicit in `manifest.json` (`av`, `numpy`, `pillow`) because RotorHazard plugin install flows may not preserve extras reliably
- [x] SendSpin source/server starts when plugin initializes
- [x] SendSpin source accepts WAV input from the plugin audio queue worker
- [x] In-process mode: plugin drives `aiosendspin` directly (Python 3.12+)
- [ ] Sidecar mode: plugin sends WAV jobs to local sidecar via HTTP/WS (see Phase 4)
- [ ] Plugin setting: SendSpin mode (in-process / sidecar / disabled)

#### Player target configuration
- [ ] Plugin setting: SendSpin player target list (one or more entries)
- [ ] Each target: name label + manual URL (e.g. `ws://192.168.1.50:5000/sendspin`)
- [ ] UI: add / remove targets
- [ ] Plugin connects to all configured targets on startup

#### Health checks
- [ ] SendSpin source running: check on plugin init, show status in panel
- [ ] Per-target: player connected / disconnected / unreachable
- [ ] Status refreshes automatically (poll interval: 10 seconds)
- [ ] Disconnected target shows warning in panel; does not disable other targets

#### Latency validation
- [ ] Log timestamps per job: event received → WAV ready → SendSpin submitted → (if measurable) playback confirmed
- [ ] Run test race on actual hardware (Pi → SendSpin → NUC player)
- [ ] Document measured latency in this document under a "Validated Latency" subsection
- [ ] If latency > 1 second for cached phrases: investigate persistent stream / keep-alive connection
- [ ] Decision recorded: stream-per-WAV vs persistent stream

#### Test phrase through SendSpin
- [x] Test button sends phrase through the full stack: Piper → cache → in-process `aiosendspin` → connected player(s)
- [ ] Panel shows: "Last test: sent to [target name] at [time]"

#### Browser player rewrite
- [x] Browser player served at `/player`
- [x] Root-level `player/` Vite/Preact app scaffolded
- [x] Add `@sendspin/sendspin-js` to the root-level player app
- [x] Configure Vite build output to `custom_plugins/local_voice/player/`
- [x] Replace template UI with `SendspinPlayer`-based app
- [x] Add compact diagnostics for sync drift, correction mode, reconnects, and player state
- [ ] Validate browser player against native SendSpin player for sync and hiccup recovery

**Success criteria:**
- [ ] "Test phrase" plays audibly through the SendSpin player on a remote device
- [ ] Lap callout latency (cached phrase, Pi to player) measured and documented
- [ ] Player disconnect is shown in the UI; plugin continues without crash
- [ ] Disconnecting and reconnecting the player recovers automatically

---

### Phase 4 — Sidecar, Cloud, and QR Code

**Goal:** SendSpin server can run as an independent sidecar service (for Python version compatibility) and optionally in the cloud for spectator/pilot phone feeds.

#### SendSpin sidecar service
- [ ] Provide `local-voice-sendspin.service` systemd unit file with the plugin
- [ ] Plugin setting: sidecar URL (default: `http://localhost:8766`)
- [ ] Plugin health check pings sidecar status endpoint
- [ ] Sidecar mode works without Python 3.12+ in the RotorHazard virtualenv
- [ ] Document sidecar installation steps (pip install in separate venv, enable service)

#### Cloud SendSpin target
- [ ] Cloud server URL supported as a player target (same target list as local)
- [ ] Plugin sends same audio jobs to cloud target alongside any local targets
- [ ] No change required to the audio queue or TTS pipeline

#### QR code for spectator/pilot feed
- [ ] Generate QR code from the SendSpin player join URL (cloud target)
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
- [ ] Discover SendSpin players on local network via mDNS/Zeroconf
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
- [ ] SendSpin player: install on NUC / laptop / Pi
- [ ] SendSpin sidecar: install on Pi for Python 3.10/3.11 setups
- [ ] RotorHazard browser clients: how to set Voice Volume to 0
- [ ] End-to-end test checklist for a new installation

**Success criteria:**
- Wyoming Piper produces callouts with measurably lower latency than in-process piper-tts for uncached phrases
- mDNS discovers the SendSpin player without manual URL entry on a standard home/club network
- A new user following the installation guide has audio working within 30 minutes
- Cache size stays bounded; old files evicted automatically when limit is reached

---

## Technical Risks

| Risk | Impact | Mitigation |
|---|---|---|
| SendSpin stream latency too high for short callouts | High | Measure early; persistent stream / keep-alive source if needed |
| SendSpin public preview API changes | Medium | Pin version, document upgrade path |
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
5. Playback worker sends WAV to the SendSpin source.
6. SendSpin streams audio to connected clients on the local network.
7. Player outputs audio through the connected speaker/mixer.
8. Built-in browser audio remains disabled on normal clients.

---

## References

- [RotorHazard Plugin docs](doc/Plugins.md)
- [RHAPI docs](doc/RHAPI.md)
- [Piper TTS](https://github.com/rhasspy/piper)
- [Wyoming protocol](https://www.home-assistant.io/integrations/wyoming/)
- [SendSpin](https://www.sendspin-audio.com/)
