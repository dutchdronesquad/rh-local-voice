# Sendspin Service Package — Plan of Approach

## Problem

The Local Voice plugin needs a reliable way to play generated WAV callouts through Sendspin without making RotorHazard own the Sendspin server process.

The current mixed model has become harder than it needs to be:

- The plugin can start an internal Sendspin server.
- A separate local Sendspin service can also run on the same host.
- Both compete for the same Sendspin player port (`8927`) when misconfigured.
- The plugin has to expose internal/external mode selection and lifecycle handling.
- Sendspin code changes can touch both plugin code and service code.

For a Raspberry Pi install, the better long-term product direction is a dedicated Sendspin service package that is installed once and managed by systemd.

---

## Decision

Move to a **service-only local Sendspin architecture**.

```text
RotorHazard plugin
  -> generates/caches TTS WAV files
  -> POSTs playback jobs to http://127.0.0.1:8766

rh-sendspin-service
  -> receives playback jobs
  -> owns the Sendspin server/player endpoint on :8927
  -> runs as a systemd service
```

The plugin should no longer offer an internal Sendspin server mode as an end-user option.

Later, cloud output is added as a parallel target:

```text
RotorHazard plugin
  -> local rh-sendspin-service for PA/speakers
  -> cloud Sendspin service for QR/phone listeners
```

Local playback remains the race-day priority. Cloud failures must not delay or block local playback.

---

## User-Facing Goal

The user should not need to understand Python, `uv`, virtualenvs, or package layout.

Local install should look like:

```shell
sudo apt install ./rh-sendspin-service_0.1.0_arm64.deb
```

Then:

```shell
sudo systemctl status rh-sendspin-service
curl http://127.0.0.1:8766/health
```

The plugin should default to:

```text
Sendspin service URL: http://127.0.0.1:8766
```

If the service is missing or stopped, the plugin should show/log a direct message:

```text
Sendspin service is not reachable at http://127.0.0.1:8766.
Install or start rh-sendspin-service.
```

---

## Python Runtime Strategy

Important nuance: a `.deb` by itself does **not** automatically make Python irrelevant. It depends on what the package contains.

### Option A: Depends on system Python

The `.deb` declares a dependency such as:

```text
Depends: python3 (>= 3.12), python3-venv, ...
```

This is simple, but not ideal for Raspberry Pi users because installed Python versions vary.

### Option B: Embedded app environment

The `.deb` installs a private app directory under:

```text
/opt/rh-sendspin-service
```

That directory contains the service code plus its own Python environment/dependencies.

This avoids `uv` and manual `pip install`, but if the environment still points at `/usr/bin/python3`, the host Python version can still matter.

### Option C: Bundled runtime or single binary

The `.deb` contains either:

- a bundled CPython runtime plus app environment, or
- a PyInstaller/Nuitka-style executable.

This is the closest to "it does not matter which Python is installed".

**Preferred package goal:** the `.deb` should not depend on the RotorHazard venv and should not require users to run `uv` or `pip`. For the final user-facing package, aim for a self-contained runtime per architecture. During early development, an embedded venv/PEX is acceptable if the limitation is documented.

### Chosen direction

Target **Option C from the start** for the package work.

Reasoning:

- The service becomes a real product component, not a Python setup task.
- Users should not need to know or care which Python version is installed.
- Support is simpler when the service package owns its runtime.
- The install/update UX stays clean: `sudo apt install ./rh-sendspin-service_...deb`.

This makes the `.deb` larger, but that is an acceptable trade-off if the install is reliable.

Expected size range:

```text
Bundled runtime / binary .deb: roughly 80-250+ MB
```

The exact size depends on the packaging tool and native dependencies. The packaging work should explicitly track `.deb` size for both `amd64` and `arm64`.

Size reduction tactics:

- Avoid packaging plugin-only dependencies such as Piper TTS into the Sendspin service.
- Keep `sendspin_service` dependency scope separate from the plugin dependency scope.
- Prefer runtime tools that can strip unused metadata, tests, caches, and `__pycache__`.
- Use `--no-cache-dir` / clean build caches before packaging.
- Strip native binaries where safe.
- Audit whether heavy dependencies such as `av` are actually needed by the Sendspin service package.
- Keep model files out of the service package.
- Build per architecture instead of shipping universal artifacts.

The first package milestone should include a size report:

```text
amd64 .deb size:
arm64 .deb size:
installed size:
```

---

## Package Targets

Build at least:

```text
rh-sendspin-service_0.1.0_amd64.deb
rh-sendspin-service_0.1.0_arm64.deb
```

Architecture usage:

- `amd64`: Ubuntu VM, laptop, server testing.
- `arm64`: Raspberry Pi 4/5 running 64-bit Raspberry Pi OS.

Do not support `armhf` initially unless 32-bit Raspberry Pi OS becomes a real requirement.

Native dependencies must be built/tested per architecture. Packages like `av` can contain native wheels, so `amd64` and `arm64` artifacts should be produced separately.

---

## Debian Package Layout

Target package name:

```text
rh-sendspin-service
```

Install layout:

```text
/opt/rh-sendspin-service/
  bin/rh-sendspin-service
  app/...

/etc/default/rh-sendspin-service

/lib/systemd/system/rh-sendspin-service.service
```

Default config:

```shell
SENDSPIN_INGEST_HOST=127.0.0.1
SENDSPIN_INGEST_PORT=8766
SENDSPIN_PORT=8927
SENDSPIN_MAX_BODY_MB=100
SENDSPIN_WORK_DIR=/var/lib/rh-sendspin-service
```

Systemd service:

```ini
[Unit]
Description=RH Sendspin Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/default/rh-sendspin-service
ExecStart=/opt/rh-sendspin-service/bin/rh-sendspin-service
Restart=on-failure
RestartSec=2
DynamicUser=yes
StateDirectory=rh-sendspin-service

[Install]
WantedBy=multi-user.target
```

Post-install behavior:

- `systemctl daemon-reload`
- `systemctl enable rh-sendspin-service`
- start or restart service

Config in `/etc/default/rh-sendspin-service` should be preserved on upgrade.

---

## Update Model

Start with GitHub Releases.

Install:

```shell
sudo apt install ./rh-sendspin-service_0.1.0_arm64.deb
```

Upgrade:

```shell
sudo apt install ./rh-sendspin-service_0.2.0_arm64.deb
```

Remove:

```shell
sudo apt remove rh-sendspin-service
```

Purge:

```shell
sudo apt purge rh-sendspin-service
```

Later, an apt repository can be added without changing the package model:

```shell
sudo apt update
sudo apt install rh-sendspin-service
sudo apt upgrade
```

---

## Service API

Keep the service API stable because both local and cloud deployments can share it.

Required endpoints:

```text
GET  /health
POST /v1/play
POST /v1/stop
```

Health response should include version:

```json
{
  "ok": true,
  "version": "0.1.0",
  "sendspin_port": 8927,
  "connected_players": 0
}
```

The plugin can use this later to warn about old service versions.

---

## Plugin Simplification

Remove the internal/external local mode choice from the product model, but do
not delete the internal implementation until the service package has shipped and
been validated on `amd64` and `arm64`.

Eventually remove:

- `Sendspin local mode`
- `Internal server`
- `Disabled` local mode
- `InternalSendspinOutput`
- plugin-managed `SendSpinServer`
- plugin port preflight for `8927`
- live switching between internal/external modes

Migration rule:

- Internal Sendspin may remain in code as a hidden/legacy fallback while the
  package is being built and tested.
- Internal Sendspin should not be the default or recommended path.
- Internal Sendspin should only be removed after the packaged service has passed
  the Ubuntu VM lifecycle tests and Raspberry Pi `arm64` install tests.
- Until removal, keep the internal path isolated so new service work does not
  add more plugin-side `aiosendspin` behavior.

Keep:

- `Sendspin service URL`
- `Sendspin timeout`
- clear failure message when service is unreachable

The plugin stays responsible for:

- listening to RotorHazard events/filters
- generating/caching Piper WAV files
- queueing callouts
- dispatching playback jobs to configured output targets

The service stays responsible for:

- owning Sendspin server lifecycle
- player connections
- playback stop/resume behavior
- service health/version

---

## Code Ownership Target

Current state has Sendspin server logic in plugin code and service glue in `sendspin_service/`.

Target state:

```text
custom_plugins/local_voice/
  plugin.py
  output.py                 # HTTP client only
  piper.py
  ...

sendspin_service/
  server.py                 # HTTP ingest API
  sendspin.py               # Sendspin server adapter
  audio_queue.py
  __main__.py
  Dockerfile

packaging/
  deb/
    control
    postinst
    prerm
    postrm
    rh-sendspin-service.service
    rh-sendspin-service.default
```

All Sendspin server/process code should live under `sendspin_service/`.

The plugin should not import `aiosendspin` directly after the migration. It should only send HTTP requests to the service.

---

## Open PR / Migration Strategy

There are open PRs that still modify `custom_plugins/local_voice/sendspin.py`.

Recommended order:

1. Pause new feature work touching `sendspin.py`.
2. Merge or rebase important PR changes into the current branch.
3. Move the final Sendspin server adapter into `sendspin_service/sendspin.py`.
4. Remove plugin imports of `SendSpinServer`.
5. Delete `custom_plugins/local_voice/sendspin.py` or leave a temporary shim only if needed for compatibility.
6. Update open PRs to target `sendspin_service/sendspin.py` instead.

Avoid keeping two active copies. A temporary shim is acceptable during migration, but only one file should own the implementation.

---

## Build And Deployment Workflows

Add separate CI workflows for service packaging.

Suggested workflows:

```text
.github/workflows/sendspin-service-test.yml
.github/workflows/sendspin-service-package.yml
.github/workflows/sendspin-service-docker.yml
```

Test workflow:

- lint service code
- compile/import checks
- API unit tests
- package metadata checks

Package workflow:

- build `amd64` `.deb`
- build `arm64` `.deb`
- smoke test install in Ubuntu container/VM where possible
- upload artifacts on GitHub Release

Docker workflow:

- build image for `linux/amd64`
- build image for `linux/arm64`
- push to GHCR

Artifacts:

```text
rh-sendspin-service_0.1.0_amd64.deb
rh-sendspin-service_0.1.0_arm64.deb
ghcr.io/<owner>/rh-sendspin-service:0.1.0
```

---

## Local Testing On Ubuntu VM

The Ubuntu VM can test the full `.deb` lifecycle for `amd64`.

```shell
sudo apt install ./rh-sendspin-service_0.1.0_amd64.deb
systemctl status rh-sendspin-service
curl http://127.0.0.1:8766/health
sudo apt install ./rh-sendspin-service_0.2.0_amd64.deb
sudo apt remove rh-sendspin-service
sudo apt purge rh-sendspin-service
```

Test cases:

- install succeeds without `uv`
- service starts after install
- `/health` works
- config file is used
- config survives upgrade
- remove stops service but leaves config
- purge removes config/state as expected
- port conflicts produce clear logs

Pi-specific `arm64` testing is still required before release.

---

## Docker / Cloud Path

Keep Docker as the primary cloud deployment format.

```shell
docker run \
  -p 8766:8766 \
  -p 8927:8927 \
  ghcr.io/<owner>/rh-sendspin-service:0.1.0
```

Cloud adds:

- HTTPS termination
- token auth
- event/session identity
- QR landing page/player join flow
- possibly persistence/cleanup for event sessions

Do not let cloud requirements complicate the local `.deb` package. Keep the API shared, but deployment concerns separate.

---

## Phased Plan

### Phase 0 — Freeze and PR alignment

Goal: stop adding more moving parts while Sendspin ownership is being moved.

Checklist:

- [ ] Identify open PRs that modify `custom_plugins/local_voice/sendspin.py`.
- [ ] Decide which PR changes are still wanted.
- [ ] Merge, cherry-pick, or rebase those Sendspin changes before moving files.
- [ ] Pause new plugin-side Sendspin server changes until Phase 2 is complete.
- [ ] Add a note to active PRs that future Sendspin server work targets `sendspin_service/sendspin.py`.

Acceptance:

- [ ] There is one agreed branch that contains the final current Sendspin behavior.
- [ ] No unreviewed PR still needs to be applied to the old plugin `sendspin.py`.

Docs:

- [ ] Add a short migration note to this PVA if any PR needs manual follow-up.

---

### Phase 1 — Product decision cleanup

Goal: make the local service the preferred local playback path while keeping
the internal implementation available as a temporary legacy fallback.

Plugin checklist:

- [ ] Remove **Sendspin local mode** from the UI.
- [ ] Remove **Internal server** and **Disabled** local mode values.
- [ ] If internal fallback is still needed, hide it behind an explicit legacy/dev flag instead of normal UI.
- [ ] Rename **External Sendspin URL** to **Sendspin service URL**.
- [ ] Rename **External Sendspin timeout** to **Sendspin service timeout**.
- [ ] Default service URL to `http://127.0.0.1:8766`.
- [ ] Keep plugin audio enable/disable as the top-level plugin control.
- [ ] Replace internal mode startup behavior with service-only HTTP dispatch.
- [ ] Make missing service errors short and actionable.

Code cleanup checklist:

- [ ] Keep `InternalSendspinOutput` only as a temporary hidden/legacy fallback.
- [ ] Avoid starting internal Sendspin during RotorHazard startup.
- [ ] Avoid live switching between internal/external modes in normal user flows.
- [ ] Keep only the HTTP output client for local service playback.
- [ ] Keep a simple disabled/no-op path only if needed when plugin audio is disabled.

Acceptance:

- [ ] Starting RotorHazard never binds port `8927`.
- [ ] Starting RotorHazard does not require the Sendspin service to already be running.
- [ ] Pressing **Play audio check** POSTs to the configured service URL.
- [ ] If the service is stopped, the plugin logs a clear "service not reachable" message.
- [ ] If the service is running, browser playback still works.

Docs:

- [ ] Update `docs/usage.md` to describe service-only local playback.
- [ ] Update `Local Voice Assistant Plugin PVA.md` to mark internal server as legacy/superseded.
- [ ] Update screenshots or setting names if screenshots are added later.

Internal removal gate:

- [ ] `amd64` `.deb` install/upgrade/remove/purge lifecycle has passed.
- [ ] `arm64` `.deb` install and race-flow test has passed on Raspberry Pi.
- [ ] Service failure messages are clear enough for normal users.
- [ ] Open PRs touching the old plugin `sendspin.py` have been resolved.
- [ ] Only after these are true, remove plugin-managed internal Sendspin code.

---

### Phase 2 — Service ownership cleanup

Goal: move all Sendspin server/process code into `sendspin_service/` and keep plugin code as HTTP client only.

Current migration status: the repository now contains a first standalone
`sendspin_service/` package with its own service-side `audio_queue.py`,
`sendspin.py`, and `server.py`. This is intentionally duplicated from the
plugin-side playback path for the transition. The plugin should keep its
internal Sendspin path until the service package and HTTP output path have been
tested end to end.

Service code checklist:

- [x] Add a first Sendspin adapter implementation to `sendspin_service/sendspin.py`.
- [x] Keep `sendspin_service/server.py` as the HTTP ingest API.
- [x] Keep `sendspin_service/audio_queue.py` owned by the service.
- [x] Avoid importing RotorHazard plugin modules from `sendspin_service`.
- [x] Add `version` to `/health`.
- [x] Smoke-test `/health`, `/v1/play`, and `/v1/stop` outside the sandbox.
- [ ] Add clear startup errors for port conflicts on `8766` and `8927`.
- [ ] Keep ingest body limit configurable with `SENDSPIN_MAX_BODY_MB`.

Plugin code checklist:

- [ ] Remove `custom_plugins/local_voice/sendspin.py` implementation.
- [ ] Ensure `custom_plugins/local_voice` no longer imports `aiosendspin`.
- [ ] Ensure `output.py` only contains service/cloud HTTP outputs and small orchestration code.
- [ ] Keep plugin TTS/cache code independent from service runtime dependencies.

Dependency checklist:

- [ ] Split dependency thinking into plugin dependencies and service dependencies.
- [ ] Audit whether `sendspin_service` really needs `av`, `piper-tts`, `numpy`, or `pillow`.
- [ ] Keep Piper/model dependencies out of the service package.
- [ ] Keep Sendspin service package as small as practical.

Acceptance:

- [x] `python -m sendspin_service --help` works from the repo.
- [x] `python -m sendspin_service` starts without importing RotorHazard-only modules.
- [ ] `rg "aiosendspin" custom_plugins/local_voice` returns no plugin-side server usage.
- [x] The plugin can be loaded by RotorHazard without `sendspin_service` installed as a Python package.

Docs:

- [x] Update `docs/architecture.md` to show plugin/service separation.
- [x] Update `docs/usage.md` to stop referring to the standalone service as the default while the plugin still owns internal Sendspin.
- [x] Add a small service API section with `/health`, `/v1/play`, `/v1/stop`.

---

### Phase 3 — Bundled `.deb` package MVP on `amd64`

Goal: build and test the first self-contained `.deb` package on this Ubuntu VM.

Packaging checklist:

- [ ] Choose bundling tool: PyInstaller, Nuitka, PEX with bundled runtime, or another self-contained approach.
- [ ] Add package source under `packaging/deb/`.
- [ ] Add Debian `control`.
- [ ] Add systemd unit template.
- [ ] Add `/etc/default/rh-sendspin-service` config template.
- [ ] Add maintainer scripts: `postinst`, `prerm`, `postrm` as needed.
- [ ] Install app under `/opt/rh-sendspin-service`.
- [ ] Install state/work directory under `/var/lib/rh-sendspin-service` or use `StateDirectory`.
- [ ] Make package install without `uv`, `pip`, or RotorHazard venv.

Runtime checklist:

- [ ] Produce `/opt/rh-sendspin-service/bin/rh-sendspin-service`.
- [ ] Ensure executable includes or owns the required Python runtime.
- [ ] Ensure service starts through systemd.
- [ ] Ensure `/health` returns `ok`, `version`, `sendspin_port`, and `connected_players`.

Size checklist:

- [ ] Record `.deb` size.
- [ ] Record installed size.
- [ ] Strip or remove unnecessary caches, metadata, tests, and `__pycache__`.
- [ ] Confirm Piper models and plugin-only dependencies are not included.
- [ ] Document any large dependency that cannot be removed.

Ubuntu VM lifecycle checklist:

- [ ] `sudo apt install ./rh-sendspin-service_0.1.0_amd64.deb`
- [ ] `systemctl status rh-sendspin-service`
- [ ] `curl http://127.0.0.1:8766/health`
- [ ] `sudo apt install ./rh-sendspin-service_0.1.1_amd64.deb`
- [ ] Confirm `/etc/default/rh-sendspin-service` survives upgrade.
- [ ] `sudo apt remove rh-sendspin-service`
- [ ] Confirm service stops and config remains.
- [ ] `sudo apt purge rh-sendspin-service`
- [ ] Confirm config/state cleanup behavior is correct.

Acceptance:

- [ ] A user can install and start the service with only `sudo apt install ./...deb`.
- [ ] No user-facing install step mentions `uv`, `pip`, or Python version.
- [ ] The plugin can play audio through the installed service on the Ubuntu VM.
- [ ] Package size is recorded and judged acceptable for `amd64`.

Docs:

- [ ] Add `docs/sendspin-service-package.md` or equivalent install guide.
- [ ] Document install, upgrade, status, logs, remove, and purge commands.
- [ ] Document config file location and defaults.

---

### Phase 4 — Raspberry Pi `arm64` package

Goal: produce the Raspberry Pi package and validate it on 64-bit Raspberry Pi OS.

Build checklist:

- [ ] Add `arm64` build path in CI or documented local build.
- [ ] Build `rh-sendspin-service_0.1.0_arm64.deb`.
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

Failure checklist:

- [ ] Stop service and confirm plugin shows/logs clear unreachable-service message.
- [ ] Occupy port `8927` and confirm service logs clear port conflict.
- [ ] Occupy port `8766` and confirm service logs clear port conflict.
- [ ] Reboot Pi and confirm service starts automatically.

Acceptance:

- [ ] `arm64` package is usable by a normal Pi user with one `apt install` command.
- [ ] Package size is recorded and judged acceptable for Pi installs.
- [ ] Service remains independent from RotorHazard restarts.

Docs:

- [ ] Add Pi-specific install section.
- [ ] Add troubleshooting section for service status, logs, and port conflicts.
- [ ] Add architecture selection guidance: `amd64` vs `arm64`.

---

### Phase 5 — Release automation

Goal: make service package builds repeatable and publishable.

Workflow checklist:

- [ ] Add `.github/workflows/sendspin-service-test.yml`.
- [ ] Add `.github/workflows/sendspin-service-package.yml`.
- [ ] Add `.github/workflows/sendspin-service-docker.yml`.
- [ ] Build `amd64` `.deb` in CI.
- [ ] Build `arm64` `.deb` in CI.
- [ ] Run smoke test install where practical.
- [ ] Upload `.deb` artifacts to GitHub Release.
- [ ] Publish checksums.
- [ ] Tag Docker images with release version and `latest`.

Versioning checklist:

- [ ] Define one service version source.
- [ ] Include version in binary/package name.
- [ ] Include version in `/health`.
- [ ] Include version in Docker image labels.
- [ ] Add changelog/release note template.

Acceptance:

- [ ] A tagged release produces both `.deb` packages.
- [ ] Release artifacts are named consistently.
- [ ] A user can download the correct package from GitHub Releases.

Docs:

- [ ] Add release process documentation for maintainers.
- [ ] Add update instructions for users.
- [ ] Add checksum verification instructions if desired.

---

### Phase 6 — Cloud target and QR flow

Goal: add cloud output as a parallel target without weakening local PA reliability.

Plugin checklist:

- [ ] Add optional cloud output enable setting.
- [ ] Add cloud URL/token/event config.
- [ ] Send local and cloud outputs independently.
- [ ] Keep local timeout short and priority high.
- [ ] Ensure cloud failure never blocks local playback.
- [ ] Fan out stop commands to enabled targets.

Cloud service checklist:

- [ ] Keep shared `/health`, `/v1/play`, `/v1/stop` semantics.
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

- [ ] Local PA playback remains functional if cloud is down.
- [ ] Phone listener can join with QR code and hear callouts.
- [ ] Cloud failures are visible but non-fatal.

Docs:

- [ ] Add cloud setup guide.
- [ ] Add QR join/operator guide.
- [ ] Add security/token guidance.

---

## Open Questions

- Which bundling tool gives the best balance between self-contained runtime, package size, and maintainability?
- Do we want the package name to be `rh-sendspin-service`, `sendspin-service`, or `local-voice-sendspin-service`?
- Should install auto-start the service, or only enable it and leave start to the user?
- How strict should token auth be for localhost-only service installs?
- Which open PRs must be merged before moving Sendspin implementation out of the plugin package?
