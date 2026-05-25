# Debian Package Files

This directory contains Debian-specific package assets for `sendspin-service`.

Package metadata and file mapping live in `packaging/nfpm.yaml`. The build script stages a bundled CPython runtime, service dependencies, service code, and launcher under `build/sendspin-service/`, then calls `nfpm`.

Build:

```shell
uv run python -m tools.build_sendspin_service_deb
```

Target install layout:

```text
/opt/sendspin-service/runtime/
/opt/sendspin-service/app/
/opt/sendspin-service/bin/sendspin-service
/etc/default/sendspin-service
/lib/systemd/system/sendspin-service.service
```

Expected package behavior:

- install package name `sendspin-service`
- enable and restart `sendspin-service` after install/upgrade
- preserve `/etc/default/sendspin-service` on upgrade
- stop and disable the service on remove
- remove config and systemd state on purge
