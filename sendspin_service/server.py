"""Standalone HTTP service for Sendspin playback."""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .audio_queue import DEFAULT_EXPIRY_SEC, AudioQueue, Priority
from .sendspin import SendSpinServer

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

SERVICE_VERSION = "0.1.0"
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8766
DEFAULT_SENDSPIN_HOST = "0.0.0.0"  # noqa: S104
DEFAULT_SENDSPIN_PORT = 8927
MAX_REQUEST_BYTES = 1_000_000


@dataclass(frozen=True)
class ServiceConfig:
    """Runtime configuration for the Sendspin service."""

    api_host: str = DEFAULT_API_HOST
    api_port: int = DEFAULT_API_PORT
    sendspin_host: str = DEFAULT_SENDSPIN_HOST
    sendspin_port: int = DEFAULT_SENDSPIN_PORT
    advertise: bool = True


class SendspinService:
    """Own Sendspin playback and expose simple service operations."""

    def __init__(self, config: ServiceConfig) -> None:
        """Initialize the service backend."""
        self._config = config
        self._sendspin = SendSpinServer(
            host=config.sendspin_host,
            port=config.sendspin_port,
            advertise=config.advertise,
        )
        self._queue = AudioQueue(player=self._sendspin.play)

    def start(self) -> None:
        """Start the Sendspin server."""
        self._sendspin.start()

    def health(self) -> dict[str, Any]:
        """Return service health metadata."""
        return {
            "status": "ok",
            "version": SERVICE_VERSION,
            "api_host": self._config.api_host,
            "api_port": self._config.api_port,
            "sendspin_host": self._config.sendspin_host,
            "sendspin_port": self._config.sendspin_port,
            "connected_clients": self._sendspin.connected_client_count(),
        }

    def play(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Queue a playback request from a JSON payload."""
        wav_paths = _wav_paths(payload.get("wav_paths"))
        if not wav_paths:
            raise ValueError("wav_paths must contain at least one path")
        priority = _priority(payload.get("priority"))
        expiry_sec = _float_value(payload.get("expiry_sec"), DEFAULT_EXPIRY_SEC)
        play_at = _optional_float(payload.get("play_at"))
        volume = _clamped_float(payload.get("volume"), 1.0, 0.0, 1.0)
        text = str(payload.get("text") or "service audio")
        self._queue.enqueue(
            text=text,
            wav_paths=wav_paths,
            priority=priority,
            expiry_sec=expiry_sec,
            play_at=play_at,
            volume=volume,
        )
        return {"queued": True, "count": len(wav_paths)}

    def stop(self) -> dict[str, Any]:
        """Stop active playback and clear queued jobs."""
        dropped = self._queue.clear()
        self._sendspin.stop()
        return {"stopped": True, "dropped": dropped}

    def shutdown(self) -> None:
        """Stop playback and close the underlying Sendspin server."""
        self._queue.clear()
        self._sendspin.close()


class _RequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler bound to a SendspinService instance."""

    server: _ServiceHTTPServer

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self._path == "/health":
            self._write_json(HTTPStatus.OK, self.server.service.health())
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        """Handle POST requests."""
        try:
            if self._path == "/v1/play":
                payload = self._read_json()
                self._write_json(HTTPStatus.ACCEPTED, self.server.service.play(payload))
                return
            if self._path == "/v1/stop":
                self._write_json(HTTPStatus.OK, self.server.service.stop())
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (TypeError, ValueError) as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:
            logger.exception("Sendspin service request failed: %s", self._path)
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal server error"},
            )

    def log_message(self, format_: str, *args: object) -> None:
        """Route HTTP server logs through logging."""
        logger.info("%s - %s", self.address_string(), format_ % args)

    @property
    def _path(self) -> str:
        return urlparse(self.path).path

    def _read_json(self) -> dict[str, Any]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length header") from exc
        if content_length <= 0:
            return {}
        if content_length > MAX_REQUEST_BYTES:
            raise ValueError("request body too large")
        data = self.rfile.read(content_length)
        try:
            payload = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise TypeError("JSON body must be an object")
        return payload

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class _ServiceHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying a SendspinService reference."""

    daemon_threads = True

    def __init__(
        self, server_address: tuple[str, int], service: SendspinService
    ) -> None:
        super().__init__(server_address, _RequestHandler)
        self.service = service


def _wav_paths(value: object) -> list[Path]:
    if not isinstance(value, list):
        return []
    return [Path(item).expanduser() for item in value if isinstance(item, str)]


def _priority(value: object) -> Priority:
    if isinstance(value, int):
        with contextlib.suppress(ValueError):
            return Priority(value)
    if isinstance(value, str):
        with contextlib.suppress(KeyError):
            return Priority[value.upper()]
    return Priority.NORMAL


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return _float_value(value, 0.0)


def _float_value(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamped_float(
    value: object, default: float, minimum: float, maximum: float
) -> float:
    return max(minimum, min(maximum, _float_value(value, default)))


def _parse_args(argv: Sequence[str] | None = None) -> ServiceConfig:
    parser = argparse.ArgumentParser(description="Run the Sendspin playback service")
    parser.add_argument("--host", default=DEFAULT_API_HOST, help="HTTP API host")
    parser.add_argument(
        "--port", default=DEFAULT_API_PORT, type=int, help="HTTP API port"
    )
    parser.add_argument(
        "--sendspin-host",
        default=DEFAULT_SENDSPIN_HOST,
        help="Sendspin WebSocket host",
    )
    parser.add_argument(
        "--sendspin-port",
        default=DEFAULT_SENDSPIN_PORT,
        type=int,
        help="Sendspin WebSocket port",
    )
    parser.add_argument(
        "--no-advertise",
        action="store_true",
        help="Disable Sendspin address advertising",
    )
    args = parser.parse_args(argv)
    return ServiceConfig(
        api_host=args.host,
        api_port=args.port,
        sendspin_host=args.sendspin_host,
        sendspin_port=args.sendspin_port,
        advertise=not args.no_advertise,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Sendspin service until interrupted."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = _parse_args(argv)
    service = SendspinService(config)
    service.start()
    server = _ServiceHTTPServer((config.api_host, config.api_port), service)
    logger.info(
        "Sendspin service listening on http://%s:%s",
        config.api_host,
        config.api_port,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Sendspin service stopping")
    finally:
        service.shutdown()
        server.server_close()
    return 0
