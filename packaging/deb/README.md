# Debian Packaging Skeleton

This directory defines the planned Debian package shape for the Sendspin service.

The package is expected to install a self-contained service executable at:

```text
/opt/sendspin-service/bin/sendspin-service
```

The executable build step is intentionally not defined here yet. The packaging
work still needs a bundling decision, such as PyInstaller, Nuitka, PEX with a
bundled runtime, or another self-contained runtime approach.

Target package behavior:

- install package name `sendspin-service`
- install default config at `/etc/default/sendspin-service`
- install systemd unit at `/lib/systemd/system/sendspin-service.service`
- start and enable the service after install
- preserve `/etc/default/sendspin-service` during upgrades
- stop the service on remove
- remove config and state on purge
