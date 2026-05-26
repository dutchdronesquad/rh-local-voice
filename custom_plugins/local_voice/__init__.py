"""Race voice callouts for RotorHazard."""

from __future__ import annotations

from typing import Any

from .plugin import RaceVoicePlugin


def initialize(rhapi: Any) -> RaceVoicePlugin:
    """RotorHazard plugin entry point."""
    return RaceVoicePlugin(rhapi)
