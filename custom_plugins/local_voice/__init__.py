"""Local server-side voice callouts for RotorHazard."""

from __future__ import annotations

from typing import Any

from .plugin import LocalVoicePlugin


def initialize(rhapi: Any) -> LocalVoicePlugin:
    """RotorHazard plugin entry point."""
    return LocalVoicePlugin(rhapi)
