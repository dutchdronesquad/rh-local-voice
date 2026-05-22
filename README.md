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
  <a href="https://github.com/RotorHazard/RotorHazard"><strong>RotorHazard</strong></a>
  &middot;
  <a href="https://github.com/sendspin"><strong>Sendspin</strong></a>
  &middot;
  <a href="CONTRIBUTING.md"><strong>Contributing</strong></a>
</p>

<p align="center">
  Local Voice generates RotorHazard announcements on the timing server, caches reusable WAV files,
  and streams playback to one or more Sendspin clients over the local network.
</p>

<p align="center">
  <img alt="Local Voice showcase" src="https://raw.githubusercontent.com/dutchdronesquad/rh-local-voice/develop/.github/assets/screenshot.png" width="800">
</p>

# Local Voice

Server-side voice callouts for the [RotorHazard] timing platform, powered by [Piper TTS]. Audio is generated locally on the RotorHazard server and streamed to connected clients over the network using the [Sendspin] protocol — no cloud services required.

## What you can do

- 🎙️ **Local TTS**: Generates voice callouts with [Piper TTS] entirely on-device.
- 📡 **Sendspin streaming**: Streams PCM audio to one or more clients over WebSocket for synchronised multi-room playback.
- 🌐 **Browser player**: A built-in web player accessible at `/player`, compatible with any Sendspin client (e.g. [WindowsSpin]).
- 🎛️ **Configurable voice**: Adjustable speech speed, noise scale, and phoneme width from the RotorHazard settings panel.
- ⚡ **Smart caching**: Synthesised WAV files are cached by content hash; ephemeral lap-time files are discarded after each heat.

## How it works

Local Voice hooks into RotorHazard's phonetic callout events. When a race event needs speech, the plugin synthesises the phrase with Piper, stores the WAV in the RotorHazard data cache, and queues it for Sendspin playback.

Lap callouts are split into reusable and time-sensitive parts. Pilot names and lap numbers can be cached across heats, while lap-time audio is written to a temporary cache and cleared when the heat changes.

## Requirements

- [RotorHazard] with RHAPI plugin support.
- Python 3.12 or newer.
- Network access from playback clients to the RotorHazard server.
- A Sendspin playback client, either the built-in browser player at `/player` or another compatible client such as [WindowsSpin].

## Installation

1. Download the plugin ZIP from the latest GitHub release.
2. In RotorHazard, open the plugin manager and upload the ZIP file.
3. Restart RotorHazard if requested.
4. Open the RotorHazard settings page and enable **Local Voice**.

The first generated phrase for a voice model downloads the Piper model into the RotorHazard data cache. That can take a moment depending on the server and network connection.

## Usage

1. In RotorHazard, open **Settings** → **Local Voice**.
2. Enable **Plugin audio**.
3. Choose a voice model and adjust the speech parameters if needed.
4. Open `/player` from the same RotorHazard host in a browser tab, for example `http://localhost:5000/player`.
5. Set normal RotorHazard browser voice volume to `0` on clients that should only use Local Voice audio.
6. Use **Generate test phrase** or **Play audio check** to verify playback.

The Sendspin server listens on port `8927`. If another machine is used for playback, make sure that port is reachable on the local network.

## Settings

- **Enable plugin audio**: Turns Local Voice callout generation on or off.
- **Voice model**: Selects the Piper voice model. Models are downloaded once and reused.
- **Speech speed**: Controls speaking rate. `1.0` is Piper default; lower is slower, higher is faster.
- **Noise scale**: Controls voice variation. Lower values are more monotone; higher values are more expressive.
- **Phoneme width noise**: Controls duration variation between phonemes.
- **Crossing enter / exit beeps**: Adds short local beeps for crossing events.
- **Test phrase**: Phrase used by the **Generate test phrase** button.

## Browser Player

The built-in browser player is served by the plugin at `/player`. It connects to Sendspin over WebSocket and plays the streamed PCM audio in the browser.

During local testing, Safari on macOS produced the smoothest browser playback. Chrome can work well too, but browser extensions may add console noise or small timing interruptions. If playback jitter appears in Chrome, test once in an incognito window with extensions disabled before debugging the server.

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
