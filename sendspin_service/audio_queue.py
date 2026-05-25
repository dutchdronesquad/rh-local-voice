"""Async audio job queue with priority and expiry."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Default expiry time for a job
DEFAULT_EXPIRY_SEC = 5.0


class Priority(IntEnum):
    """Job priority — lower value = higher priority."""

    HIGH = 0  # winner, interrupt messages
    NORMAL = 1  # lap callouts, pilot done
    LOW = 2  # crossing beeps


@dataclass(order=True)
class AudioJob:
    """A single audio playback job: one or more WAV files played in sequence."""

    priority: Priority
    expires_at: float
    text: str = field(compare=False)
    wav_items: list[WavItem] = field(compare=False)
    play_at: float | None = field(compare=False, default=None)
    volume: float = field(compare=False, default=1.0)


@dataclass(frozen=True)
class WavItem:
    """A WAV clip supplied either as a path or inline bytes."""

    name: str
    path: str | None = None
    data: bytes | None = None


class AudioQueue:
    """Priority queue with a single daemon worker thread.

    The worker drains jobs in priority order, dropping any that have exceeded
    their expiry time. Each ready job is handed to *player* with its deadline
    so the output backend can avoid scheduling stale audio.
    """

    def __init__(
        self, player: Callable[[list[WavItem], float, float | None, float], None]
    ) -> None:
        """Start the background worker thread."""
        self._player = player
        self._queue: queue.PriorityQueue[AudioJob] = queue.PriorityQueue()
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="sendspin-service-audio"
        )
        self._thread.start()

    def enqueue(  # noqa: PLR0913
        self,
        text: str,
        wav_items: list[WavItem],
        priority: Priority = Priority.NORMAL,
        expiry_sec: float = DEFAULT_EXPIRY_SEC,
        play_at: float | None = None,
        volume: float = 1.0,
    ) -> None:
        """Add a job to the queue. Returns immediately."""
        job = AudioJob(
            priority=priority,
            expires_at=time.monotonic() + expiry_sec,
            text=text,
            wav_items=wav_items,
            play_at=play_at,
            volume=volume,
        )
        self._queue.put(job)
        logger.debug("Sendspin service queued [%s] '%s'", priority.name, text)

    def clear(self) -> int:
        """Drop queued jobs that have not started yet."""
        count = 0
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return count
            self._queue.task_done()
            count += 1

    def _worker(self) -> None:
        """Drain the queue, drop expired jobs, play ready jobs."""
        while True:
            job = self._queue.get()
            try:
                if time.monotonic() > job.expires_at:
                    logger.info("Sendspin service dropped expired job: '%s'", job.text)
                    continue
                logger.info(
                    "Sendspin service playing [%s]: %s",
                    job.priority.name,
                    ", ".join(item.name for item in job.wav_items),
                )
                self._player(job.wav_items, job.expires_at, job.play_at, job.volume)
            except Exception:
                logger.exception("Sendspin service worker error for '%s'", job.text)
            finally:
                self._queue.task_done()
