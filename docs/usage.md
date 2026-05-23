# Usage Guide

This guide covers day-to-day setup and operation for Local Voice.

## Basic Setup

1. In RotorHazard, open **Settings** -> **Local Voice**.
2. Enable **Plugin audio**.
3. Choose a voice model and adjust the speech parameters if needed.
4. Open `/player` from the RotorHazard host in a browser tab on the playback device, for example `http://rotorhazard.local:5000/player`.
5. Set normal RotorHazard browser Voice Volume to `0` on clients that should only use Local Voice audio.
6. Use **Generate test phrase** or **Play audio check** to verify playback.

The Sendspin server listens on port `8927`. If another machine is used for playback, make sure that port is reachable on the local network.

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
  tts/<model>/precache/laps/
                           pre-generated "[name], Lap [n]" phrases
  tts/<model>/precache/schedule/
                           scheduled-race countdown phrases
  tts/<model>/tmp/        ephemeral lap-time phrases
  tts/<model>/test/       generated test phrases
```

Cache behavior:

- `tmp/` is cleared whenever a heat is selected.
- `precache/` keeps existing reusable phrases. Use **Rebuild pre-cache** to generate schedule and current-heat pilot/lap phrases on demand.
- `tmp/` and `precache/` are cleared on RotorHazard data reset.
- **Clear TTS cache** removes all WAV files for the selected model.

## Operational Notes

- Local Voice does not disable RotorHazard's built-in browser speech. Set Voice Volume to `0` on regular RotorHazard browser clients to avoid duplicate callouts.
- The first use of a voice model requires internet access to download model files. Racing can run offline after the selected model has been cached.
- Callouts are generated server-side; browser-specific RotorHazard voice settings do not affect Local Voice output.
- If no Sendspin browser player is connected, generated audio is dropped and logged.

## Troubleshooting

- **No audio in the browser player**: confirm that `/player` is open, connected to the correct host, and that port `8927` is reachable from the playback device.
- **Duplicate voice callouts**: set RotorHazard Voice Volume to `0` in all regular RotorHazard browser clients.
- **First phrase is slow**: the selected Piper model may be downloading or loading. Watch the RotorHazard log for Local Voice status messages.
- **Browser playback stutters**: try Safari or a Chrome incognito window with extensions disabled, then validate on the actual race network.
