"""Race clock warning phrase planning for Local Voice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence


DEFAULT_THRESHOLDS = (60, 30, 10)
PRECACHE_DIR_NAME = "clock"
PRECACHE_SUBDIR = f"precache/{PRECACHE_DIR_NAME}"


@dataclass(frozen=True)
class ClockWarningPhrase:
    """One pre-cacheable race clock warning phrase."""

    text: str
    subdir: str = PRECACHE_SUBDIR


class ClockWarningCallouts:
    """Build race clock warning phrases for live playback and pre-cache."""

    def __init__(
        self,
        *,
        locale_for_model: Callable[[str], dict],
        thresholds: Sequence[int] = DEFAULT_THRESHOLDS,
    ) -> None:
        """Initialize phrase generation helpers."""
        self._locale_for_model = locale_for_model
        self._thresholds = thresholds

    @property
    def subdir(self) -> str:
        """Return the cache subdirectory for race clock warning phrases."""
        return PRECACHE_SUBDIR

    @property
    def precache_dir_name(self) -> str:
        """Return the race clock warning directory under the model pre-cache root."""
        return PRECACHE_DIR_NAME

    def phrase(self, seconds: int | str, model_name: str) -> str:
        """Return the localized phrase for a race clock warning threshold."""
        locale = self._locale_for_model(model_name)
        return locale.get("clock_warning", {}).get(str(seconds), f"{seconds} seconds")

    def precache_phrases(self, model_name: str) -> Iterator[ClockWarningPhrase]:
        """Yield all race clock warning phrases for manual pre-cache rebuilds."""
        for seconds in self._thresholds:
            yield ClockWarningPhrase(self.phrase(seconds, model_name))
