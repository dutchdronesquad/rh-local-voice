"""Build a self-contained Sendspin service Debian package."""

from __future__ import annotations

import argparse
import logging
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

PACKAGE_NAME = "sendspin-service"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = PROJECT_ROOT / "build" / PACKAGE_NAME
DIST_ROOT = PROJECT_ROOT / "dist"
DEB_SOURCE = PROJECT_ROOT / "packaging" / "deb"
PYINSTALLER_ENTRY = BUILD_ROOT / "pyinstaller" / "sendspin_service_entry.py"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PackageMeta:
    """Debian package metadata used by the build script."""

    name: str
    version: str
    architecture: str


def main() -> int:
    """Run the package build."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args()
    meta = PackageMeta(
        name=PACKAGE_NAME,
        version=_package_version(),
        architecture=args.architecture or _debian_architecture(),
    )
    _check_tool("dpkg-deb")
    _check_pyinstaller()

    if args.clean:
        shutil.rmtree(BUILD_ROOT, ignore_errors=True)
    DIST_ROOT.mkdir(exist_ok=True)

    binary = _build_binary()
    deb_root = _stage_deb_root(binary, meta)
    output = DIST_ROOT / f"{meta.name}_{meta.version}_{meta.architecture}.deb"
    if output.exists():
        output.unlink()
    _run(["dpkg-deb", "--build", "--root-owner-group", str(deb_root), str(output)])
    _print_size_report(output, deb_root)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the Sendspin service executable and Debian package"
    )
    parser.add_argument(
        "--architecture",
        help="Debian architecture override, for example amd64 or arm64",
    )
    parser.add_argument(
        "--no-clean",
        action="store_false",
        dest="clean",
        help="Reuse the existing build directory",
    )
    parser.set_defaults(clean=True)
    return parser.parse_args()


def _package_version() -> str:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    return str(pyproject["project"]["version"])


def _debian_architecture() -> str:
    dpkg = shutil.which("dpkg")
    if dpkg is not None:
        result = subprocess.run(  # noqa: S603
            [dpkg, "--print-architecture"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "amd64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    message = f"Cannot map machine architecture to Debian architecture: {machine}"
    raise RuntimeError(message)


def _check_tool(command: str) -> None:
    if shutil.which(command) is None:
        message = f"Required build tool not found: {command}"
        raise RuntimeError(message)


def _check_pyinstaller() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        message = (
            "PyInstaller is not installed. Run: "
            "uv run --with pyinstaller python -m tools.build_sendspin_service_deb"
        )
        raise RuntimeError(message)


def _build_binary() -> Path:
    pyinstaller_root = BUILD_ROOT / "pyinstaller"
    dist_path = pyinstaller_root / "dist"
    binary = dist_path / PACKAGE_NAME
    _write_pyinstaller_entry(PYINSTALLER_ENTRY)
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--clean",
            "--noconfirm",
            "--name",
            PACKAGE_NAME,
            "--distpath",
            str(dist_path),
            "--workpath",
            str(pyinstaller_root / "work"),
            "--specpath",
            str(pyinstaller_root / "spec"),
            str(PYINSTALLER_ENTRY),
        ]
    )
    if not binary.exists():
        message = f"PyInstaller did not produce expected binary: {binary}"
        raise RuntimeError(message)
    return binary


def _write_pyinstaller_entry(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '''"""Generated PyInstaller entry point."""

from __future__ import annotations

from sendspin_service.server import main

if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )


def _stage_deb_root(binary: Path, meta: PackageMeta) -> Path:
    deb_root = BUILD_ROOT / "debroot"
    shutil.rmtree(deb_root, ignore_errors=True)
    _copy_executable(binary, deb_root / "opt" / PACKAGE_NAME / "bin" / PACKAGE_NAME)
    _copy_file(
        DEB_SOURCE / "sendspin-service.default",
        deb_root / "etc" / "default" / PACKAGE_NAME,
        mode=0o644,
    )
    _copy_file(
        DEB_SOURCE / "sendspin-service.service",
        deb_root / "lib" / "systemd" / "system" / f"{PACKAGE_NAME}.service",
        mode=0o644,
    )

    debian_dir = deb_root / "DEBIAN"
    debian_dir.mkdir(parents=True, exist_ok=True)
    _write_control(debian_dir / "control", meta, deb_root)
    for script_name in ("postinst", "prerm", "postrm"):
        _copy_file(DEB_SOURCE / script_name, debian_dir / script_name, mode=0o755)
    return deb_root


def _copy_executable(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    target.chmod(0o755)


def _copy_file(source: Path, target: Path, *, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    target.chmod(mode)


def _write_control(target: Path, meta: PackageMeta, deb_root: Path) -> None:
    source = (DEB_SOURCE / "control").read_text()
    installed_size_kib = _directory_size(deb_root) // 1024
    lines = []
    wrote_installed_size = False
    for line in source.splitlines():
        if line.startswith("Version:"):
            lines.append(f"Version: {meta.version}")
        elif line.startswith("Architecture:"):
            lines.append(f"Architecture: {meta.architecture}")
        elif line.startswith("Installed-Size:"):
            lines.append(f"Installed-Size: {installed_size_kib}")
            wrote_installed_size = True
        else:
            lines.append(line)
    if not wrote_installed_size:
        insert_at = _control_insert_index(lines)
        lines.insert(insert_at, f"Installed-Size: {installed_size_kib}")
    target.write_text("\n".join(lines) + "\n")
    target.chmod(0o644)


def _control_insert_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.startswith("Description:"):
            return index
    return len(lines)


def _directory_size(path: Path) -> int:
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def _print_size_report(output: Path, deb_root: Path) -> None:
    deb_size = output.stat().st_size
    installed_size = _directory_size(deb_root)
    logger.info("Built: %s", output)
    logger.info(".deb size: %s", _format_bytes(deb_size))
    logger.info("Installed size: %s", _format_bytes(installed_size))


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def _run(command: list[str]) -> None:
    logger.info("+ %s", " ".join(command))
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)  # noqa: S603


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
    except subprocess.CalledProcessError as exc:
        command = " ".join(str(part) for part in exc.cmd)
        message = f"Command failed with exit code {exc.returncode}: {command}"
        raise SystemExit(message) from None
