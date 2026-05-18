"""Piper TTS model loading, synthesis, and WAV cache handling."""

from __future__ import annotations

import hashlib
import logging
import time
import unicodedata
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from piper.config import SynthesisConfig

from .const import VOICE_MODELS

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SynthesisResult:
    """Result metadata for a synthesized or cached WAV file."""

    text: str
    wav_path: Path
    duration_ms: int
    cache_hit: bool


class PiperSynthesizer:
    """Generate local WAV files with Piper and cache them by phrase/model/speed."""

    def __init__(
        self,
        model_dir: Path,
        tts_dir: Path,
        set_status: Callable[[str], None],
    ) -> None:
        """Initialize model and TTS cache directories."""
        self._model_dir = model_dir
        self._tts_dir = tts_dir
        self._set_status = set_status
        self._voice: Any | None = None
        self._loaded_model: str | None = None

        self._model_dir.mkdir(parents=True, exist_ok=True)
        self._tts_dir.mkdir(parents=True, exist_ok=True)

    def synthesize_to_cache(
        self,
        text: str,
        model_name: str,
        speed: str,
    ) -> SynthesisResult | None:
        """Return a cached WAV for text, synthesizing it with Piper if needed."""
        normalized_text = self.normalize_text(text)
        if not normalized_text:
            self._set_status("No text supplied")
            return None

        cache_key = self.cache_key(normalized_text, model_name, speed)
        wav_path = self._tts_dir / f"{cache_key}.wav"
        started = time.perf_counter()

        if wav_path.exists() and self.valid_wav(wav_path):
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.info("Local Voice cache hit for '%s': %s", normalized_text, wav_path)
            return SynthesisResult(
                text=normalized_text,
                wav_path=wav_path,
                duration_ms=duration_ms,
                cache_hit=True,
            )

        voice = self._load_voice(model_name)
        if voice is None:
            return None

        try:
            syn_config = SynthesisConfig(length_scale=1.0 / float(speed))
            with wave.open(str(wav_path), "wb") as wav_file:
                voice.synthesize_wav(normalized_text, wav_file, syn_config=syn_config)
        except Exception as exc:
            wav_path.unlink(missing_ok=True)
            self._set_status(f"Synthesis failed: {exc}")
            logger.exception("Local Voice synthesis failed for '%s'", normalized_text)
            return None

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "Local Voice synthesized '%s' to %s in %sms",
            normalized_text,
            wav_path,
            duration_ms,
        )
        return SynthesisResult(
            text=normalized_text,
            wav_path=wav_path,
            duration_ms=duration_ms,
            cache_hit=False,
        )

    def cache_status_text(self) -> str:
        """Return cache directory and file-count status."""
        cached_files = sum(1 for path in self._tts_dir.glob("*.wav") if path.is_file())
        return f"{self._tts_dir} | {cached_files} cached WAV files"

    def _load_voice(self, model_name: str) -> Any | None:
        """Load the selected Piper model once, downloading files if necessary."""
        if self._voice is not None and self._loaded_model == model_name:
            return self._voice

        model_path = self._ensure_model_files(model_name)
        if model_path is None:
            return None

        try:
            from piper import PiperVoice  # noqa: PLC0415
        except ImportError:
            self._set_status(
                "piper-tts is not installed in the RotorHazard environment"
            )
            logger.exception("piper-tts import failed")
            return None

        try:
            self._set_status(f"Loading model {model_name}")
            self._voice = PiperVoice.load(str(model_path))
            self._loaded_model = model_name
            self._set_status(f"Model loaded: {model_name}")
        except Exception as exc:
            self._voice = None
            self._loaded_model = None
            self._set_status(f"Model load failed: {exc}")
            logger.exception("Local Voice failed to load Piper model %s", model_name)
            return None

        return self._voice

    def _ensure_model_files(self, model_name: str) -> Path | None:
        """Ensure the selected Piper model and JSON config are present locally."""
        model = VOICE_MODELS.get(model_name)
        if model is None:
            self._set_status(f"Unknown model: {model_name}")
            return None

        model_path = self._model_dir / f"{model_name}.onnx"
        config_path = self._model_dir / f"{model_name}.onnx.json"
        if model_path.exists() and config_path.exists():
            return model_path

        self._set_status(f"Downloading model {model_name}")
        base_url = model["base_url"]
        downloads = (
            (f"{base_url}.onnx", model_path),
            (f"{base_url}.onnx.json", config_path),
        )
        for url, destination in downloads:
            if destination.exists():
                continue
            try:
                self._download_file(url, destination)
            except (OSError, urllib.error.URLError) as exc:
                destination.unlink(missing_ok=True)
                self._set_status(f"Model download failed: {exc}")
                logger.exception("Local Voice model download failed from %s", url)
                return None

        return model_path

    @staticmethod
    def _download_file(url: str, destination: Path) -> None:
        """Download a URL to a local file with a temporary partial file."""
        partial_path = destination.with_suffix(f"{destination.suffix}.part")
        with (
            urllib.request.urlopen(url, timeout=60) as response,  # noqa: S310
            partial_path.open("wb") as output_file,
        ):
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output_file.write(chunk)
        partial_path.replace(destination)

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize text before synthesis and cache-key generation."""
        normalized = unicodedata.normalize("NFKC", text).strip()
        return " ".join(normalized.split())

    @staticmethod
    def cache_key(text: str, model_name: str, speed: str) -> str:
        """Build the configured SHA1-based WAV cache key."""
        digest = hashlib.sha1(text.lower().encode("utf-8")).hexdigest()  # noqa: S324
        return f"{digest}_{model_name}_{speed}"

    @staticmethod
    def valid_wav(path: Path) -> bool:
        """Return whether a cached path can be opened as a WAV file."""
        try:
            with wave.open(str(path), "rb") as wav_file:
                return wav_file.getnframes() >= 0
        except (OSError, wave.Error):
            return False
