"""Sendspin server adapter for streaming WAV audio over the local network."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import wave
from typing import TYPE_CHECKING, Protocol

from aiosendspin.server import AudioFormat
from aiosendspin.server import SendspinServer as AioSendspinServer
from aiosendspin.server.push_stream import MAIN_CHANNEL, StreamStoppedError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from aiosendspin.server.group import SendspinGroup

logger = logging.getLogger(__name__)

_CHUNK_DURATION_S = 0.05
_INITIAL_PLAYBACK_DELAY_S = 0.25
_TIMEOUT_MARGIN_S = 10
_BUFFER_LIMIT_US = 500_000
_LATE_JOIN_SYNC_INTERVAL_S = 0.1


class _SendspinClock(Protocol):
    def now_us(self) -> int:
        """Return the current Sendspin monotonic clock in microseconds."""
        ...


class _PushStream(Protocol):
    @property
    def is_stopped(self) -> bool:
        """Whether the stream has been stopped."""
        ...

    async def sleep_to_limit_buffer(self, max_buffer_us: int) -> None:
        """Throttle when the queued client buffer is above the requested size."""
        ...

    def prepare_audio(
        self, pcm: bytes, audio_format: AudioFormat, *, channel_id: object
    ) -> None:
        """Prepare PCM audio for the next commit."""
        ...

    async def commit_audio(self, *, play_start_us: int | None = None) -> int:
        """Commit prepared audio and return the chunk start timestamp."""
        ...


class SendSpinServer:
    """Thin synchronous adapter around ``aiosendspin``.

    RotorHazard plugin callbacks are synchronous, while aiosendspin is asyncio
    native. This class owns a background event loop and exposes blocking
    ``play()`` / ``stop()`` methods for the existing ``AudioQueue`` worker.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",  # noqa: S104
        port: int = 8927,
        *,
        advertise: bool = True,
    ) -> None:
        """Configure host and port; call ``start()`` to launch the server."""
        self._host = host
        self._port = port
        self._advertise = advertise
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: AioSendspinServer | None = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the Sendspin server in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="local_voice_sendspin"
        )
        self._thread.start()

    def play(self, wav_paths: list[Path]) -> None:
        """Stream WAV files to connected clients. Blocks until done."""
        if not self._ready.wait(timeout=5.0) or self._loop is None:
            logger.warning("Local Voice: Sendspin server not yet ready")
            return
        if self._server is None:
            logger.warning("Local Voice: Sendspin server failed to start")
            return
        if not self._server.connected_clients:
            logger.info("Local Voice: no Sendspin clients connected - audio dropped")
            return

        duration_s = _wav_total_duration(wav_paths)
        timeout = max(30.0, duration_s + _INITIAL_PLAYBACK_DELAY_S + _TIMEOUT_MARGIN_S)
        future = asyncio.run_coroutine_threadsafe(
            self._play_stream(wav_paths), self._loop
        )
        try:
            future.result(timeout=timeout)
        except TimeoutError:
            logger.warning("Local Voice: Sendspin stream timed out")
        except Exception:
            logger.exception("Local Voice: Sendspin stream error")

    def stop(self) -> None:
        """Stop current playback and clear scheduled client audio."""
        if self._loop is None or self._server is None:
            return
        future = asyncio.run_coroutine_threadsafe(self._stop_stream(), self._loop)
        try:
            future.result(timeout=5.0)
        except TimeoutError:
            logger.warning("Local Voice: Sendspin stop timed out")
        except Exception:
            logger.exception("Local Voice: Sendspin stop error")

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._start_server())
            self._ready.set()
            loop.run_forever()
        except Exception:
            logger.exception("Local Voice: Sendspin server loop failed")
            self._ready.set()
        finally:
            with contextlib.suppress(Exception):
                loop.run_until_complete(self._close_server())
            self._drain_pending_tasks(loop)
            loop.close()

    @staticmethod
    def _drain_pending_tasks(loop: asyncio.AbstractEventLoop) -> None:
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            with contextlib.suppress(Exception):
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        with contextlib.suppress(Exception):
            loop.run_until_complete(loop.shutdown_asyncgens())

    async def _start_server(self) -> None:
        server = AioSendspinServer(
            loop=asyncio.get_running_loop(),
            server_id="rh-local-voice",
            server_name="RotorHazard Local Voice",
        )
        await server.start_server(
            port=self._port,
            host=self._host,
            advertise_addresses=None if self._advertise else [],
            discover_clients=False,
        )
        self._server = server
        logger.info(
            "Local Voice: Sendspin server listening on %s:%s",
            self._host,
            self._port,
        )

    async def _close_server(self) -> None:
        if self._server is not None:
            await self._server.close()
            self._server = None

    async def _play_stream(self, wav_paths: list[Path]) -> None:
        await self._stop_stream()
        self._stream_task = asyncio.create_task(self._stream_all(wav_paths))
        try:
            await self._stream_task
        except asyncio.CancelledError:
            logger.info("Local Voice: Sendspin stream cancelled")
        finally:
            self._stream_task = None

    async def _stop_stream(self) -> None:
        task = self._stream_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._stream_task is task:
            self._stream_task = None

        server = self._server
        if server is None:
            return
        stop_tasks = [client.group.stop() for client in server.connected_clients]
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

    async def _stream_all(self, wav_paths: list[Path]) -> None:
        server = self._server
        if server is None:
            return
        clients = server.connected_clients
        if not clients:
            logger.info("Local Voice: no Sendspin clients connected - audio dropped")
            return

        group = clients[0].group
        client_count = await self._sync_connected_clients(group)

        stream = group.start_stream()
        play_start_us: int | None = server.clock.now_us() + int(
            _INITIAL_PLAYBACK_DELAY_S * 1_000_000
        )
        play_end_us = play_start_us
        streamed_count = 0

        async def sync_clients() -> int:
            return await self._sync_connected_clients(group)

        try:
            for wav_path in wav_paths:
                next_play_start_us, clip_end_us, client_count = await _stream_wav(
                    stream,
                    wav_path,
                    play_start_us=play_start_us,
                    sync_clients=sync_clients,
                )
                play_start_us = next_play_start_us
                if clip_end_us is not None:
                    play_end_us = clip_end_us
                    streamed_count += 1
            await self._finish_stream(
                server.clock,
                play_end_us,
                streamed_count,
                client_count,
                sync_clients=sync_clients,
            )
        except StreamStoppedError:
            logger.info("Local Voice: Sendspin stream stopped")
        finally:
            await group.stop()

    async def _sync_connected_clients(self, group: SendspinGroup) -> int:
        server = self._server
        if server is None:
            return 0
        for client in server.connected_clients:
            if client.group is not group:
                await group.add_client(client)
                logger.info(
                    "Local Voice: added late Sendspin client to active stream: %s",
                    client.client_id,
                )
        return sum(1 for client in group.clients if client.is_connected)

    async def _finish_stream(
        self,
        clock: _SendspinClock,
        play_end_us: int,
        streamed_count: int,
        client_count: int,
        *,
        sync_clients: Callable[[], Awaitable[int]],
    ) -> None:
        if not streamed_count:
            return
        client_count = max(client_count, await sync_clients())
        logger.info(
            "Local Voice: streamed %d WAV(s) to %d client(s)",
            streamed_count,
            client_count,
        )
        await _sleep_until(clock, play_end_us, sync_clients=sync_clients)


async def _stream_wav(
    stream: _PushStream,
    wav_path: Path,
    *,
    play_start_us: int | None,
    sync_clients: Callable[[], Awaitable[int]],
) -> tuple[int | None, int | None, int]:
    client_count = await sync_clients()
    clip = _read_wav(wav_path)
    if clip is None:
        return play_start_us, None, client_count
    audio_format, pcm_data = clip
    bytes_per_frame = audio_format.channels * (audio_format.bit_depth // 8)
    chunk_frames = max(1, int(audio_format.sample_rate * _CHUNK_DURATION_S))
    chunk_bytes = chunk_frames * bytes_per_frame
    play_end_us: int | None = None

    for offset in range(0, len(pcm_data), chunk_bytes):
        if stream.is_stopped:
            return play_start_us, play_end_us, client_count
        client_count = await sync_clients()
        await stream.sleep_to_limit_buffer(max_buffer_us=_BUFFER_LIMIT_US)
        chunk = pcm_data[offset : offset + chunk_bytes]
        stream.prepare_audio(chunk, audio_format, channel_id=MAIN_CHANNEL)
        chunk_start_us = await stream.commit_audio(play_start_us=play_start_us)
        frames_in_chunk = len(chunk) // bytes_per_frame
        chunk_duration_us = int(frames_in_chunk * 1_000_000 / audio_format.sample_rate)
        play_end_us = chunk_start_us + chunk_duration_us
        play_start_us = None
    return play_start_us, play_end_us, client_count


def _read_wav(wav_path: Path) -> tuple[AudioFormat, bytes] | None:
    """Read a WAV file as PCM bytes and return its Sendspin audio format."""
    try:
        with wave.open(str(wav_path), "rb") as wav_file:
            sample_width = wav_file.getsampwidth()
            if sample_width not in {2, 3, 4}:
                logger.warning(
                    "Local Voice: unsupported WAV sample width %s: %s",
                    sample_width,
                    wav_path.name,
                )
                return None
            audio_format = AudioFormat(
                sample_rate=wav_file.getframerate(),
                bit_depth=sample_width * 8,
                channels=wav_file.getnchannels(),
            )
            return audio_format, wav_file.readframes(wav_file.getnframes())
    except Exception:
        logger.exception("Local Voice: cannot read WAV: %s", wav_path.name)
        return None


def _wav_total_duration(wav_paths: list[Path]) -> float:
    """Return the combined duration in seconds of all WAV files."""
    total = 0.0
    for wav_path in wav_paths:
        try:
            with wave.open(str(wav_path), "rb") as wav_file:
                total += wav_file.getnframes() / wav_file.getframerate()
        except Exception:
            logger.exception("Local Voice: cannot inspect WAV: %s", wav_path.name)
    return total


async def _sleep_until(
    clock: _SendspinClock,
    timestamp_us: int,
    *,
    sync_clients: Callable[[], Awaitable[int]],
) -> None:
    """Sleep until a Sendspin clock timestamp has passed while catching late joiners."""
    while True:
        await sync_clients()
        delay_s = (timestamp_us - clock.now_us()) / 1_000_000
        if delay_s <= 0:
            return
        await asyncio.sleep(min(delay_s, _LATE_JOIN_SYNC_INTERVAL_S))
