"""RotorHazard integration for the Local Voice plugin."""

from __future__ import annotations

import logging
import math
import struct
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from eventmanager import Evt
from filtermanager import Flt

from .audio_queue import AudioQueue, Priority
from .const import (
    DEFAULT_MODEL,
    DEFAULT_SPEED,
    DEFAULT_TEST_PHRASE,
    ENABLE_CROSSING_BEEPS_OPTION,
    ENABLE_OPTION,
    SPEECH_SPEED_OPTION,
    TEST_PHRASE_OPTION,
    VOICE_MODEL_OPTION,
    VOICE_MODELS,
)
from .piper import PiperSynthesizer, SynthesisResult
from .ui import register_ui

logger = logging.getLogger(__name__)


class LocalVoicePlugin:
    """RotorHazard plugin for local Piper TTS generation and WAV caching."""

    def __init__(self, rhapi: Any) -> None:
        """Initialize the plugin and register RotorHazard integration points."""
        self._rhapi = rhapi
        data_dir = Path(
            getattr(self._rhapi.server, "data_dir", Path.home() / "rh-data")
        )
        cache_root = data_dir / "local_voice_cache"
        self._tts = PiperSynthesizer(
            model_dir=cache_root / "models",
            tts_dir=cache_root / "tts",
            set_status=self._set_status,
        )
        self._audio_queue = AudioQueue()
        self._beep_wav = self._generate_beep(cache_root / "tts" / "beep.wav")
        self._synth_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="local_voice_synth"
        )

        register_ui(
            self._rhapi,
            test_callback=self.generate_test_phrase,
            clear_cache_callback=self.clear_tts_cache,
        )
        self._register_events()
        self._register_filters()
        logger.info("Local Voice plugin initialized")

    # ------------------------------------------------------------------
    # Event + filter registration
    # ------------------------------------------------------------------

    def _register_events(self) -> None:
        self._rhapi.events.on(
            Evt.CROSSING_ENTER, self._on_crossing, name="local_voice_crossing_enter"
        )
        self._rhapi.events.on(
            Evt.CROSSING_EXIT, self._on_crossing, name="local_voice_crossing_exit"
        )
        self._rhapi.events.on(
            Evt.HEAT_SET, self._on_heat_set, name="local_voice_heat_set"
        )

    def _register_filters(self) -> None:
        self._rhapi.filters.add(
            Flt.EMIT_PHONETIC_DATA,
            "local_voice_phonetic_data",
            self._on_phonetic_data,
        )
        self._rhapi.filters.add(
            Flt.EMIT_PHONETIC_TEXT,
            "local_voice_phonetic_text",
            self._on_phonetic_text,
        )

    # ------------------------------------------------------------------
    # Filter hooks
    # ------------------------------------------------------------------

    def _on_phonetic_data(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Snapshot lap data and schedule synthesis off the RH event thread."""
        if not self._enabled():
            return payload
        lap_number: int = payload.get("lap", 0)
        if lap_number == 0:
            return payload  # holeshot - not announced
        snapshot = {
            "lap": lap_number,
            "pilot": payload.get("pilot"),
            "callsign": payload.get("callsign"),
            "phonetic": payload.get("phonetic"),
            "expires_at": time.monotonic() + 5.0,
        }
        self._synth_pool.submit(self._synthesize_lap, snapshot)
        return payload

    def _synthesize_lap(self, snapshot: dict[str, Any]) -> None:
        """Synthesize lap callout in background using split synthesis.

        Part 1 (pilot + lap number) is cacheable and reused across heats.
        Part 2 (lap time) is always unique and synthesized live.
        """
        expires_at: float = snapshot["expires_at"]
        if time.monotonic() > expires_at:
            logger.info("Local Voice dropped expired lap synthesis job")
            return

        lap_number = snapshot["lap"]
        pilot_name = snapshot.get("pilot") or snapshot.get("callsign")
        phonetic_time = snapshot.get("phonetic")

        part1 = ", ".join(
            filter(
                None,
                [
                    str(pilot_name) if pilot_name else None,
                    f"Lap {lap_number}",
                ],
            )
        )

        wav_paths: list[Path] = []
        path = self.synthesize_to_cache(part1)
        if path:
            wav_paths.append(path)
        if phonetic_time:
            path = self.synthesize_ephemeral(str(phonetic_time))
            if path:
                wav_paths.append(path)

        if wav_paths:
            label = part1 + (f", {phonetic_time}" if phonetic_time else "")
            self._audio_queue.enqueue(
                text=label,
                wav_paths=wav_paths,
                priority=Priority.NORMAL,
                expiry_sec=max(0.0, expires_at - time.monotonic()),
            )

    def _on_phonetic_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Snapshot phonetic text and schedule synthesis off the RH event thread."""
        if not self._enabled():
            return payload
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            return payload
        priority = Priority.HIGH if payload.get("winner_flag") else Priority.NORMAL
        expires_at = time.monotonic() + 5.0
        self._synth_pool.submit(self._enqueue, text.strip(), priority, expires_at)
        return payload

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_heat_set(self, _args: dict[str, Any]) -> None:
        """Wipe ephemeral lap-time WAVs when a new heat is selected."""
        tmp_dir = self._tts.tmp_dir_for_model(self._model_name())
        if not tmp_dir.exists():
            return
        count = 0
        for wav_file in tmp_dir.glob("*.wav"):
            wav_file.unlink(missing_ok=True)
            count += 1
        if count:
            logger.info("Local Voice cleared %d ephemeral WAV files", count)

    def _on_crossing(self, _args: dict[str, Any]) -> None:
        if not self._enabled() or not self._flag(
            ENABLE_CROSSING_BEEPS_OPTION, default=False
        ):
            return
        if self._beep_wav is not None:
            self._audio_queue.enqueue(
                text="beep", wav_paths=[self._beep_wav], priority=Priority.LOW
            )

    # ------------------------------------------------------------------
    # UI button handlers
    # ------------------------------------------------------------------

    def generate_test_phrase(self, _args: dict[str, Any] | None = None) -> None:
        """Generate the configured test phrase and report the result."""
        text = str(
            self._option(TEST_PHRASE_OPTION, default=DEFAULT_TEST_PHRASE)
        ).strip()
        if not text:
            text = DEFAULT_TEST_PHRASE
        wav_path = self.synthesize_to_cache(text)
        if wav_path is None:
            self._rhapi.ui.message_alert("Local Voice test failed - check logs")
            return
        self._rhapi.ui.message_notify(f"Local Voice test WAV ready: {wav_path.name}")

    def clear_tts_cache(self, _args: dict[str, Any] | None = None) -> None:
        """Delete all cached WAV files for the currently selected model."""
        model_name = self._model_name()
        model_tts_dir = self._tts.tts_dir_for_model(model_name)
        if not model_tts_dir.exists():
            self._rhapi.ui.message_notify("Local Voice: cache is already empty")
            return
        count = sum(1 for f in model_tts_dir.glob("*.wav") if f.is_file())
        for wav_file in model_tts_dir.glob("*.wav"):
            wav_file.unlink(missing_ok=True)
        self._rhapi.ui.message_notify(
            f"Local Voice: cleared {count} WAV files for {model_name}"
        )

    # ------------------------------------------------------------------
    # Synthesis helpers
    # ------------------------------------------------------------------

    def synthesize_to_cache(self, text: str) -> Path | None:
        """Return a cached WAV path for text, synthesizing with Piper if needed."""
        result = self._tts.synthesize_to_cache(
            text=text,
            model_name=self._model_name(),
            speed=self._speed_value(),
        )
        if result is None:
            return None
        self._record_generation(result)
        return result.wav_path

    def synthesize_ephemeral(self, text: str) -> Path | None:
        """Synthesize to the tmp dir — cleared on heat change."""
        result = self._tts.synthesize_to_cache(
            text=text,
            model_name=self._model_name(),
            speed=self._speed_value(),
            ephemeral=True,
        )
        if result is None:
            return None
        self._record_generation(result)
        return result.wav_path

    def _enqueue(
        self, text: str, priority: Priority, expires_at: float | None = None
    ) -> None:
        """Synthesize text and push it onto the audio queue."""
        if expires_at is not None and time.monotonic() > expires_at:
            logger.info("Local Voice dropped expired enqueue job: '%s'", text)
            return
        wav_path = self.synthesize_to_cache(text)
        if wav_path is None:
            return
        expiry_sec = (
            max(0.0, expires_at - time.monotonic()) if expires_at is not None else 5.0
        )
        self._audio_queue.enqueue(
            text=text, wav_paths=[wav_path], priority=priority, expiry_sec=expiry_sec
        )

    def _record_generation(self, result: SynthesisResult) -> None:
        source = "cache hit" if result.cache_hit else "synthesized"
        size = result.wav_path.stat().st_size if result.wav_path.exists() else 0
        dur = result.duration_ms
        self._set_status(
            f"Ready ({source}): {result.wav_path.name} | {size}B | {dur}ms"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_beep(
        path: Path,
        freq: int = 880,
        duration_ms: int = 120,
        sample_rate: int = 22050,
    ) -> Path | None:
        """Write a short sine-tone WAV to path and return it, or None on error."""
        try:
            if path.exists():
                return path
            num_samples = int(sample_rate * duration_ms / 1000)
            fade_samples = int(sample_rate * 0.01)  # 10 ms fade in/out
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                for i in range(num_samples):
                    fade = min(i, num_samples - i, fade_samples) / fade_samples
                    angle = 2 * math.pi * freq * i / sample_rate
                    sample = int(32767 * fade * math.sin(angle))
                    wav_file.writeframes(struct.pack("<h", sample))
        except Exception:
            logger.exception("Local Voice could not generate beep WAV")
            return None
        else:
            return path

    def _set_status(self, status: str) -> None:
        logger.info("Local Voice status: %s", status)

    def _enabled(self) -> bool:
        return bool(self._option(ENABLE_OPTION, default=False))

    def _flag(self, option: str, *, default: bool = True) -> bool:
        value = self._option(option, default=default)
        if isinstance(value, bool):
            return value
        return str(value).lower() not in {"0", "false", "no", ""}

    def _model_name(self) -> str:
        value = str(self._option(VOICE_MODEL_OPTION, default=DEFAULT_MODEL))
        return value if value in VOICE_MODELS else DEFAULT_MODEL

    def _speed_value(self) -> str:
        value = self._option(SPEECH_SPEED_OPTION, default=DEFAULT_SPEED)
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return f"{float(DEFAULT_SPEED):.2f}"

    def _option(self, name: str, *, default: Any) -> Any:
        value = self._rhapi.db.option(name)
        return default if value is None else value
