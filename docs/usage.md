# Usage Guide

Race Voice generates RotorHazard callout WAV files on the timing server and sends them to `sendspin-service` over HTTP. The RotorHazard plugin serves its browser player at `/player`; the standalone service/container serves its player at `/`.

The plugin ZIP and service `.deb` are separate release assets. Install both for a normal RotorHazard setup: the plugin provides RotorHazard integration and the `/player` page, while `sendspin-service` provides playback transport.

## Setup

1. Install and start `sendspin-service`.
2. In RotorHazard, open **Settings** -> **Race Voice**.
3. Enable **Plugin audio**.
4. Confirm **Sendspin service URL** is `http://127.0.0.1:8766`.
5. Choose a voice model and speech settings.
6. Open the browser player from the RotorHazard UI on the playback device, for example `<RotorHazard UI base URL>/player`.
7. Set normal RotorHazard browser Voice Volume to `0` on clients that should not play duplicate built-in callouts.
8. Use **Generate test phrase** or **Play audio check**.

## Sendspin Service

Install target:

```shell
sudo apt install ./sendspin-service_0.1.0_arm64.deb
```

Download the matching package from the GitHub Release assets. Use `arm64` for 64-bit Raspberry Pi OS and `amd64` for Ubuntu/laptop testing.

Common checks:

```shell
systemctl status sendspin-service
curl http://127.0.0.1:8766/health
journalctl -u sendspin-service -n 80 --no-pager
```

Default config is stored in `/etc/default/sendspin-service`:

```shell
SENDSPIN_INGEST_HOST=127.0.0.1
SENDSPIN_INGEST_PORT=8766
SENDSPIN_HOST=0.0.0.0
SENDSPIN_PORT=8927
SENDSPIN_ADVERTISE=true
SENDSPIN_MAX_BODY_MB=50
```

The service API accepts inline WAV payloads via `wav_files`. It does not accept filesystem paths. This keeps the packaged service independent of RotorHazard/plugin directory permissions while running with `DynamicUser=yes`.

## Docker Image

The Docker image is the container deployment path for `sendspin-service`. For a normal Raspberry Pi timing-server install, use the `.deb` package instead.

Basic local container run:

```shell
docker run --rm \
  -p 8766:8766 \
  -p 8927:8927 \
  ghcr.io/dutchdronesquad/sendspin-service:latest
```

Docker Compose:

```shell
cp .env.example .env
sed -i "s/change-this-token/$(openssl rand -hex 32)/" .env
docker compose up -d
```

The included Compose file builds the local Dockerfile by default. To run the published image instead, replace the `build:` block with `image: ghcr.io/dutchdronesquad/sendspin-service:latest`.

The container serves the browser player at `http://<container-host>:8766/`. The HTTP ingest API is on the same port under `/v1`, and the health check is available at `/health`. Browser clients connect to the Sendspin WebSocket endpoint on port `8927` at `/sendspin`.

Container defaults:

```shell
SENDSPIN_INGEST_HOST=0.0.0.0
SENDSPIN_INGEST_PORT=8766
SENDSPIN_HOST=0.0.0.0
SENDSPIN_PORT=8927
SENDSPIN_ADVERTISE=false
SENDSPIN_MAX_BODY_MB=50
SENDSPIN_PLAYER_DIR=/opt/sendspin-service/player
```

For a public container deployment, set `SENDSPIN_API_TOKEN` before exposing port `8766`. Producers must send `Authorization: Bearer <token>` for `/v1/play` and `/v1/stop`. Keep it unset only for local-only testing on a trusted machine.

The image does not include the RotorHazard plugin. The bundled player is for direct container use; the normal RotorHazard plugin ZIP still serves its own `/player` route.

Manual playback test:

```shell
python - <<'PY'
import base64
import json
import urllib.request

wav_data = base64.b64encode(
    open("custom_plugins/local_voice/assets/moavii-foreign.wav", "rb").read()
).decode("ascii")
payload = json.dumps({
    "text": "audio check",
    "wav_files": [{"name": "moavii-foreign.wav", "data": wav_data}],
    "priority": "high",
    "volume": 1.0,
}).encode("utf-8")
request = urllib.request.Request(
    "http://127.0.0.1:8766/v1/play",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(request).read().decode("utf-8"))
PY
```

## Package Build

Maintainer build requirements: `uv`, `nfpm`, and a local Python 3.11+ interpreter for the build script.

```shell
python -m tools.build_sendspin_service_deb
```

Build for a specific architecture on a matching runner:

```shell
python -m tools.build_sendspin_service_deb --architecture arm64
```

For local install testing, copy the `.deb` to `/tmp` first so `apt` can read it through its `_apt` sandbox user:

```shell
rm -f /tmp/sendspin-service_*.deb
cp dist/sendspin-service_*_amd64.deb /tmp/
sudo apt install /tmp/sendspin-service_*_amd64.deb
```

Reinstall the same local version:

```shell
sudo apt install --reinstall /tmp/sendspin-service_*_amd64.deb
```

Package CI:

- Pull requests that touch service/package files build the `amd64` `.deb` through `.github/workflows/build.yaml`.
- Published GitHub Releases build and upload both `amd64` and `arm64` `.deb` assets through `.github/workflows/release.yaml`.
- The shared build logic lives in `.github/actions/build-sendspin-deb/action.yaml`.

## Settings

- **Enable plugin audio**: Turns Race Voice callout generation on or off.
- **Sendspin service URL**: HTTP endpoint for `sendspin-service`. Default: `http://127.0.0.1:8766` when the plugin and service run on the same host.
- **Sendspin service timeout**: HTTP timeout for queue/stop requests to `sendspin-service`.
- **Voice model**: Piper voice model. Models are downloaded once and reused.
- **Speech speed**: Speaking rate. `1.0` is Piper default.
- **Noise scale**: Voice variation.
- **Phoneme width noise**: Duration variation between phonemes.
- **Test phrase**: Phrase generated by the **Generate test phrase** button.

## Cache Layout

Generated files live under the RotorHazard data directory:

```text
local_voice_cache/
  models/                 downloaded Piper ONNX models
  tts/<model>/            cached phrases
  tts/<model>/precache/   reusable pilot, lap, and schedule phrases
  tts/<model>/tmp/        ephemeral lap-time phrases
  tts/<model>/test/       generated test phrases
```

Use **Rebuild pre-cache** after startup or voice setting changes to prepare current-heat pilot names, lap segments, and schedule phrases.

## Troubleshooting

- **No audio in `/player`**: confirm `sendspin-service` is running, the player Server URL points at the same service RotorHazard sends to, and the player is connected.
- **Service unreachable**: confirm `curl http://127.0.0.1:8766/health` works from the RotorHazard host.
- **Player page unreachable**: confirm `<RotorHazard UI base URL>/player` works from the playback device.
- **Duplicate voice callouts**: set RotorHazard Voice Volume to `0` in regular RotorHazard browser clients.
- **First phrase is slow**: the selected Piper model may still be downloading or loading.
- **Browser playback stutters**: test Safari or Chrome incognito with extensions disabled, then validate on the race network.
