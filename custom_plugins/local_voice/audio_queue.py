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
    from pathlib import Path

logger = logging.getLogger(__name__)

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
    wav_paths: list[Path] = field(compare=False)


class AudioQueue:
    """Priority queue with a single daemon worker thread.

    The worker drains jobs in priority order, dropping any that have exceeded
    their expiry time. Each ready job is handed to *player* with its deadline
    so the output backend can avoid scheduling stale audio.
    """

    def __init__(self, player: Callable[[list[Path], float], None]) -> None:
        """Start the background worker thread."""
        self._player = player
        self._queue: queue.PriorityQueue[AudioJob] = queue.PriorityQueue()
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="local_voice_audio"
        )
        self._thread.start()

    def enqueue(
        self,
        text: str,
        wav_paths: list[Path],
        priority: Priority = Priority.NORMAL,
        expiry_sec: float = DEFAULT_EXPIRY_SEC,
    ) -> None:
        """Add a job to the queue. Returns immediately."""
        job = AudioJob(
            priority=priority,
            expires_at=time.monotonic() + expiry_sec,
            text=text,
            wav_paths=wav_paths,
        )
        self._queue.put(job)
        logger.debug("Local Voice queued [%s] '%s'", priority.name, text)

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
                    logger.info("Local Voice dropped expired job: '%s'", job.text)
                    continue
                logger.info(
                    "Local Voice playing [%s]: %s",
                    job.priority.name,
                    ", ".join(p.name for p in job.wav_paths),
                )
                self._player(job.wav_paths, job.expires_at)
            except Exception:
                logger.exception("Local Voice worker error for '%s'", job.text)
            finally:
                self._queue.task_done()
