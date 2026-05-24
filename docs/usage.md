# Usage Guide

This guide covers day-to-day setup and operation for Local Voice.

## Basic Setup

1. In RotorHazard, open **Settings** -> **Local Voice**.
2. Enable **Plugin audio**.
3. Choose a voice model and adjust the speech parameters if needed.
4. Open `/player` from the RotorHazard host in a browser tab on the playback device, for example `http://rotorhazard.local:5000/player`.
5. Set normal RotorHazard browser Voice Volume to `0` on clients that should only use Local Voice audio.
6. Use **Generate test phrase** or **Play audio check** to verify playback.

The current plugin release still owns the local Sendspin server inside the
RotorHazard plugin process. The standalone Sendspin service described below is
migration work and is not the default user-facing playback path until the plugin
HTTP output layer is connected.

## Standalone Sendspin Service

The planned local playback path is a separate service package named
`rh-sendspin-service`. In the target architecture, the plugin generates and
caches WAV files, then sends playback jobs to the service over local HTTP.

The repository now contains a first standalone service implementation under
`sendspin_service/`. It owns its own `AudioQueue` and Sendspin server adapter so
the migration can proceed without importing RotorHazard plugin modules.

Current development command:

```shell
python -m sendspin_service
```

Useful development flags:

```shell
python -m sendspin_service \
  --host 127.0.0.1 \
  --port 8766 \
  --sendspin-host 0.0.0.0 \
  --sendspin-port 8927
```

Target user install:

```shell
sudo apt install ./rh-sendspin-service_0.1.0_arm64.deb
```

Useful endpoints:

- `GET /health`: service status, version, Sendspin port, and connected player count.
- `POST /v1/play`: queues one or more WAV paths for playback.
- `POST /v1/stop`: stops current playback.

Example playback payload:

```json
{
  "text": "race callout",
  "wav_paths": ["/home/pi/rh-data/local_voice_cache/tts/example.wav"],
  "priority": "normal",
  "expiry_sec": 5.0,
  "play_at": null,
  "volume": 1.0
}
```

Packaging work is tracked in `Sendspin Service Package PVA.md`.

## Settings

- **Enable plugin audio**: Turns Local Voice callout generation on or off.
- **Voice model**: Selects the Piper voice model. Models are downloaded once and reused.
- **Speech speed**: Controls speaking rate. `1.0` is Piper default; lower is slower, higher is faster.
- **Noise scale**: Controls voice variation. Lower values are more monotone; higher values are more expressive.
- **Phoneme width noise**: Controls duration variation between phonemes.
- **Test phrase**: Phrase used by the **Generate test phrase** button.

## Quick Buttons

- **Generate test phrase**: Generates and queues the configured test phrase.
- **Play audio check**: Plays a bundled music clip through the Sendspin path.
- **Stop audio**: Stops Sendspin playback and clears queued audio.
- **Clear TTS cache**: Deletes all cached WAV files for the selected voice model.

## Browser Player

The built-in browser player is served by the plugin at `/player`. It connects to Sendspin over WebSocket and plays streamed PCM audio in the browser.

During local testing, Safari on macOS produced the smoothest browser playback. Chrome can work well too, but browser extensions may add console noise or small timing interruptions. If playback jitter appears in Chrome, test once in an incognito window with extensions disabled before debugging the server.

## Cache Layout

Local Voice stores generated files under the RotorHazard data directory:

```text
local_voice_cache/
  models/                 downloaded Piper ONNX models
  tts/<model>/            normal cached phrases
  tts/<model>/precache/pilots/
                           pre-generated pilot-name segments
  tts/<model>/precache/laps/
                           pre-generated "Lap [n]" segments
  tts/<model>/precache/schedule/
                           scheduled-race countdown phrases
  tts/<model>/tmp/        ephemeral lap-time phrases
  tts/<model>/test/       generated test phrases
```

Cache behavior:

- `tmp/` is cleared whenever a heat is selected.
- `precache/` keeps existing reusable phrases. Use **Rebuild pre-cache** to generate schedule phrases, current-heat pilot-name segments, and lap-number segments on demand.
- `tmp/` and `precache/` are cleared on RotorHazard data reset.
- **Clear TTS cache** removes all WAV files for the selected model.

## Operational Notes

- Local Voice does not disable RotorHazard's built-in browser speech. Set Voice Volume to `0` on regular RotorHazard browser clients to avoid duplicate callouts.
- The first use of a voice model requires internet access to download model files. Racing can run offline after the selected model has been cached.
- Callouts are generated server-side; browser-specific RotorHazard voice settings do not affect Local Voice output.
- If no Sendspin browser player is connected, generated audio is dropped and logged.

## Troubleshooting

- **No audio in the browser player**: confirm that `/player` is open, connected to the correct host, and that port `8927` is reachable from the playback device.
- **Standalone service is not reachable during migration testing**: confirm `python -m sendspin_service` is running and `GET /health` works on `http://127.0.0.1:8766`.
- **Duplicate voice callouts**: set RotorHazard Voice Volume to `0` in all regular RotorHazard browser clients.
- **First phrase is slow**: the selected Piper model may be downloading or loading. Watch the RotorHazard log for Local Voice status messages.
- **Browser playback stutters**: try Safari or a Chrome incognito window with extensions disabled, then validate on the actual race network.
