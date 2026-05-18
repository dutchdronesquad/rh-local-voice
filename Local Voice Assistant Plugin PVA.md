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
**Model download:** the plugin downloads the selected voice model automatically from the Piper release repository on first use (or when the model is changed). Models are cached in `~/rh-data/local_voice_cache/models/`. Internet is only needed once per model; race operation is fully offline after that.

**Supported languages:** English and Dutch to start. Recommended default models: `en_GB-alan-medium` (English) and `nl_NL-mls-medium` (Dutch). The plugin setting shows a dropdown of available models grouped by language; the operator picks one per installation.
**Mitigation for synthesis latency:** pre-generate all predictable phrases at heat load (pilot names, lap numbers 1–20, "Race Start", "Race Stop", "Winner is", countdown). Real-time synthesis only for unexpected text.

### Wyoming Piper (upgrade path)

Piper as a persistent TCP service. Plugin sends text, receives WAV back. Can run on a separate LAN machine if the Pi is underpowered for synthesis.

**Recommendation:** start with `piper-tts` Python package + pre-caching. Add Wyoming Piper as an optional backend in Phase 5.

---

## B. Audio Output — SendSpin

SendSpin separates a **server/source** (orchestrates streams, accepts audio input) from a **player/client** (receives audio, plays through a local audio device). The plugin acts as a source and pushes generated WAV audio to one or more named player instances on the local network.

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
        │     Evt.RACE_STAGE, RACE_START, RACE_LAP_RECORDED,
        │     RACE_PILOT_DONE, RACE_WIN, RACE_STOP,
        │     CROSSING_ENTER/EXIT, MESSAGE_STANDARD/INTERRUPT
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

Cache key: `{normalized_text}_{voice}_{speed}.wav`

Pre-generate at heat load:
- Pilot callsigns from the current heat.
- Lap numbers 1–20.
- Fixed phrases: "Race Start", "Race Stop", countdown, "Winner is", "Finished", "First place".

---

## Integration with Built-In RotorHazard Audio

The plugin cannot take over the built-in Audio Control tab. The operating model is:

1. Install and enable the plugin.
2. Configure Piper and SendSpin in the plugin panel.
3. Run a SendSpin player on the device connected to the speakers.
4. On every regular RotorHazard browser client: set Voice Volume to 0 and disable browser beeps if the plugin handles beeps.

**Built-in Audio Control → used only to silence browser clients**
**Plugin Audio Profile → decides what the speakers announce**

Plugin audio profile mirrors the familiar RH categories:
- Pilot callsign, lap number, lap time on/off
- Race clock callouts
- Winner / race leader callouts
- Crossing enter/exit beeps
- Voice volume, beep volume, speech speed, voice model

---

## Plugin Settings

- Enable plugin audio: on/off
- TTS engine: piper-tts (in-process) / Wyoming Piper / disabled
- Voice model: dropdown of available models grouped by language (English / Dutch)
- Wyoming Piper host and port (if used)
- SendSpin mode: in-process / sidecar / disabled
- SendSpin sidecar URL (if sidecar mode)
- SendSpin player target: auto-discover / manual URL
- SendSpin player name (e.g. `Race Speakers`)
- Speech speed, output volume, beep volume
- Pre-generate on heat load: on/off
- Cache directory and clear button
- Audio profile: per-event toggles (see above)
- Test phrase button
- Status display: TTS reachable, SendSpin source running, player connected
- Duplicate prevention checklist: shows required built-in RH Audio Control settings

---

## Implementation Phases

Each phase has a clear goal, a concrete checklist, and success criteria. A phase is done when every checkbox is ticked and the success criteria are met — not before.

---

### Phase 1 — Foundation: Plugin Scaffold + Piper TTS

**Goal:** A working plugin that generates a valid WAV file from text using the `piper-tts` Python package. No SendSpin yet. Proves the TTS pipeline and cache end to end.

#### Plugin structure
- [ ] Create `plugins/local_voice/__init__.py` with `initialize(rhapi)` entry point
- [ ] Register a settings panel via `rhapi.ui.register_panel()`
- [ ] Add "Enable plugin audio" toggle via `rhapi.fields.register_option()`
- [ ] Add voice model selector setting
- [ ] Add speech speed setting
- [ ] Add "Test phrase" quick button via `rhapi.ui.register_quickbutton()`

#### piper-tts integration
- [ ] Add `piper-tts` to plugin dependencies
- [ ] On first use (or model change): auto-download selected voice model from Piper release repository into `~/rh-data/local_voice_cache/models/`
- [ ] Show download progress in plugin panel; handle download failure with a clear error message
- [ ] Load `PiperVoice` once at plugin init; reload only when model/speed setting changes
- [ ] Synthesize text to WAV using `voice.synthesize(text, wav_file)`
- [ ] Handle synthesis errors gracefully (log, skip, no crash)

#### Audio cache
- [ ] Create cache directory: `~/rh-data/local_voice_cache/tts/`
- [ ] Cache key: `{sha1(normalized_text)}_{model_name}_{speed}.wav`
- [ ] On cache hit: return existing WAV path, skip synthesis
- [ ] On cache miss: synthesize, write to cache, return WAV path

#### Event hook
- [ ] Register `Flt.EMIT_PHONETIC_TEXT` handler
- [ ] Log intercepted callout text to verify hook fires correctly
- [ ] Hook does not modify or block the callout payload

#### Status display
- [ ] Show in plugin panel: model loaded / loading / error
- [ ] Show: last generated phrase + WAV file size + synthesis duration
- [ ] Show: cache directory path + number of cached files

**Success criteria:**
- Clicking "Test phrase" generates a WAV in the cache directory with correct size and a valid WAV header
- Second click on "Test phrase" returns the cached file without re-synthesizing (log confirms cache hit)
- `Flt.EMIT_PHONETIC_TEXT` log entry appears when a test callout is triggered
- Model not found / download failure shows a clear message in the panel, does not crash RotorHazard

---

### Phase 2 — Race Events + Audio Queue

**Goal:** All race events wired. Async queue with priority and expiry. Pre-caching at heat load. The plugin is now race-functional; audio output is verified via the log and WAV files — SendSpin is wired in Phase 3.

#### Race event listeners
- [ ] `Evt.RACE_STAGE` → stage message or countdown phrase
- [ ] `Evt.RACE_START` → "Race Start" callout
- [ ] `Evt.RACE_LAP_RECORDED` → "Pilot [callsign], Lap [n]" + optional lap time
- [ ] `Evt.RACE_PILOT_DONE` → "Finished" callout for that pilot
- [ ] `Evt.RACE_WIN` → "Winner is [callsign]" callout
- [ ] `Evt.RACE_STOP` / `Evt.RACE_FINISH` → "Race Stop" / "Race Finished" callout
- [ ] `Evt.CROSSING_ENTER` / `Evt.CROSSING_EXIT` → short beep WAV (bundled with the plugin, no synthesis needed)
- [ ] `Evt.MESSAGE_STANDARD` / `Evt.MESSAGE_INTERRUPT` → optional spoken message text

#### Async audio queue
- [ ] Single `queue.Queue` with a dedicated worker thread — never block the event handler (threading chosen over asyncio to avoid conflicts with RotorHazard's gevent/eventlet model)
- [ ] `AudioJob` dataclass: `text`, `wav_path`, `priority`, `expires_at`
- [ ] Priority levels: `HIGH` (race start / winner / interrupt) > `NORMAL` (lap callout) > `LOW` (beep)
- [ ] Expiry: drop jobs where `time.monotonic() > expires_at` (default: 5 seconds)
- [ ] Single worker draining the queue in order; HIGH priority jobs jump the queue
- [ ] Worker plays one item at a time; previous item must finish before next starts

#### Audio profile settings
- [ ] Pilot callsign: on/off
- [ ] Lap number: on/off
- [ ] Lap time: on/off
- [ ] Race clock callouts: on/off
- [ ] Winner callout: on/off
- [ ] Finished callout: on/off
- [ ] Crossing enter/exit beeps: on/off
- [ ] All toggles exposed in plugin settings panel

#### Pre-caching at heat load
- [ ] Hook into heat load event (or `Evt.HEAT_SET`)
- [ ] Generate WAVs for all pilot callsigns in the loaded heat
- [ ] Generate WAVs for lap numbers 1–20
- [ ] Generate WAVs for all fixed phrases (see list in Architecture section)
- [ ] Pre-caching runs in a background thread; does not block heat load or event handling
- [ ] Log how many files were generated and how long it took

#### Duplicate prevention UI
- [ ] Plugin panel shows a setup checklist:
  - [ ] "Set Voice Volume to 0 on all browser clients"
  - [ ] "Disable browser beeps on all browser clients if plugin beeps are enabled"
- [ ] Checklist items show as warnings, not errors (operator responsibility)

#### Error handling
- [ ] Piper fails → log error with phrase text, skip callout, continue
- [ ] Event handler never raises an unhandled exception
- [ ] No race event is delayed or dropped because of plugin audio work

**Success criteria:**
- A full simulated race (stage → start → laps → winner → stop) produces the correct callouts in the log
- Pilot names and lap numbers are pre-generated when a heat loads; generation time logged
- Piper crash mid-race does not affect RotorHazard timing or results
- Expired callouts are dropped and logged, never played late

---

### Phase 3 — SendSpin Integration

**Goal:** Audio leaves the Pi and plays on a remote device via SendSpin. Latency validated. Local Pi playback retired as primary path.

#### SendSpin source setup
- [ ] Add `sendspin` to plugin dependencies (pin to a specific version)
- [ ] SendSpin source/server starts when plugin is enabled
- [ ] SendSpin source accepts WAV input from the plugin audio queue worker
- [ ] In-process mode: plugin drives SendSpin source directly (Python 3.12+)
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
- [ ] Test button sends phrase through the full stack: Piper → cache → SendSpin → player
- [ ] Panel shows: "Last test: sent to [target name] at [time]"

**Success criteria:**
- "Test phrase" plays audibly through the SendSpin player on a remote device
- Lap callout latency (cached phrase, Pi to player) measured and documented
- Player disconnect is shown in the UI; plugin continues without crash
- Disconnecting and reconnecting the player recovers automatically

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
- [ ] Setting: TTS engine selector (Piper CLI / Wyoming Piper)
- [ ] Fallback: if Wyoming unreachable on startup, fall back to Piper CLI and show warning
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
- Wyoming Piper produces callouts with measurably lower latency than Piper CLI for uncached phrases
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
| piper-tts too slow on Pi for uncached callouts | High | Pre-caching at heat load; Wyoming Piper on separate machine as fallback |
| Browser audio not disabled on clients | Duplicate audio | Setup checklist in UI |
| mDNS unreliable on race network | Medium | Manual player URL as primary config |

---

## Data Flow

1. RotorHazard triggers a race event.
2. Plugin event handler builds an audio job (text + priority).
3. Plugin checks cache; on miss, calls piper-tts in-process to generate WAV.
4. Audio job enters the async playback queue.
5. Playback worker sends WAV to the SendSpin source.
6. SendSpin streams audio to the named player on the local network.
7. Player outputs audio through the connected speaker/mixer.
8. Built-in browser audio remains disabled on normal clients.

---

## References

- [RotorHazard Plugin docs](doc/Plugins.md)
- [RHAPI docs](doc/RHAPI.md)
- [Piper TTS](https://github.com/rhasspy/piper)
- [Wyoming protocol](https://www.home-assistant.io/integrations/wyoming/)
- [SendSpin](https://www.sendspin-audio.com/)
