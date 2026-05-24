# Debian Packaging Skeleton

This directory defines the planned Debian package shape for the Sendspin service.

The package is expected to install a self-contained service executable at:

```text
/opt/sendspin-service/bin/sendspin-service
```

The first executable build path uses PyInstaller and `dpkg-deb`:

```shell
uv run --with pyinstaller python -m tools.build_sendspin_service_deb
```

The script writes build intermediates under `build/sendspin-service/` and the resulting package under `dist/`.

This PyInstaller path is an experimental packaging validation path, not the final production packaging decision. Before release, compare it with Nuitka and a bundled CPython/app-runtime layout.

Target package behavior:

- install package name `sendspin-service`
- install default config at `/etc/default/sendspin-service`
- install systemd unit at `/lib/systemd/system/sendspin-service.service`
- start and enable the service after install
- preserve `/etc/default/sendspin-service` during upgrades
- stop the service on remove
- remove config and state on purge, including the DynamicUser private state path
