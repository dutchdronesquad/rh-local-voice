# Changelog

All notable shipped changes to Race Voice should be documented in this file.

This changelog is intentionally concise. GitHub Releases can carry the fuller change list and release assets.

## [0.2.0] - 2026-05-24

### Scheduled race callouts

Race Voice now listens to RotorHazard race schedule events and can announce countdowns before a deferred race start. The default countdown phrases cover 60, 30, 10, and 5 seconds before the scheduled start, and pending countdowns are cancelled when the schedule is replaced or cancelled.

Countdown phrases are localized alongside lap callouts for the supported voice-model languages:

- English
- Dutch
- German

### Faster race-day pre-cache

Pre-cache rebuilding has been split into reusable segments for pilot names, lap numbers, and scheduled-race countdowns. This keeps repeated lap announcements fast while allowing temporary lap-time audio to remain heat-specific.

The pre-cache rebuild action now cancels stale rebuild jobs, reports completion for the current heat, and clears the relevant pre-cache folders before regenerating audio for the selected model.

### Sendspin playback

Sendspin playback can now schedule audio against a future playback time instead of only appending immediate clips. This improves scheduled countdown timing and allows future clips to be fully buffered before playback starts.

Queued audio now carries a per-job volume value, and the Sendspin backend applies linear gain to PCM audio while leaving cached WAV files unchanged.

Playback buffering has also been tightened:

- Consecutive callouts are appended to an active stream without resetting connected clients.
- Late-joining Sendspin clients are synced into the active stream.
- Stale audio is dropped before scheduling if it would start after its expiry deadline.
- The active stream is stopped once queued playback has gone idle.

## [0.1.0] - 2026-05-22

### Local voice generation

Race Voice can now generate RotorHazard callouts on the timing server with Piper TTS, without relying on browser speech or cloud services. Voice models are downloaded on first use, cached locally, and configured from the RotorHazard settings panel.

For race operators, the main benefits are:

- Callouts keep working locally after the selected voice model has been downloaded.
- Voice output is configured once in RotorHazard instead of per browser client.
- Test phrases can be generated from the settings panel before race day.

### Sendspin playback

Generated audio is queued and streamed from an in-process Sendspin source to connected playback clients. The plugin includes its own browser player at `/player`, while other Sendspin clients such as [WindowsSpin](https://github.com/sendspin/windowsspin) can also connect to the stream.

### Race-day caching

Repeated phrases are cached so they do not need to be generated again during a race. Lap callouts are split into reusable pilot/lap phrases and temporary lap-time phrases, which keeps repeated announcements fast while avoiding stale lap-time audio after a heat change.

The audio queue also tracks priorities and expiry times so stale lap callouts can be dropped instead of playing too late after a busy gate crossing.

### Operator controls

The settings panel includes quick actions for generating a test phrase, playing an audio check clip, stopping current playback, and clearing the selected voice model's TTS cache.

This release requires Python 3.12 or newer. The selected Piper model needs internet access once for the initial download, and regular RotorHazard browser clients should have Voice Volume set to `0` when Race Voice is handling callouts.
