"""RotorHazard integration for the Local Voice plugin."""

from __future__ import annotations

import contextlib
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from eventmanager import Evt
from filtermanager import Flt

from .audio_queue import AudioQueue, Priority
from .const import (
    DEFAULT_MODEL,
    DEFAULT_NOISE_SCALE,
    DEFAULT_NOISE_W_SCALE,
    DEFAULT_SPEED,
    DEFAULT_TEST_PHRASE,
    ENABLE_OPTION,
    NOISE_SCALE_OPTION,
    NOISE_W_SCALE_OPTION,
    SENDSPIN_PORT,
    SPEECH_SPEED_OPTION,
    TEST_PHRASE_OPTION,
    VOICE_MODEL_OPTION,
    VOICE_MODELS,
)
from .piper import PiperSynthesizer, SynthesisParams, SynthesisResult
from .sendspin import SendSpinServer
from .ui import register_ui

logger = logging.getLogger(__name__)

_ASSET_DIR = Path(__file__).parent / "assets"
_AUDIO_CHECK_WAV = _ASSET_DIR / "moavii-foreign.wav"

# Status messages that are surfaced to the UI as notifications.
_UI_NOTIFY_PREFIXES = ("Downloading model", "Loading model", "Model loaded")

# Maximum lap number to pre-cache per pilot when a heat loads.
_PRECACHE_MAX_LAPS = 15


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
        self._sendspin = SendSpinServer(port=SENDSPIN_PORT)
        self._sendspin.start()
        self._audio_queue = AudioQueue(player=self._sendspin.play)
        self._synth_pool = ThreadPoolExecutor(
            max_workers=os.cpu_count() or 4,
            thread_name_prefix="local_voice_synth",
        )

        register_ui(
            self._rhapi,
            test_callback=self.generate_test_phrase,
            audio_check_callback=self.play_audio_check,
            stop_audio_callback=self.stop_audio,
            clear_cache_callback=self.clear_tts_cache,
        )
        self._register_events()
        self._register_filters()
        self._synth_pool.submit(self._warmup_model)
        logger.info("Local Voice plugin initialized")

    # ------------------------------------------------------------------
    # Event + filter registration
    # ------------------------------------------------------------------

    def _register_events(self) -> None:
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
            "expires_at": time.monotonic() + 30.0,
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
        part1 = f"{pilot_name}, Lap {lap_number}" if pilot_name else f"Lap {lap_number}"

        wav_paths: list[Path] = []
        if path := self._synthesize(part1):
            wav_paths.append(path)
        if phonetic_time and (path := self._synthesize(str(phonetic_time), "tmp")):
            wav_paths.append(path)

        if wav_paths:
            label = f"{part1}, {phonetic_time}" if phonetic_time else part1
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
        self._synth_pool.submit(
            self._enqueue, text.strip(), priority, time.monotonic() + 5.0
        )
        return payload

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_heat_set(self, args: dict[str, Any]) -> None:
        """Wipe ephemeral lap-time WAVs and queued audio when a new heat is selected."""
        dropped = self._audio_queue.clear()
        if dropped:
            logger.info("Local Voice cleared %d queued audio jobs on heat set", dropped)
        tmp_dir = self._tts.tmp_dir_for_model(self._model_name())
        if tmp_dir.exists():
            count = sum(
                1
                for wav_file in tmp_dir.glob("*.wav")
                if wav_file.unlink(missing_ok=True) is None
            )
            if count:
                logger.info("Local Voice cleared %d ephemeral WAV files", count)
        heat_id = args.get("heat_id")
        if heat_id and self._enabled():
            self._synth_pool.submit(self._precache_heat, heat_id)

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
        wav_path = self._synthesize(text, "test")
        if wav_path is None:
            self._rhapi.ui.message_alert("Local Voice test failed - check logs")
            return
        self._audio_queue.enqueue(
            text=text, wav_paths=[wav_path], priority=Priority.HIGH
        )
        self._rhapi.ui.message_notify(
            f"Local Voice test phrase queued: {wav_path.name}"
        )

    def play_audio_check(self, _args: dict[str, Any] | None = None) -> None:
        """Play the bundled audio-check WAV through Sendspin."""
        if not _AUDIO_CHECK_WAV.exists():
            self._rhapi.ui.message_alert("Local Voice audio check WAV is missing")
            return
        self._audio_queue.enqueue(
            text="Sendspin audio check",
            wav_paths=[_AUDIO_CHECK_WAV],
            priority=Priority.HIGH,
            expiry_sec=45.0,
        )
        self._rhapi.ui.message_notify(
            f"Local Voice audio check queued: {_AUDIO_CHECK_WAV.name}"
        )

    def stop_audio(self, _args: dict[str, Any] | None = None) -> None:
        """Stop current Sendspin playback and clear queued audio."""
        dropped = self._audio_queue.clear()
        self._sendspin.stop()
        self._rhapi.ui.message_notify(f"Local Voice audio stopped ({dropped} queued)")

    def clear_tts_cache(self, _args: dict[str, Any] | None = None) -> None:
        """Delete all cached WAV files for the currently selected model."""
        model_name = self._model_name()
        model_tts_dir = self._tts.tts_dir_for_model(model_name)
        if not model_tts_dir.exists():
            self._rhapi.ui.message_notify("Local Voice: cache is already empty")
            return
        wav_files = [path for path in model_tts_dir.rglob("*.wav") if path.is_file()]
        for wav_file in wav_files:
            wav_file.unlink(missing_ok=True)
        self._rhapi.ui.message_notify(
            f"Local Voice: cleared {len(wav_files)} WAV files for {model_name}"
        )

    # ------------------------------------------------------------------
    # Synthesis helpers
    # ------------------------------------------------------------------

    def _synthesize(self, text: str, subdir: str = "") -> Path | None:
        """Synthesize text with the current model and params, return WAV path."""
        result = self._tts.synthesize_to_cache(
            text=text,
            model_name=self._model_name(),
            params=self._synth_params(),
            subdir=subdir,
        )
        if result is None:
            return None
        self._record_generation(result)
        return result.wav_path

    def _enqueue(self, text: str, priority: Priority, expires_at: float) -> None:
        """Synthesize text and push it onto the audio queue."""
        if time.monotonic() > expires_at:
            logger.info("Local Voice dropped expired enqueue job: '%s'", text)
            return
        if wav_path := self._synthesize(text):
            self._audio_queue.enqueue(
                text=text,
                wav_paths=[wav_path],
                priority=priority,
                expiry_sec=max(0.0, expires_at - time.monotonic()),
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

    def _warmup_model(self) -> None:
        self._tts.warmup(self._model_name(), self._synth_params())

    def _precache_heat(self, heat_id: int) -> None:
        """Pre-synthesize pilot + lap-number phrases for all pilots in the heat."""
        slots = self._rhapi.db.slots_by_heat(heat_id)
        model_name = self._model_name()
        params = self._synth_params()
        started = time.perf_counter()
        count = 0
        for slot in slots:
            if not slot.pilot_id:
                continue
            pilot = self._rhapi.db.pilot_by_id(slot.pilot_id)
            if pilot is None:
                continue
            name = pilot.phonetic or pilot.callsign
            if not name:
                continue
            for lap in range(1, _PRECACHE_MAX_LAPS + 1):
                result = self._tts.synthesize_to_cache(
                    text=f"{name}, Lap {lap}",
                    model_name=model_name,
                    params=params,
                )
                if result is not None and not result.cache_hit:
                    count += 1
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "Local Voice pre-cached %d new WAV(s) for heat %s in %dms",
            count,
            heat_id,
            elapsed_ms,
        )

    def _set_status(self, status: str) -> None:
        logger.info("Local Voice status: %s", status)
        if any(status.startswith(prefix) for prefix in _UI_NOTIFY_PREFIXES):
            with contextlib.suppress(Exception):
                self._rhapi.ui.message_notify(f"Local Voice: {status}")

    def _enabled(self) -> bool:
        return self._flag(ENABLE_OPTION, default=False)

    def _flag(self, option: str, *, default: bool = True) -> bool:
        value = self._option(option, default=default)
        if isinstance(value, bool):
            return value
        return str(value).lower() not in {"0", "false", "no", ""}

    def _model_name(self) -> str:
        value = str(self._option(VOICE_MODEL_OPTION, default=DEFAULT_MODEL))
        return value if value in VOICE_MODELS else DEFAULT_MODEL

    def _synth_params(self) -> SynthesisParams:
        return SynthesisParams(
            speed=self._float_option(SPEECH_SPEED_OPTION, DEFAULT_SPEED),
            noise=self._float_option(NOISE_SCALE_OPTION, DEFAULT_NOISE_SCALE),
            noise_w=self._float_option(NOISE_W_SCALE_OPTION, DEFAULT_NOISE_W_SCALE),
        )

    def _float_option(self, option: str, default: str) -> str:
        value = self._option(option, default=default)
        try:
            return f"{float(value):.3f}"
        except (TypeError, ValueError):
            return f"{float(default):.3f}"

    def _option(self, name: str, *, default: Any) -> Any:
        value = self._rhapi.db.option(name, default=default)
        return default if value is False else value
