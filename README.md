<p align="center">
  <picture>
    <img alt="Local Voice" src="https://raw.githubusercontent.com/dutchdronesquad/rh-local-voice/develop/custom_plugins/local_voice/player/favicon.svg" width="96">
  </picture>
</p>

<p align="center">
  <strong>Local server-side voice callouts for RotorHazard, powered by Piper TTS and Sendspin.</strong>
</p>

<p align="center">
  <a href="https://github.com/dutchdronesquad/rh-local-voice/actions/workflows/linting.yaml"><img
    src="https://github.com/dutchdronesquad/rh-local-voice/actions/workflows/linting.yaml/badge.svg"
    alt="Linting"
  /></a>
  <a href="https://github.com/dutchdronesquad/rh-local-voice/actions/workflows/rhfest.yaml"><img
    src="https://github.com/dutchdronesquad/rh-local-voice/actions/workflows/rhfest.yaml/badge.svg"
    alt="RHFest"
  /></a>
  <a href="LICENSE"><img
    src="https://img.shields.io/badge/license-MIT-blue"
    alt="License"
  /></a>
</p>

<p align="center">
  <a href="https://github.com/dutchdronesquad/rh-local-voice/releases/latest"><strong>Download</strong></a>
  &middot;
  <a href="docs/usage.md"><strong>Usage Guide</strong></a>
  &middot;
  <a href="https://github.com/sendspin"><strong>Sendspin</strong></a>
  &middot;
  <a href="CONTRIBUTING.md"><strong>Contributing</strong></a>
</p>

<p align="center">
  Local Voice generates RotorHazard announcements on the timing server, caches reusable WAV files,
  and sends playback to a local Sendspin service for network clients.
</p>

<p align="center">
  <img alt="Local Voice showcase" src="https://raw.githubusercontent.com/dutchdronesquad/rh-local-voice/develop/.github/assets/screenshot.png" width="800">
</p>

# Local Voice

Server-side voice callouts for the [RotorHazard] timing platform, powered by [Piper TTS]. Audio is generated locally on the RotorHazard server and sent to `sendspin-service`, which streams to connected clients using the [Sendspin] protocol — no cloud services required.

## What you can do

- 🎙️ **Local TTS**: Generates voice callouts with [Piper TTS] entirely on-device.
- 📡 **Sendspin service playback**: Sends generated WAV files to a local service that streams PCM audio to connected Sendspin clients over WebSocket, including [WindowsSpin].
- 🌐 **Browser player**: A built-in web player accessible at `/player`.
- 🎛️ **Configurable voice**: Adjustable speech speed, noise scale, and phoneme width from the RotorHazard settings panel.
- ⚡ **Smart caching**: Reusable pilot-name and lap-number segments are cached separately; use **Rebuild pre-cache** after startup or voice model/settings changes to prepare them ahead of racing.

## Requirements

- [RotorHazard] with RHAPI plugin support.
- Python 3.12 or newer.
- `sendspin-service` installed on the RotorHazard host or another reachable machine.
- Network access from playback clients to the RotorHazard server.
- A browser on the playback device. The plugin serves its own Sendspin player at `/player`.

## Quick Start

1. Download the plugin ZIP from the latest GitHub release.
2. In RotorHazard, open the plugin manager and upload the ZIP file.
3. Restart RotorHazard if requested.
4. Download the matching `sendspin-service_*.deb` from the same GitHub release and install it on the RotorHazard host.
5. Open the RotorHazard settings page and enable **Local Voice**.
6. Confirm **Sendspin service URL** points to the service, normally `http://127.0.0.1:8766`.
7. Open `/player` from the RotorHazard host on the playback device.
8. Use **Rebuild pre-cache** to prepare schedule, pilot-name, and lap-number WAV files.
9. Use **Generate test phrase** or **Play audio check** to verify playback.

The first generated phrase for a voice model downloads the Piper model into the RotorHazard data cache. That can take a moment depending on the server and network connection.

## Documentation

- [Usage Guide](docs/usage.md): setup, settings, browser player, cache layout, operational notes, and troubleshooting.
- [Changelog](CHANGELOG.md): release history.
- [Contributing](CONTRIBUTING.md): development setup and contribution guidelines.

## Sponsors

If Local Voice helps your club, event, or race-day workflow, you can help fund continued development and maintenance.

- Support the project through [GitHub Sponsors](https://github.com/sponsors/klaasnicolaas)
- Send a one-off contribution through [Ko-fi](https://ko-fi.com/klaasnicolaas)

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and development guidelines.

<a href="https://github.com/dutchdronesquad/rh-local-voice/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=dutchdronesquad/rh-local-voice" alt="Contributors" />
</a>

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
[Sendspin]: https://github.com/sendspin
[WindowsSpin]: https://github.com/sendspin/windowsspin

[license-shield]: https://img.shields.io/github/license/dutchdronesquad/rh-local-voice.svg
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026.svg
[project-stage-shield]: https://img.shields.io/badge/project%20stage-experimental-yellow.svg
[rhfest-shield]: https://github.com/dutchdronesquad/rh-local-voice/actions/workflows/rhfest.yaml/badge.svg
[rhfest-url]: https://github.com/dutchdronesquad/rh-local-voice/actions/workflows/rhfest.yaml
