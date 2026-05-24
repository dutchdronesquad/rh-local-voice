"""Sendspin server adapter for streaming WAV audio over the local network."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
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
_MIN_SCHEDULE_DELAY_S = 0.05


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

    def clear(self) -> None:
        """Clear pending and buffered client audio."""
        ...

    def stop(self, *, keep_stream: bool = False) -> None:
        """Stop the stream transport."""
        ...


class SendSpinServer:
    """Thin synchronous adapter around ``aiosendspin``.

    RotorHazard plugin callbacks are synchronous, while aiosendspin is asyncio
    native. This class owns a background event loop and exposes blocking
    ``play()`` / ``stop()`` methods for the existing ``AudioQueue`` worker.
    Normal ``play()`` calls append to the active stream instead of stopping it,
    so queued lap callouts can be scheduled back-to-back without audible resets.
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
        self._stream_lock: asyncio.Lock | None = None
        self._stream_group: SendspinGroup | None = None
        self._stream: _PushStream | None = None
        self._next_play_start_us: int | None = None
        self._idle_stop_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the Sendspin server in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="local_voice_sendspin"
        )
        self._thread.start()

    def play(
        self,
        wav_paths: list[Path],
        expires_at: float | None = None,
        play_at: float | None = None,
    ) -> None:
        """Queue WAV files to connected clients without resetting active playback."""
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
            self._append_to_stream(wav_paths, expires_at, play_at), self._loop
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
        self._stream_lock = asyncio.Lock()
        logger.info(
            "Local Voice: Sendspin server listening on %s:%s",
            self._host,
            self._port,
        )

    async def _close_server(self) -> None:
        if self._server is not None:
            await self._stop_stream()
            await self._server.close()
            self._server = None

    async def _stop_stream(self) -> None:
        await self._interrupt_stream(clear_client_audio=True)

    async def _stop_stream_locked(self, *, stop_all_client_groups: bool) -> None:
        self._cancel_idle_stop()

        server = self._server
        group = self._stream_group
        self._stream = None
        self._stream_group = None
        self._next_play_start_us = None
        if server is None:
            return
        if stop_all_client_groups:
            stop_tasks = [client.group.stop() for client in server.connected_clients]
            if stop_tasks:
                await asyncio.gather(*stop_tasks, return_exceptions=True)
        elif group is not None:
            await group.stop()

    async def _interrupt_stream(self, *, clear_client_audio: bool) -> None:
        """Immediately interrupt active playback, even while audio is being queued."""
        self._cancel_idle_stop()

        server = self._server
        stream = self._stream
        group = self._stream_group
        self._stream = None
        self._stream_group = None
        self._next_play_start_us = None

        if clear_client_audio and stream is not None and not stream.is_stopped:
            stream.clear()
        if stream is not None and not stream.is_stopped:
            stream.stop()

        if server is None:
            return

        groups = {client.group for client in server.connected_clients}
        if group is not None:
            groups.add(group)
        if groups:
            await asyncio.gather(
                *(group.stop() for group in groups),
                return_exceptions=True,
            )

    async def _append_to_stream(
        self, wav_paths: list[Path], expires_at: float | None, play_at: float | None
    ) -> None:
        lock = self._stream_lock
        if lock is None:
            logger.warning("Local Voice: Sendspin stream lock not ready")
            return
        async with lock:
            self._cancel_idle_stop()
            await self._append_to_stream_locked(wav_paths, expires_at, play_at)

    async def _append_to_stream_locked(
        self, wav_paths: list[Path], expires_at: float | None, play_at: float | None
    ) -> None:
        server = self._server
        if server is None:
            return
        clients = server.connected_clients
        if not clients:
            logger.info("Local Voice: no Sendspin clients connected - audio dropped")
            return

        group, stream = await self._ensure_stream()
        if group is None or stream is None:
            return
        client_count = await self._sync_connected_clients(group)

        play_start_us = self._next_play_start_us
        now_us = server.clock.now_us()
        if play_at is not None:
            play_start_us = _scheduled_play_start_us(play_at, now_us)
        elif play_start_us is None or play_start_us <= now_us:
            play_start_us = now_us + int(_INITIAL_PLAYBACK_DELAY_S * 1_000_000)
        if self._would_start_after_expiry(play_start_us, now_us, expires_at):
            logger.info("Local Voice dropped stale audio before Sendspin scheduling")
            return

        async def sync_clients() -> int:
            return await self._sync_connected_clients(group)

        try:
            play_end_us, streamed_count, client_count = await self._queue_wav_paths(
                stream,
                wav_paths,
                play_start_us=play_start_us,
                initial_client_count=client_count,
                sync_clients=sync_clients,
            )
            client_count = max(client_count, await sync_clients())
            if streamed_count:
                logger.info(
                    "Local Voice: queued %d WAV(s) to %d client(s)",
                    streamed_count,
                    client_count,
                )
                self._schedule_idle_stop(server.clock, group, play_end_us)
        except StreamStoppedError:
            logger.info("Local Voice: Sendspin stream stopped")
            self._stream = None
            self._stream_group = None
            self._next_play_start_us = None

    async def _queue_wav_paths(
        self,
        stream: _PushStream,
        wav_paths: list[Path],
        *,
        play_start_us: int,
        initial_client_count: int,
        sync_clients: Callable[[], Awaitable[int]],
    ) -> tuple[int, int, int]:
        play_end_us = play_start_us
        streamed_count = 0
        client_count = initial_client_count
        next_play_start_us: int | None = play_start_us
        for wav_path in wav_paths:
            next_play_start_us, clip_end_us, client_count = await _stream_wav(
                stream,
                wav_path,
                play_start_us=next_play_start_us,
                sync_clients=sync_clients,
            )
            if clip_end_us is not None:
                play_end_us = clip_end_us
                self._next_play_start_us = clip_end_us
                streamed_count += 1
        return play_end_us, streamed_count, client_count

    async def _ensure_stream(self) -> tuple[SendspinGroup | None, _PushStream | None]:
        server = self._server
        if server is None or not server.connected_clients:
            return None, None
        if (
            self._stream_group is not None
            and self._stream is not None
            and not self._stream.is_stopped
        ):
            return self._stream_group, self._stream

        group = server.connected_clients[0].group
        await self._sync_connected_clients(group)
        stream = group.start_stream()
        self._stream_group = group
        self._stream = stream
        self._next_play_start_us = None
        return group, stream

    def _cancel_idle_stop(self) -> None:
        task = self._idle_stop_task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        if self._idle_stop_task is task:
            self._idle_stop_task = None

    def _schedule_idle_stop(
        self, clock: _SendspinClock, group: SendspinGroup, play_end_us: int
    ) -> None:
        self._cancel_idle_stop()
        self._idle_stop_task = asyncio.create_task(
            self._stop_stream_when_idle(clock, group, play_end_us)
        )

    @staticmethod
    def _would_start_after_expiry(
        play_start_us: int, now_us: int, expires_at: float | None
    ) -> bool:
        if expires_at is None:
            return False
        scheduled_delay_s = max(0.0, (play_start_us - now_us) / 1_000_000)
        return time.monotonic() + scheduled_delay_s > expires_at

    async def _stop_stream_when_idle(
        self, clock: _SendspinClock, group: SendspinGroup, play_end_us: int
    ) -> None:
        try:
            while True:
                if self._stream_group is not group:
                    return
                await self._sync_connected_clients(group)
                delay_s = (play_end_us - clock.now_us()) / 1_000_000
                if delay_s <= 0:
                    break
                await asyncio.sleep(min(delay_s, _LATE_JOIN_SYNC_INTERVAL_S))
            lock = self._stream_lock
            if lock is None:
                return
            async with lock:
                if (
                    self._stream_group is group
                    and self._next_play_start_us == play_end_us
                ):
                    await self._stop_stream_locked(stop_all_client_groups=False)
        except asyncio.CancelledError:
            pass

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


def _scheduled_play_start_us(play_at: float, now_us: int) -> int:
    """Map a process-local monotonic target time to the Sendspin clock."""
    clock_offset_us = now_us - int(time.monotonic() * 1_000_000)
    requested_start_us = int(play_at * 1_000_000) + clock_offset_us
    minimum_start_us = now_us + int(_MIN_SCHEDULE_DELAY_S * 1_000_000)
    return max(requested_start_us, minimum_start_us)


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
