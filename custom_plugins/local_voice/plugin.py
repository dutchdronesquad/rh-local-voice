"""RotorHazard integration for the Local Voice plugin."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
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
_PRECACHE_MAX_LAPS = 6
_PRECACHE_LAPS_SUBDIR = "precache/laps"
_LAP_CALLOUT_EXPIRY_SEC = 10.0

try:
    with (Path(__file__).parent / "locales.json").open(encoding="utf-8") as _f:
        _LOCALES: dict[str, dict] = json.load(_f)
except (OSError, json.JSONDecodeError) as exc:
    raise RuntimeError("Local Voice: failed to load locales.json") from exc


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
        self._precache_generation = 0
        self._precache_lock = threading.Lock()
        self._warmed_model: str | None = None
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
            rebuild_precache_callback=self.rebuild_precache,
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
        self._rhapi.events.on(
            Evt.DATABASE_RESET,
            self._on_event_cache_reset,
            name="local_voice_database_reset",
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
            "expires_at": time.monotonic() + _LAP_CALLOUT_EXPIRY_SEC,
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
        lap = self._locale().get("lap", "Lap")
        part1 = (
            f"{pilot_name}, {lap} {lap_number}" if pilot_name else f"{lap} {lap_number}"
        )

        wav_paths: list[Path] = []
        if path := self._synthesize(part1, _PRECACHE_LAPS_SUBDIR):
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
        with self._precache_lock:
            self._precache_generation += 1
            precache_generation = self._precache_generation

        dropped = self._audio_queue.clear()
        if dropped:
            logger.info("Local Voice cleared %d queued audio jobs on heat set", dropped)
        model_name = self._model_name()
        self._clear_wavs(self._tts.tmp_dir_for_model(model_name), "ephemeral")
        if model_name != self._warmed_model:
            self._synth_pool.submit(self._warmup_model)
        heat_id = args.get("heat_id")
        if heat_id and self._enabled():
            future = self._synth_pool.submit(
                self._precache_heat, heat_id, precache_generation
            )

            def _on_heat_precache_done(f: Any) -> None:
                try:
                    count = f.result() or 0
                except Exception:
                    logger.exception(
                        "Local Voice pre-cache failed for heat %s", heat_id
                    )
                    return
                if count > 0 and self._precache_is_current(precache_generation):
                    with contextlib.suppress(Exception):
                        heat = self._rhapi.db.heat_by_id(heat_id)
                        heat_name = heat.name if heat else heat_id
                        self._rhapi.ui.message_notify(
                            f"Local Voice: pre-cache ready for {heat_name}"
                            f" ({count} new WAV files)"
                        )

            future.add_done_callback(_on_heat_precache_done)

    def _on_event_cache_reset(self, _args: dict[str, Any]) -> None:
        """Wipe event-specific WAVs when RotorHazard starts a new data set."""
        with self._precache_lock:
            self._precache_generation += 1
        model_name = self._model_name()
        self._clear_wavs(self._tts.tmp_dir_for_model(model_name), "ephemeral")
        self._clear_wavs(self._tts.precache_dir_for_model(model_name), "pre-cache")

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
        with self._precache_lock:
            self._precache_generation += 1

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

    def rebuild_precache(self, _args: dict[str, Any] | None = None) -> None:
        """Clear and regenerate pre-cached phrases for the current model and heat."""
        with self._precache_lock:
            self._precache_generation += 1
            generation = self._precache_generation

        model_name = self._model_name()
        precache_dir = self._tts.precache_dir_for_model(model_name)
        self._clear_wavs(precache_dir / "laps", "pre-cache laps")
        self._clear_wavs(precache_dir / "clock", "pre-cache clock")

        self._rhapi.ui.message_notify("Local Voice: rebuilding pre-cache...")

        heat_id = self._rhapi.race.heat

        def _on_rebuild_done(f: Any) -> None:
            if not self._precache_is_current(generation):
                return
            try:
                count = f.result() or 0
            except Exception:
                logger.exception("Local Voice pre-cache rebuild failed")
                return
            with contextlib.suppress(Exception):
                if heat_id:
                    heat = self._rhapi.db.heat_by_id(heat_id)
                    heat_name = heat.name if heat else heat_id
                    msg = (
                        f"Local Voice: pre-cache rebuild complete for {heat_name}"
                        f" ({count} new WAV files)"
                    )
                else:
                    msg = (
                        "Local Voice: pre-cache rebuild complete "
                        f"({count} new WAV files)"
                    )
                self._rhapi.ui.message_notify(msg)

        warmup_future = self._synth_pool.submit(self._warmup_model)
        if heat_id:
            heat_future = self._synth_pool.submit(
                self._precache_heat, heat_id, generation
            )
            heat_future.add_done_callback(_on_rebuild_done)
        else:
            warmup_future.add_done_callback(_on_rebuild_done)

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
        model_name = self._model_name()
        self._tts.warmup(model_name, self._synth_params())
        self._warmed_model = model_name

    def _precache_heat(self, heat_id: int, generation: int) -> int:
        """Pre-synthesize pilot + lap-number phrases for all pilots in the heat."""
        slots = self._rhapi.db.slots_by_heat(heat_id)
        model_name = self._model_name()
        params = self._synth_params()
        lap_word = self._locale().get("lap", "Lap")
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
                if not self._precache_is_current(generation):
                    logger.info(
                        "Local Voice stopped stale pre-cache job for heat %s", heat_id
                    )
                    return count
                result = self._tts.synthesize_to_cache(
                    text=f"{name}, {lap_word} {lap}",
                    model_name=model_name,
                    params=params,
                    subdir=_PRECACHE_LAPS_SUBDIR,
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
        return count

    def _clear_wavs(self, directory: Path, label: str) -> None:
        """Delete WAV files under a cache subdirectory."""
        if not directory.exists():
            return
        count = sum(
            1
            for wav_file in directory.rglob("*.wav")
            if wav_file.unlink(missing_ok=True) is None
        )
        if count:
            logger.info("Local Voice cleared %d %s WAV files", count, label)

    def _precache_is_current(self, generation: int) -> bool:
        with self._precache_lock:
            return generation == self._precache_generation

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

    def _locale(self) -> dict:
        return _LOCALES.get(self._model_name()[:2], _LOCALES["en"])

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
