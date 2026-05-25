"""Standalone HTTP service for Sendspin playback."""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aiohttp import web

from .audio_queue import DEFAULT_EXPIRY_SEC, AudioQueue, Priority, WavItem
from .sendspin import SendSpinServer

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

SERVICE_VERSION = os.environ.get("SENDSPIN_SERVICE_VERSION", "0.0.0+dev")
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8766
DEFAULT_SENDSPIN_HOST = "0.0.0.0"  # noqa: S104
DEFAULT_SENDSPIN_PORT = 8927
DEFAULT_MAX_BODY_MB = 50
MAX_BODY_MB_LIMIT = 100
BYTES_PER_MIB = 1024 * 1024


@dataclass(frozen=True)
class ServiceConfig:
    """Runtime configuration for the Sendspin service."""

    api_host: str = DEFAULT_API_HOST
    api_port: int = DEFAULT_API_PORT
    sendspin_host: str = DEFAULT_SENDSPIN_HOST
    sendspin_port: int = DEFAULT_SENDSPIN_PORT
    advertise: bool = True
    max_body_bytes: int = DEFAULT_MAX_BODY_MB * BYTES_PER_MIB


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
        connected_clients = self._sendspin.connected_client_count()
        return {
            "ok": True,
            "status": "ok",
            "version": SERVICE_VERSION,
            "api_host": self._config.api_host,
            "api_port": self._config.api_port,
            "sendspin_host": self._config.sendspin_host,
            "sendspin_port": self._config.sendspin_port,
            "connected_clients": connected_clients,
            "connected_players": connected_clients,
            "max_body_bytes": self._config.max_body_bytes,
        }

    @property
    def max_body_bytes(self) -> int:
        """Return the configured maximum HTTP request body size."""
        return self._config.max_body_bytes

    def play(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Queue a playback request from a JSON payload."""
        wav_items = _wav_items(payload)
        if not wav_items:
            raise ValueError("wav_files must contain at least one WAV")
        priority = _priority(payload.get("priority"))
        expiry_sec = _float_value(payload.get("expiry_sec"), DEFAULT_EXPIRY_SEC)
        play_at = _optional_float(payload.get("play_at"))
        volume = _clamped_float(payload.get("volume"), 1.0, 0.0, 1.0)
        text = str(payload.get("text") or "service audio")
        self._queue.enqueue(
            text=text,
            wav_items=wav_items,
            priority=priority,
            expiry_sec=expiry_sec,
            play_at=play_at,
            volume=volume,
        )
        return {"queued": True, "count": len(wav_items)}

    def stop(self) -> dict[str, Any]:
        """Stop active playback and clear queued jobs."""
        dropped = self._queue.clear()
        self._sendspin.stop()
        return {"stopped": True, "dropped": dropped}

    def shutdown(self) -> None:
        """Stop playback and close the underlying Sendspin server."""
        self._queue.clear()
        self._sendspin.close()


def _create_app(service: SendspinService) -> web.Application:
    """Create the HTTP ingest application."""
    app = web.Application(client_max_size=service.max_body_bytes)
    app["service"] = service
    app.router.add_get("/health", _health)
    app.router.add_post("/v1/play", _play)
    app.router.add_post("/v1/stop", _stop)
    return app


async def _health(request: web.Request) -> web.Response:
    """Return service health metadata."""
    return web.json_response(_service(request).health())


async def _play(request: web.Request) -> web.Response:
    """Queue playback from a JSON request body."""
    try:
        payload = await _read_json(request)
        return web.json_response(_service(request).play(payload), status=202)
    except web.HTTPRequestEntityTooLarge:
        return web.json_response({"error": "request body too large"}, status=413)
    except (TypeError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception:
        logger.exception("Sendspin service request failed: %s", request.path)
        return web.json_response({"error": "internal server error"}, status=500)


async def _stop(request: web.Request) -> web.Response:
    """Stop active playback and clear queued audio."""
    try:
        return web.json_response(_service(request).stop())
    except Exception:
        logger.exception("Sendspin service stop request failed")
        return web.json_response({"error": "internal server error"}, status=500)


async def _read_json(request: web.Request) -> dict[str, Any]:
    content_length = request.content_length
    if content_length == 0:
        return {}
    if content_length is not None and content_length > _service(request).max_body_bytes:
        raise ValueError("request body too large")
    try:
        payload = await request.json(loads=json.loads)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise TypeError("JSON body must be an object")
    return payload


def _service(request: web.Request) -> SendspinService:
    return request.app["service"]


def _wav_items(payload: dict[str, Any]) -> list[WavItem]:
    if "wav_paths" in payload:
        raise ValueError("wav_paths are not supported; use wav_files")
    return _inline_wav_items(payload.get("wav_files"))


def _inline_wav_items(value: object) -> list[WavItem]:
    if not isinstance(value, list):
        return []
    items: list[WavItem] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise TypeError("wav_files entries must be objects")
        name = str(item.get("name") or f"inline-{index}.wav")
        data = item.get("data")
        encoding = str(item.get("encoding") or "base64").lower()
        if not isinstance(data, str):
            raise TypeError("wav_files entries must include string data")
        if encoding != "base64":
            raise ValueError("wav_files entries only support base64 encoding")
        try:
            wav_data = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            message = "wav_files entries must contain valid base64 data"
            raise ValueError(message) from exc
        items.append(WavItem(name=name, data=wav_data))
    return items


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


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    with contextlib.suppress(ValueError):
        return int(value)
    logger.warning("Ignoring invalid integer value for %s: %r", name, value)
    return default


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _body_limit_mb(value: int) -> int:
    if value < 1:
        logger.warning("Clamping SENDSPIN_MAX_BODY_MB to 1 MiB")
        return 1
    if value > MAX_BODY_MB_LIMIT:
        logger.warning("Clamping SENDSPIN_MAX_BODY_MB to %d MiB", MAX_BODY_MB_LIMIT)
        return MAX_BODY_MB_LIMIT
    return value


def _parse_args(argv: Sequence[str] | None = None) -> ServiceConfig:
    parser = argparse.ArgumentParser(description="Run the Sendspin playback service")
    parser.add_argument(
        "--host",
        default=_env_str("SENDSPIN_INGEST_HOST", DEFAULT_API_HOST),
        help="HTTP API host",
    )
    parser.add_argument(
        "--port",
        default=_env_int("SENDSPIN_INGEST_PORT", DEFAULT_API_PORT),
        type=int,
        help="HTTP API port",
    )
    parser.add_argument(
        "--sendspin-host",
        default=_env_str("SENDSPIN_HOST", DEFAULT_SENDSPIN_HOST),
        help="Sendspin WebSocket host",
    )
    parser.add_argument(
        "--sendspin-port",
        default=_env_int("SENDSPIN_PORT", DEFAULT_SENDSPIN_PORT),
        type=int,
        help="Sendspin WebSocket port",
    )
    parser.add_argument(
        "--no-advertise",
        action="store_false",
        default=_env_bool("SENDSPIN_ADVERTISE", default=True),
        dest="advertise",
        help="Disable Sendspin address advertising",
    )
    parser.add_argument(
        "--max-body-mb",
        default=_env_int("SENDSPIN_MAX_BODY_MB", DEFAULT_MAX_BODY_MB),
        type=int,
        help="Maximum JSON request body size in MiB",
    )
    args = parser.parse_args(argv)
    max_body_mb = _body_limit_mb(args.max_body_mb)
    return ServiceConfig(
        api_host=args.host,
        api_port=args.port,
        sendspin_host=args.sendspin_host,
        sendspin_port=args.sendspin_port,
        advertise=args.advertise,
        max_body_bytes=max_body_mb * BYTES_PER_MIB,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Sendspin service until interrupted."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = _parse_args(argv)
    logger.info(
        "Sendspin service request body limit: %d MiB",
        config.max_body_bytes // BYTES_PER_MIB,
    )
    service = SendspinService(config)
    try:
        service.start()
        app = _create_app(service)
    except RuntimeError:
        logger.exception("Sendspin service startup failed")
        service.shutdown()
        return 1
    logger.info(
        "Sendspin service listening on http://%s:%s",
        config.api_host,
        config.api_port,
    )
    try:
        web.run_app(
            app,
            host=config.api_host,
            port=config.api_port,
            print=None,
            access_log=logger,
        )
    except OSError:
        logger.exception(
            "Sendspin service cannot listen on http://%s:%s",
            config.api_host,
            config.api_port,
        )
        return 1
    finally:
        service.shutdown()
    return 0
