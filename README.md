<!-- PLUGIN BADGES -->
![Project Stage][project-stage-shield]
![Project Maintenance][maintenance-shield]
[![License][license-shield]](LICENSE)

[![RHFest][rhfest-shield]][rhfest-url]

# Local Voice

Server-side voice callouts for the [RotorHazard] timing platform, powered by [Piper TTS]. Audio is generated locally on the RotorHazard server and streamed to connected clients over the network using the [SendSpin] protocol — no cloud services required.

## Features

- **Local TTS**: Generates voice callouts with [Piper TTS] entirely on-device.
- **SendSpin streaming**: Streams PCM audio to one or more clients over WebSocket for synchronised multi-room playback.
- **Browser player**: A built-in web player accessible at `/player`, compatible with any SendSpin client (e.g. [WindowsSpin]).
- **Configurable voice**: Adjustable speech speed, noise scale, and phoneme width from the RotorHazard settings panel.
- **Smart caching**: Synthesised WAV files are cached by content hash; ephemeral lap-time files are discarded after each heat.

## Development

This Python project relies on [uv] as its dependency manager.

You need the following tools to get started:

- [uv] — Python virtual environment and package manager
- [Python] 3.12 or higher
- [Node.js] 20 or higher (for the browser player)

### Installation

1. Clone the repository.
2. Install Python dependencies:

```bash
uv sync --all-groups
```

3. Install browser player dependencies:

```bash
cd player && npm install
```

### Pre-commit checks

This repository uses the [prek] framework. All changes are linted and tested on each commit.

Install the pre-commit hook:

```bash
uv run prek install
```

Run all checks manually:

```bash
uv run prek run --all-files
```

Run checks on staged files only:

```bash
uv run prek run
```

### Browser Player

The SendSpin browser player source lives in `player/` and is built with Vite + Preact.

```bash
cd player
npm run dev      # local dev server
npm run check    # type-check
npm run lint     # lint
npm run build    # production build → custom_plugins/local_voice/player/
```

`npm run build` writes the production build to `custom_plugins/local_voice/player/`. The `assets/` subdirectory is not committed to git and must be built locally before deploying.

> **Browser compatibility note**: During local testing, Safari on macOS gave the smoothest playback experience. Chrome on macOS occasionally showed small playback interruptions and more sync-error movement, particularly with browser extensions active. When testing sync quality in Chrome, use an incognito window with extensions disabled before treating jitter as a server-side issue.

## Credits

The bundled audio check track is:

- Music track: Foreign by Moavii
- Source: <https://freetouse.com/music>
- Free Music Without Copyright (Safe)

## License

Distributed under the **MIT** License. See [`LICENSE`](LICENSE) for more information.

<!-- LINKS -->
[RotorHazard]: https://github.com/RotorHazard/RotorHazard
[Piper TTS]: https://github.com/OHF-Voice/piper1-gpl
[SendSpin]: https://github.com/sendspin
[WindowsSpin]: https://github.com/sendspin/windowsspin
[uv]: https://docs.astral.sh/uv/
[Python]: https://www.python.org/
[Node.js]: https://nodejs.org/
[prek]: https://prek.j178.dev/

[license-shield]: https://img.shields.io/github/license/dutchdronesquad/rh-local-voice.svg
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026.svg
[project-stage-shield]: https://img.shields.io/badge/project%20stage-experimental-yellow.svg
[rhfest-shield]: https://github.com/dutchdronesquad/rh-local-voice/actions/workflows/rhfest.yaml/badge.svg
[rhfest-url]: https://github.com/dutchdronesquad/rh-local-voice/actions/workflows/rhfest.yaml
