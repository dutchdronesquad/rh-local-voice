# Sendspin Service Package — Plan of Approach

## Problem

Local Voice needs reliable Sendspin playback without making RotorHazard own the Sendspin server process.

The mixed model caused avoidable complexity:

- RotorHazard could start an internal Sendspin server.
- A separate Sendspin service could also run on the same host.
- Both competed for port `8927`.
- The plugin needed lifecycle/mode handling that users should not have to understand.
- Sendspin changes were split between plugin code and service code.

For a Raspberry Pi race setup, the service should be installed once, managed by systemd, and reused by the plugin.

## Decision

Local Sendspin playback should be service-owned, not RotorHazard-plugin-owned.

```text
Local Voice plugin
  -> generates/caches WAV files
  -> POSTs inline WAV payloads to http://127.0.0.1:8766

sendspin-service
  -> owns the Sendspin server/player endpoint on :8927
  -> runs under systemd
  -> streams audio to browser/player clients
```

The plugin should not start an internal Sendspin server during RotorHazard startup. Cloud output can later be added as a parallel target; local service playback remains the race-day priority.

## User-Facing Goal

The race operator should not need to understand Python, `uv`, virtualenvs, or package layout.

Target install:

```shell
sudo apt install ./sendspin-service_0.1.0_arm64.deb
sudo systemctl status sendspin-service
curl http://127.0.0.1:8766/health
```

The plugin defaults to:

```text
Sendspin service URL: http://127.0.0.1:8766
```

If the service is stopped or missing, the plugin should log a direct message that points at the configured service URL.

## Current State

- Plugin output uses `SendspinServiceClient` in `custom_plugins/local_voice/output.py`.
- The service API accepts `wav_files` inline base64 payloads. `wav_paths` is not part of the supported API.
- The packaged service runs with `DynamicUser=yes`, so it does not need read access to RotorHazard/plugin cache directories.
- Service packaging uses a uv-built bundled CPython runtime and `nfpm`.
- The service package dependency set is separate from the plugin dependency set.
- `av`, `numpy`, and `pillow` are currently required by the `aiosendspin` runtime path.

The old plugin-side `custom_plugins/local_voice/sendspin.py` may remain temporarily while active branches are cleaned up, but it is no longer the normal runtime path.

## Runtime Strategy

The `.deb` should be self-contained per architecture. It should not depend on the RotorHazard venv, the host Python version, or user-run `pip`/`uv` commands.

Chosen direction: bundled CPython runtime plus app dependency directory, built with `uv` and packaged with `nfpm`.

Rejected or fallback options:

- **System Python dependency**: smaller package, but too dependent on whatever Python version the Pi has installed.
- **PyInstaller/Nuitka single binary**: still possible later, but less transparent to debug than a bundled runtime layout.

Why bundled runtime is preferred:

- normal `.deb` install/update UX
- predictable Python version
- inspectable Python files and stack traces
- separate service dependencies from plugin-only dependencies such as Piper/model tooling

The trade-off is package size. Current `aiosendspin` imports require `av`, `numpy`, and `pillow`, so the service package is not tiny.

## Package Targets

Build at least:

```text
sendspin-service_0.1.0_amd64.deb
sendspin-service_0.1.0_arm64.deb
```

Architecture usage:

- `amd64`: Ubuntu VM, laptop, server testing.
- `arm64`: Raspberry Pi 4/5 running 64-bit Raspberry Pi OS.

Do not support `armhf` initially unless 32-bit Raspberry Pi OS becomes a real requirement.

## Package Layout

Install layout:

```text
/opt/sendspin-service/
  runtime/
  app/
  bin/sendspin-service

/etc/default/sendspin-service
/lib/systemd/system/sendspin-service.service
```

Default service config:

```text
SENDSPIN_INGEST_HOST=127.0.0.1
SENDSPIN_INGEST_PORT=8766
SENDSPIN_HOST=0.0.0.0
SENDSPIN_PORT=8927
SENDSPIN_ADVERTISE=true
SENDSPIN_MAX_BODY_MB=50
```

Systemd behavior:

- enable and restart service after install/upgrade
- preserve `/etc/default/sendspin-service` on upgrade
- stop and disable service on remove
- remove config/state on purge

Useful user/admin commands:

```shell
sudo apt install ./sendspin-service_0.1.0_arm64.deb
sudo apt install --reinstall ./sendspin-service_0.1.0_arm64.deb
systemctl status sendspin-service
journalctl -u sendspin-service -n 80 --no-pager
sudo apt remove sendspin-service
sudo apt purge sendspin-service
```

The target user should not need Python, `uv`, `pip`, or knowledge of the package layout on the race machine.

## Package Strategy

Chosen direction: self-contained `.deb` with bundled CPython runtime and app dependencies.

Reasons:

- avoids depending on the host Python version
- keeps install/update UX to a normal `.deb`
- keeps Python files and stack traces inspectable
- is easier to debug than an opaque single binary

Build command:

```shell
python -m tools.build_sendspin_service_deb
```

Build inputs:

- `tools/build_sendspin_service_deb.py`
- `packaging/nfpm.yaml`
- `packaging/deb/sendspin-service.service`
- `packaging/deb/sendspin-service.default`
- `packaging/deb/postinst`
- `packaging/deb/prerm`
- `packaging/deb/postrm`

## Current Measurements

Latest observed package/runtime characteristics on `amd64` after restoring required `av` runtime dependency:

```text
.deb size: ~66.5 MiB
installed size: ~237.4 MiB
runtime memory: ~191.5 MiB RSS, ~192.2 MiB peak
startup/test CPU: ~3.2s
large dependencies: av, av.libs, numpy, numpy.libs, pillow.libs
```

Important measurement history:

- PyInstaller prototype: ~86.1 MiB `.deb`, ~86.9 MiB installed.
- Bundled runtime after pruning without NumPy: ~15.3 MiB `.deb`, ~69.2 MiB installed, invalid because `aiosendspin.server` imports NumPy.
- Bundled runtime with `numpy`/`pillow` but without `av`: starts, but fails during playback because `aiosendspin` imports PyAV.
- Bundled runtime with `av`/`numpy`/`pillow`: larger, but currently correct.

## Completed

- [x] Add standalone `sendspin_service/` package.
- [x] Add service HTTP API with `/health`, `/v1/play`, and `/v1/stop`.
- [x] Add service-side queue and Sendspin adapter.
- [x] Add explicit startup failure for Sendspin port conflicts.
- [x] Add clean service shutdown path.
- [x] Switch plugin playback to service HTTP output.
- [x] Stop RotorHazard from binding Sendspin port `8927`.
- [x] Use inline WAV payloads instead of service-side filesystem reads.
- [x] Split plugin dependencies from service dependencies.
- [x] Build `.deb` with bundled runtime and `nfpm`.
- [x] Validate install/remove/purge basics on Ubuntu VM.
- [x] Confirm `wav_paths` is not part of the supported service API.
- [x] Add GitHub Actions workflow for service package builds.
- [x] Publish both `amd64` and `arm64` package artifacts on release.

## Still To Do

- [ ] Verify plugin playback through installed `sendspin-service` on the Ubuntu VM after the HTTP-output switch.
- [ ] Rebuild `.deb` after the final dependency set and record updated size.
- [ ] Verify `/opt/sendspin-service/bin/sendspin-service --help` from the installed package.
- [ ] Verify config survives upgrade install.
- [ ] Build and test `arm64` package on Raspberry Pi OS.
- [ ] Confirm Raspberry Pi memory/startup behavior is acceptable.
- [ ] Remove old plugin-side `custom_plugins/local_voice/sendspin.py` once active branches no longer need it.

## Local Testing On Ubuntu VM

The Ubuntu VM is the primary `amd64` package lifecycle test environment.

```shell
python -m tools.build_sendspin_service_deb
cp dist/sendspin-service_0.1.0_amd64.deb /tmp/
sudo apt install /tmp/sendspin-service_0.1.0_amd64.deb
systemctl status sendspin-service
curl http://127.0.0.1:8766/health
```

Upgrade/reinstall tests:

```shell
sudo apt install --reinstall /tmp/sendspin-service_0.1.0_amd64.deb
sudo apt install /tmp/sendspin-service_0.1.1_amd64.deb
```

Removal tests:

```shell
sudo apt remove sendspin-service
sudo apt purge sendspin-service
```

Acceptance:

- install succeeds without target-machine `uv`, `pip`, or Python setup
- service starts after install
- `/health` returns `ok`, `version`, `sendspin_port`, and `connected_players`
- config file is used
- config survives upgrade
- remove stops service but preserves config
- purge removes config/state
- port conflicts on `8766` and `8927` produce clear logs

## Raspberry Pi `arm64` Package

Goal: produce and validate the package on 64-bit Raspberry Pi OS.

Build checklist:

- [x] Add `arm64` build path in CI or documented local build.
- [ ] Build `sendspin-service_0.1.0_arm64.deb`.
- [ ] Record `.deb` size and installed size.
- [ ] Verify native dependencies are built for `arm64`.

Pi install checklist:

- [ ] Install on clean 64-bit Raspberry Pi OS.
- [ ] Confirm no `uv`, `pip`, or Python version setup is needed.
- [ ] Confirm systemd service auto-starts.
- [ ] Confirm `/health` works.
- [ ] Confirm browser player can connect on port `8927`.
- [ ] Confirm Local Voice plugin can POST to `127.0.0.1:8766`.
- [ ] Confirm **Play audio check** works.
- [ ] Confirm race callouts work under normal event load.
- [ ] Confirm memory/startup behavior is acceptable on the Pi.

Failure checklist:

- [ ] Stop service and confirm plugin logs a clear unreachable-service message.
- [ ] Occupy port `8927` and confirm service logs clear port conflict.
- [ ] Occupy port `8766` and confirm service logs clear port conflict.
- [ ] Reboot Pi and confirm service starts automatically.

Acceptance:

- `arm64` package is usable by a normal Pi user with one `apt install` command.
- package size is recorded and judged acceptable for Pi installs.
- service remains independent from RotorHazard restarts.

## Build And Deployment Workflows

Add separate CI workflows so package/release work is repeatable.

Actual workflows:

```text
.github/workflows/release.yaml       — builds amd64 + arm64 .deb on release, uploads to GitHub Release
.github/workflows/build.yaml         — builds amd64 .deb on PR when service files change
.github/actions/build-sendspin-deb/  — composite action shared by both workflows
```

Still needed:

```text
.github/workflows/sendspin-docker.yml  — Docker image builds for cloud target
```

Test workflow (not yet created):

- lint service code
- compile/import checks
- API unit tests
- package metadata checks

Docker workflow:

- build `linux/amd64` image
- build `linux/arm64` image
- push to GHCR
- tag images with release version and `latest`

Expected artifacts:

```text
sendspin-service_0.1.0_amd64.deb
sendspin-service_0.1.0_arm64.deb
ghcr.io/<owner>/sendspin-service:0.1.0
```

## Docker / Cloud Path

Docker is the primary deployment format for cloud Sendspin targets. The local Pi path stays `.deb` + systemd.

Example target shape:

```shell
docker run \
  -p 8766:8766 \
  -p 8927:8927 \
  ghcr.io/<owner>/sendspin-service:0.1.0
```

Cloud deployment adds concerns that should not leak into the local package:

- HTTPS termination
- token auth
- event/session identity
- QR landing page/player join flow
- session cleanup/expiry
- observability for remote playback issues

Keep the local and cloud API shared where practical:

- `GET /health`
- `POST /v1/play`
- `POST /v1/stop`

But keep deployment concerns separate:

- `.deb`/systemd for local Pi/Ubuntu installs
- Docker/GHCR for cloud and container deployments
- plugin fan-out later for local + cloud output in parallel

## Cloud Target And QR Flow

Goal: allow remote listeners to join with a QR code while local PA playback remains independent.

Plugin checklist:

- [ ] Add optional cloud output enable setting.
- [ ] Add cloud URL/token/event config.
- [ ] Send local and cloud outputs independently.
- [ ] Keep local timeout short and priority high.
- [ ] Ensure cloud failure never blocks local playback.
- [ ] Fan out stop commands to enabled targets.

Cloud service checklist:

- [ ] Keep shared service API semantics.
- [ ] Add HTTPS deployment pattern.
- [ ] Add auth/token handling.
- [ ] Add event/session identity.
- [ ] Add QR join page.
- [ ] Add phone player flow.
- [ ] Add cleanup/expiry rules for event sessions.

Docker checklist:

- [ ] Build `linux/amd64` image.
- [ ] Build `linux/arm64` image.
- [ ] Push to GHCR.
- [ ] Document cloud deployment example.

Acceptance:

- local PA playback remains functional if cloud is down.
- phone listener can join with QR code and hear callouts.
- cloud failures are visible but non-fatal.

## Release Gate

Before making the service-only path the release default:

- Ubuntu VM package install/upgrade/remove/purge passes.
- Raspberry Pi `arm64` package install and playback test passes.
- `Play audio check` works through the installed service.
- Service logs clear errors for port conflicts and unreachable clients.
- Documentation covers install, upgrade, logs, remove, and purge.

## Release Automation Gate

Before public release packages are attached to GitHub Releases:

- [ ] One source of truth for service version.
- [ ] Version included in package name, `/health`, Docker tags, and release notes.
- [x] Tagged release builds `amd64` and `arm64` `.deb` packages.
- [ ] Tagged release builds `linux/amd64` and `linux/arm64` Docker images.
- [x] Release artifacts are named consistently.
- [ ] Checksums are published.
- [ ] User update instructions are documented.

## Later

- Cloud Sendspin target for QR/phone listeners.
- Optional service auth if the ingest API is bound beyond localhost.
- Possible upstream work with `aiosendspin` to avoid importing heavy optional roles/dependencies for PCM-only playback.

## Open Questions

- Should package install always restart the service, or only enable it and leave start/restart to the user?
- How strict should auth be for localhost-only installs?
- Can `aiosendspin` make `av`, `numpy`, or `pillow` optional for PCM-only service usage later?
- Which active branches still need anything from the old plugin-side `sendspin.py` before it is removed?
