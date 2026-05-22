# Changelog

All notable shipped changes to Local Voice should be documented in this file.

This changelog is intentionally concise. GitHub Releases can carry the fuller change list and release assets.

## [0.1.0] - 2026-05-22

### Local voice generation

Local Voice can now generate RotorHazard callouts on the timing server with Piper TTS, without relying on browser speech or cloud services. Voice models are downloaded on first use, cached locally, and configured from the RotorHazard settings panel.

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

This release requires Python 3.12 or newer. The selected Piper model needs internet access once for the initial download, and regular RotorHazard browser clients should have Voice Volume set to `0` when Local Voice is handling callouts.
