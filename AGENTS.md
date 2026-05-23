# AGENTS.md

## Project Context

Local Voice is a RotorHazard RHAPI plugin that generates voice callouts server-side with Piper TTS and streams the resulting WAV audio to Sendspin clients. The primary plugin package lives in `custom_plugins/local_voice/`.

Important modules:

- `plugin.py`: RotorHazard event/filter integration, synthesis scheduling, cache cleanup, pre-cache orchestration, and UI button callbacks.
- `piper.py`: Piper model download/loading, ONNX Runtime session setup, synthesis, text normalization, WAV validation, and cache-key generation.
- `audio_queue.py`: single-worker priority queue with expiry handling for stale audio.
- `sendspin.py`: synchronous adapter around `aiosendspin`, owns the background asyncio loop and active Sendspin stream.
- `ui.py`: RotorHazard settings panel, quick buttons, and `/player` blueprint.
- `const.py`: option names, defaults, voice model list, and Sendspin port.
- `services/`: small stateful helpers extracted from `plugin.py`; currently schedule countdown timers.
- `player/`: Vite/Preact source for the browser player; production output is written to `custom_plugins/local_voice/player/`.

## Runtime Behavior

RotorHazard phonetic filters are used as the callout source. Heavy work must stay off the RotorHazard event/filter thread; schedule synthesis through the existing executor instead of doing Piper work inline.

Lap callouts are intentionally split:

- reusable pilot/lap phrase: `"[name], Lap [n]"`, stored in the per-model `precache/` cache.
- dynamic lap-time phrase: stored in the per-model `tmp/` cache.

Do not clear `precache/` on `HEAT_SET`. A heat change should clear queued audio and `tmp/` only. Operators can use **Rebuild pre-cache** to generate reusable pilot/lap phrases for the current heat. RotorHazard data reset and the **Clear TTS cache** button may clear all model WAV cache content, including `precache/`.

Lap callouts should expire quickly enough to avoid stale race audio. The current lap expiry is intentionally longer than the queue default to handle several pilots crossing close together, but it should remain race-day conservative.

## Sendspin Notes

`SendSpinServer.play()` appends normal queued audio to the active stream instead of stopping and restarting playback. Preserve this behavior unless the user explicitly asks for interrupt-style playback.

The Sendspin backend checks expiry again before scheduling audio. Keep this Sendspin-side check when changing queue behavior, because queue delay and stream scheduling delay are separate concerns.

Late-joining Sendspin clients should be synced into the active group while playback is still scheduled to continue. Do not remove the periodic late-join sync during idle-tail waiting without replacing it with equivalent behavior.

## Cache Layout

Generated files live below RotorHazard's data directory:

```text
local_voice_cache/
  models/                 downloaded Piper ONNX models
  tts/<model>/            normal cached phrases
  tts/<model>/precache/   reusable pilot/lap phrases
  tts/<model>/tmp/        ephemeral lap-time phrases
  tts/<model>/test/       generated test phrases
```

Cache keys must include normalized phrase text and synthesis parameters so changing voice tuning does not reuse the wrong WAV.

## Dependency Policy

The plugin currently imports Piper and ONNX Runtime at module import time. Missing runtime dependencies are expected to fail through the normal RotorHazard/plugin dependency path rather than through a custom lazy-import layer.

Keep dependencies aligned between `pyproject.toml` and `custom_plugins/local_voice/manifest.json`.

## Development Checks

Python requires 3.12 or newer. Use `uv sync --all-groups` for the Python environment.

Useful checks:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run prek run --all-files`

The browser player source lives in `player/`:

- `npm run check`
- `npm run lint`
- `npm run build`

`npm run build` writes production files into `custom_plugins/local_voice/player/`. The release workflow builds the player and zips `custom_plugins` as `local_voice.zip`.

## Documentation Style

The README should stay selective: keep it focused on what Local Voice is, what it needs, and how to get started. Move day-to-day operation, settings, cache behavior, and troubleshooting details into files under `docs/`.

Keep user-facing docs aligned with actual race behavior, especially cache cleanup, browser playback, Sendspin port `8927`, and the need to set RotorHazard browser Voice Volume to `0` when Local Voice handles callouts.

## Changelog Style

Write changelog entries for end users and race operators, not as an internal implementation log.

Use a mixed format:

- Prefer short thematic sections with a few sentences of context.
- Use bullet lists when they make user impact easier to scan.
- Keep bullets meaningful: describe what the user can do, what changed in race-day behavior, or what they need to know before upgrading.
- Avoid long lists of internal modules, helper classes, refactors, or low-level implementation details unless they directly explain a user-visible behavior.
- GitHub Releases can carry the fuller generated change list; `CHANGELOG.md` should remain concise and readable.
