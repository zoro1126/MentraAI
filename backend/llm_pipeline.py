
#!/usr/bin/env python3
"""
llm_stts.py

Single-file, OOP backend for:
- STT (speech-to-text)
- LLM (text generation)
- TTS (text-to-speech)

Features:
- Verbose logging
- Graceful shutdown via SIGINT/SIGTERM
- Resumable checkpoints
- CLI progress reporting
- Optional Flask API for frontend integration

Dependencies:
    pip install faster-whisper llama-cpp-python pyttsx3 tqdm flask
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import os
import signal
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover
    tqdm = None

try:
    from faster_whisper import WhisperModel
except Exception as exc:  # pragma: no cover
    WhisperModel = None
    _FASTER_WHISPER_IMPORT_ERROR = exc

try:
    from llama_cpp import Llama
except Exception as exc:  # pragma: no cover
    Llama = None
    _LLAMA_CPP_IMPORT_ERROR = exc

try:
    import pyttsx3
except Exception as exc:  # pragma: no cover
    pyttsx3 = None
    _Pyttsx3_IMPORT_ERROR = exc

try:
    from flask import Flask, jsonify, request
except Exception:  # pragma: no cover
    Flask = None
    jsonify = None
    request = None


LOGGER = logging.getLogger("llm_stts")


@dataclass
class PipelineConfig:
    """Configuration for the full audio-to-response pipeline."""

    llm_model_path: Path
    stt_model_size: str = "base"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    llm_n_ctx: int = 2048
    llm_n_threads: int = max(1, (os.cpu_count() or 4) - 1)
    llm_n_batch: int = 256
    llm_temperature: float = 0.7
    llm_top_p: float = 0.9
    llm_repeat_penalty: float = 1.1
    llm_max_tokens: int = 256
    llm_stop_sequences: Tuple[str, ...] = ("User:", "System:")
    tts_rate: int = 175
    tts_volume: float = 1.0
    tts_voice_name: Optional[str] = None
    output_dir: Path = Path("outputs")
    checkpoint_dir: Path = Path("checkpoints")
    keep_temp_files: bool = False
    language: Optional[str] = None
    system_prompt: str = (
        "You are a helpful, concise assistant. "
        "Answer clearly and avoid unnecessary verbosity."
    )
    request_timeout_sec: Optional[float] = None


@dataclass
class PipelineState:
    """Serializable state used to resume partially completed runs."""

    input_audio: str = ""
    input_audio_hash: str = ""
    stt_text: str = ""
    llm_response: str = ""
    tts_audio_path: str = ""
    stage: str = "initialized"
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = dataclasses.asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineState":
        return cls(
            input_audio=data.get("input_audio", ""),
            input_audio_hash=data.get("input_audio_hash", ""),
            stt_text=data.get("stt_text", ""),
            llm_response=data.get("llm_response", ""),
            tts_audio_path=data.get("tts_audio_path", ""),
            stage=data.get("stage", "initialized"),
            updated_at=float(data.get("updated_at", time.time())),
            metadata=dict(data.get("metadata", {})),
        )


class GracefulStopController:
    """Controls cooperative shutdown and interruption handling."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._original_handlers: Dict[int, Any] = {}

    @property
    def requested(self) -> bool:
        return self._stop_event.is_set()

    def request_stop(self, signum: Optional[int] = None, frame: Any = None) -> None:
        if not self._stop_event.is_set():
            LOGGER.warning("Stop requested%s.", f" by signal {signum}" if signum else "")
        self._stop_event.set()

    def install(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._original_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self.request_stop)
            except Exception:
                LOGGER.debug("Could not install signal handler for %s.", sig)

    def restore(self) -> None:
        for sig, handler in self._original_handlers.items():
            try:
                signal.signal(sig, handler)
            except Exception:
                LOGGER.debug("Could not restore signal handler for %s.", sig)

    def raise_if_requested(self) -> None:
        if self.requested:
            raise InterruptedError("Execution stopped by user request.")


class ProgressReporter:
    """Unified progress reporter with tqdm fallback."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and tqdm is not None
        self._bar = None

    @contextmanager
    def stage(self, description: str, total: Optional[int] = None) -> Generator["ProgressReporter", None, None]:
        if self.enabled:
            self._bar = tqdm(total=total, desc=description, unit="step", leave=True)
        else:
            LOGGER.info("%s ...", description)
            self._bar = None
        try:
            yield self
        finally:
            if self._bar is not None:
                self._bar.close()
                self._bar = None

    def update(self, n: int = 1, message: Optional[str] = None) -> None:
        if self._bar is not None:
            self._bar.update(n)
            if message:
                self._bar.set_postfix_str(message)
        elif message:
            LOGGER.info(message)

    def write(self, message: str) -> None:
        if self._bar is not None:
            self._bar.write(message)
        else:
            LOGGER.info(message)


class CheckpointManager:
    """Reads and writes resumable checkpoints on disk."""

    def __init__(self, checkpoint_dir: Path) -> None:
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_input_hash(audio_path: Path) -> str:
        hasher = hashlib.sha256()
        with audio_path.open("rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def checkpoint_path_for(self, audio_path: Path) -> Path:
        key = hashlib.sha256(str(audio_path.resolve()).encode("utf-8")).hexdigest()[:16]
        return self.checkpoint_dir / f"{key}.json"

    def load(self, audio_path: Path) -> Optional[PipelineState]:
        path = self.checkpoint_path_for(audio_path)
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as file_handle:
                data = json.load(file_handle)
            state = PipelineState.from_dict(data)
            if state.input_audio_hash and state.input_audio_hash != self.compute_input_hash(audio_path):
                LOGGER.warning("Checkpoint hash mismatch; ignoring stale checkpoint.")
                return None
            return state
        except Exception:
            LOGGER.exception("Failed to load checkpoint: %s", path)
            return None

    def save(self, audio_path: Path, state: PipelineState) -> Path:
        path = self.checkpoint_path_for(audio_path)
        state.updated_at = time.time()
        tmp_path = path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as file_handle:
            json.dump(state.to_dict(), file_handle, indent=2, ensure_ascii=False)
        tmp_path.replace(path)
        LOGGER.debug("Checkpoint saved: %s", path)
        return path

    def clear(self, audio_path: Path) -> None:
        path = self.checkpoint_path_for(audio_path)
        try:
            if path.exists():
                path.unlink()
        except Exception:
            LOGGER.exception("Failed to clear checkpoint: %s", path)


class SpeechToTextEngine:
    """STT engine based on faster-whisper."""

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model: Optional[Any] = None

    def load(self, progress: Optional[ProgressReporter] = None) -> None:
        if WhisperModel is None:
            raise ImportError(
                "faster-whisper is not installed."
            ) from _FASTER_WHISPER_IMPORT_ERROR

        if self._model is not None:
            return

        if progress is not None:
            progress.write(
                f"Loading Whisper model '{self.model_size}' on {self.device} ({self.compute_type})"
            )

        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )

    def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        progress: Optional[ProgressReporter] = None,
        stop_event: Optional[threading.Event] = None,
        checkpoint_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, bool]:
        if self._model is None:
            self.load(progress=progress)

        assert self._model is not None
        LOGGER.debug("Starting transcription for: %s", audio_path)

        segments_text: List[str] = []
        segment_counter = 0
        completed = True

        segments, info = self._model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
        )

        if progress is not None:
            progress.write(
                f"Detected language: {info.language} (prob={info.language_probability:.3f})"
            )

        for segment in segments:
            if stop_event is not None and stop_event.is_set():
                LOGGER.warning("STT interrupted by stop request.")
                completed = False
                break

            segment_counter += 1
            text = segment.text.strip()
            if text:
                segments_text.append(text)

            current_transcript = " ".join(segments_text).strip()
            if checkpoint_callback is not None:
                checkpoint_callback(current_transcript)

            if progress is not None:
                progress.update(1, f"segment {segment_counter}")
            LOGGER.debug(
                "STT segment %s [%.2f -> %.2f]: %s",
                segment.id,
                segment.start,
                segment.end,
                text,
            )

        transcript = " ".join(segments_text).strip()
        LOGGER.debug(
            "Transcription completed=%s. Characters=%d",
            completed,
            len(transcript),
        )
        return transcript, completed

    def close(self) -> None:
        self._model = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class LLMEngine:
    """LLM inference engine based on llama-cpp-python."""

    def __init__(
        self,
        model_path: Path,
        n_ctx: int = 2048,
        n_threads: int = 4,
        n_batch: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.9,
        repeat_penalty: float = 1.1,
        max_tokens: int = 256,
        stop_sequences: Tuple[str, ...] = ("User:", "System:"),
    ) -> None:
        self.model_path = Path(model_path)
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.n_batch = n_batch
        self.temperature = temperature
        self.top_p = top_p
        self.repeat_penalty = repeat_penalty
        self.max_tokens = max_tokens
        self.stop_sequences = stop_sequences
        self._llm: Optional[Any] = None

    def load(self, progress: Optional[ProgressReporter] = None) -> None:
        if Llama is None:
            raise ImportError("llama-cpp-python is not installed.") from _LLAMA_CPP_IMPORT_ERROR

        if self._llm is not None:
            return

        if not self.model_path.exists():
            raise FileNotFoundError(f"LLM model not found: {self.model_path}")

        if progress is not None:
            progress.write(f"Loading LLM model: {self.model_path}")

        self._llm = Llama(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_threads=self.n_threads,
            n_batch=self.n_batch,
            verbose=False,
        )

    @staticmethod
    def build_prompt(system_prompt: str, user_prompt: str) -> str:
        return (
            f"System: {system_prompt.strip()}\n"
            f"User: {user_prompt.strip()}\n"
            f"Assistant:"
        )

    def generate(
        self,
        user_prompt: str,
        system_prompt: str,
        progress: Optional[ProgressReporter] = None,
        stop_event: Optional[threading.Event] = None,
        checkpoint_callback: Optional[Callable[[str], None]] = None,
        checkpoint_every: int = 5,
    ) -> Tuple[str, bool]:
        if self._llm is None:
            self.load(progress=progress)

        assert self._llm is not None
        prompt = self.build_prompt(system_prompt=system_prompt, user_prompt=user_prompt)
        LOGGER.debug("LLM prompt length: %d chars", len(prompt))

        response_chunks: List[str] = []
        token_count = 0
        completed = True

        stream = self._llm(
            prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            repeat_penalty=self.repeat_penalty,
            stop=list(self.stop_sequences),
            stream=True,
        )

        for chunk in stream:
            if stop_event is not None and stop_event.is_set():
                LOGGER.warning("LLM generation interrupted by stop request.")
                completed = False
                break

            token_text = chunk["choices"][0]["text"]
            response_chunks.append(token_text)
            token_count += 1

            if progress is not None:
                progress.update(1, f"tokens {token_count}")

            if checkpoint_callback is not None and token_count % max(1, checkpoint_every) == 0:
                checkpoint_callback("".join(response_chunks).strip())

            LOGGER.debug("LLM token %d: %r", token_count, token_text)

        response = "".join(response_chunks).strip()
        if checkpoint_callback is not None:
            checkpoint_callback(response)
        LOGGER.debug(
            "LLM generation completed=%s. Characters=%d",
            completed,
            len(response),
        )
        return response, completed

    def close(self) -> None:
        self._llm = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class TextToSpeechEngine:
    """Offline TTS engine based on pyttsx3."""

    def __init__(
        self,
        rate: int = 175,
        volume: float = 1.0,
        voice_name: Optional[str] = None,
    ) -> None:
        self.rate = rate
        self.volume = volume
        self.voice_name = voice_name
        self._engine: Optional[Any] = None

    def load(self, progress: Optional[ProgressReporter] = None) -> None:
        if pyttsx3 is None:
            raise ImportError("pyttsx3 is not installed.") from _Pyttsx3_IMPORT_ERROR

        if self._engine is not None:
            return

        if progress is not None:
            progress.write("Initializing TTS engine")

        self._engine = pyttsx3.init()
        self._engine.setProperty("rate", self.rate)
        self._engine.setProperty("volume", self.volume)

        if self.voice_name:
            selected = False
            for voice in self._engine.getProperty("voices"):
                voice_id = getattr(voice, "id", "")
                voice_label = f"{getattr(voice, 'name', '')} {voice_id}"
                if self.voice_name.lower() in voice_label.lower():
                    self._engine.setProperty("voice", voice.id)
                    selected = True
                    LOGGER.debug("Selected TTS voice: %s", voice_label)
                    break
            if not selected:
                LOGGER.warning("Requested TTS voice not found: %s", self.voice_name)

    def synthesize(
        self,
        text: str,
        output_path: Path,
        progress: Optional[ProgressReporter] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Path:
        if self._engine is None:
            self.load(progress=progress)

        assert self._engine is not None
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if progress is not None:
            progress.write(f"Saving TTS output: {output_path}")

        # pyttsx3 does not provide a robust progress callback during file save.
        # We expose deterministic stage progress instead.
        temp_path = output_path.with_suffix(".tmp.wav")
        if stop_event is not None and stop_event.is_set():
            raise InterruptedError("TTS skipped because stop was requested.")

        self._engine.save_to_file(text, str(temp_path))
        self._engine.runAndWait()

        if stop_event is not None and stop_event.is_set():
            LOGGER.warning("Stop requested after TTS synthesis; keeping temp file.")
            if temp_path.exists():
                return temp_path

        if temp_path.exists():
            temp_path.replace(output_path)
        else:
            LOGGER.warning("Expected TTS temp file missing: %s", temp_path)

        return output_path

    def close(self) -> None:
        self._engine = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class AIWorkflow:
    """Orchestrates STT -> LLM -> TTS with checkpointing."""

    def __init__(
        self,
        config: PipelineConfig,
        stop_controller: Optional[GracefulStopController] = None,
        verbose: bool = True,
    ) -> None:
        self.config = config
        self.stop_controller = stop_controller or GracefulStopController()
        self.progress = ProgressReporter(enabled=verbose)
        self.checkpoints = CheckpointManager(config.checkpoint_dir)
        self.stt = SpeechToTextEngine(
            model_size=config.stt_model_size,
            device=config.stt_device,
            compute_type=config.stt_compute_type,
        )
        self.llm = LLMEngine(
            model_path=config.llm_model_path,
            n_ctx=config.llm_n_ctx,
            n_threads=config.llm_n_threads,
            n_batch=config.llm_n_batch,
            temperature=config.llm_temperature,
            top_p=config.llm_top_p,
            repeat_penalty=config.llm_repeat_penalty,
            max_tokens=config.llm_max_tokens,
            stop_sequences=config.llm_stop_sequences,
        )
        self.tts = TextToSpeechEngine(
            rate=config.tts_rate,
            volume=config.tts_volume,
            voice_name=config.tts_voice_name,
        )

    def _prepare_input(self, audio_path: Path) -> PipelineState:
        audio_path = audio_path.expanduser().resolve()
        if not audio_path.exists():
            raise FileNotFoundError(f"Input audio file not found: {audio_path}")
        if not audio_path.is_file():
            raise IsADirectoryError(f"Input path is not a file: {audio_path}")

        input_hash = self.checkpoints.compute_input_hash(audio_path)
        state = PipelineState(
            input_audio=str(audio_path),
            input_audio_hash=input_hash,
            metadata={
                "size_bytes": audio_path.stat().st_size,
                "mtime": audio_path.stat().st_mtime,
            },
        )
        return state

    def _resume_or_new(self, audio_path: Path, resume: bool) -> PipelineState:
        fresh_state = self._prepare_input(audio_path)
        if not resume:
            return fresh_state

        existing = self.checkpoints.load(audio_path)
        if existing is None:
            return fresh_state

        LOGGER.info("Resuming from checkpoint: stage=%s", existing.stage)
        if existing.input_audio_hash != fresh_state.input_audio_hash:
            LOGGER.warning("Checkpoint belongs to a different input. Starting fresh.")
            return fresh_state
        return existing

    def _save_state(self, audio_path: Path, state: PipelineState) -> None:
        self.checkpoints.save(audio_path, state)

    def run(
        self,
        audio_path: Path,
        resume: bool = True,
        save_intermediate: bool = True,
    ) -> Dict[str, Any]:
        audio_path = audio_path.expanduser().resolve()
        self.stop_controller.install()

        try:
            state = self._resume_or_new(audio_path, resume=resume)
            self.config.output_dir.mkdir(parents=True, exist_ok=True)

            self.stop_controller.raise_if_requested()

            # STT
            if state.stage not in {"transcribed", "generated", "completed"}:
                with self.progress.stage("STT", total=None) as progress:
                    state.stage = "transcribing"
                    self._save_state(audio_path, state)

                    def stt_checkpoint(text: str) -> None:
                        state.stt_text = text
                        state.stage = "transcribing"
                        self._save_state(audio_path, state)

                    state.stt_text, stt_completed = self.stt.transcribe(
                        audio_path=audio_path,
                        language=self.config.language,
                        progress=progress,
                        stop_event=self.stop_controller._stop_event,
                        checkpoint_callback=stt_checkpoint,
                    )
                    if not stt_completed:
                        state.stage = "transcribing"
                        self._save_state(audio_path, state)
                        raise InterruptedError("Stopped during transcription.")
                    state.stage = "transcribed"
                    self._save_state(audio_path, state)
            else:
                LOGGER.info("Skipping STT (already complete in checkpoint).")

            self.stop_controller.raise_if_requested()

            # LLM
            if state.stage not in {"generated", "completed"}:
                with self.progress.stage("LLM", total=self.config.llm_max_tokens) as progress:
                    state.stage = "generating"
                    self._save_state(audio_path, state)

                    def llm_checkpoint(text: str) -> None:
                        state.llm_response = text
                        state.stage = "generating"
                        self._save_state(audio_path, state)

                    state.llm_response, llm_completed = self.llm.generate(
                        user_prompt=state.stt_text,
                        system_prompt=self.config.system_prompt,
                        progress=progress,
                        stop_event=self.stop_controller._stop_event,
                        checkpoint_callback=llm_checkpoint,
                    )
                    if not llm_completed:
                        state.stage = "generating"
                        self._save_state(audio_path, state)
                        raise InterruptedError("Stopped during generation.")
                    state.stage = "generated"
                    self._save_state(audio_path, state)
            else:
                LOGGER.info("Skipping LLM (already complete in checkpoint).")

            self.stop_controller.raise_if_requested()

            # TTS
            if state.stage != "completed" or not state.tts_audio_path:
                out_name = f"{audio_path.stem}_{self._short_hash(state.llm_response)}.wav"
                output_path = self.config.output_dir / out_name
                with self.progress.stage("TTS", total=None) as progress:
                    state.stage = "synthesizing"
                    self._save_state(audio_path, state)
                    final_path = self.tts.synthesize(
                        text=state.llm_response,
                        output_path=output_path,
                        progress=progress,
                        stop_event=self.stop_controller._stop_event,
                    )
                    state.tts_audio_path = str(final_path)
                    state.stage = "completed"
                    self._save_state(audio_path, state)
            else:
                LOGGER.info("Skipping TTS (already complete in checkpoint).")

            result = {
                "input_audio": state.input_audio,
                "text": state.stt_text,
                "response": state.llm_response,
                "audio_path": state.tts_audio_path,
                "stage": state.stage,
            }

            if not save_intermediate:
                self.checkpoints.clear(audio_path)

            return result

        except InterruptedError:
            LOGGER.warning("Execution interrupted. State has been checkpointed.")
            raise
        except Exception:
            LOGGER.exception("Pipeline failed.")
            raise
        finally:
            self.stop_controller.restore()

    @staticmethod
    def _short_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm_stts.py",
        description="Single-file STT -> LLM -> TTS pipeline with checkpointing.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Process an audio file end-to-end.")
    run_parser.add_argument("--audio", required=True, help="Input audio file path.")
    run_parser.add_argument("--model", required=True, help="Path to GGUF model.")
    run_parser.add_argument("--stt-model", default="base", help="faster-whisper model size.")
    run_parser.add_argument("--stt-device", default="cpu", help="STT device.")
    run_parser.add_argument("--stt-compute-type", default="int8", help="STT compute type.")
    run_parser.add_argument("--ctx", type=int, default=2048, help="LLM context size.")
    run_parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    run_parser.add_argument("--batch", type=int, default=256, help="LLM batch size.")
    run_parser.add_argument("--max-tokens", type=int, default=256, help="LLM max output tokens.")
    run_parser.add_argument("--temperature", type=float, default=0.7, help="LLM temperature.")
    run_parser.add_argument("--top-p", type=float, default=0.9, help="LLM top-p.")
    run_parser.add_argument("--repeat-penalty", type=float, default=1.1, help="LLM repeat penalty.")
    run_parser.add_argument("--language", default=None, help="Force STT language.")
    run_parser.add_argument("--output-dir", default="outputs", help="Output directory.")
    run_parser.add_argument("--checkpoint-dir", default="checkpoints", help="Checkpoint directory.")
    run_parser.add_argument("--no-resume", action="store_true", help="Do not resume from checkpoint.")
    run_parser.add_argument("--no-clear-checkpoint", action="store_true", help="Keep checkpoint after success.")
    run_parser.add_argument("--tts-rate", type=int, default=175, help="TTS speaking rate.")
    run_parser.add_argument("--tts-volume", type=float, default=1.0, help="TTS volume.")
    run_parser.add_argument("--tts-voice", default=None, help="Preferred voice name fragment.")
    run_parser.add_argument("--system-prompt", default=None, help="Override system prompt.")
    run_parser.add_argument("--quiet", action="store_true", help="Reduce console output.")
    run_parser.add_argument("--save-json", default=None, help="Save final JSON to this path.")

    serve_parser = subparsers.add_parser("serve", help="Run a small Flask API server.")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=5000)
    serve_parser.add_argument("--model", required=True, help="Path to GGUF model.")
    serve_parser.add_argument("--stt-model", default="base")
    serve_parser.add_argument("--stt-device", default="cpu")
    serve_parser.add_argument("--stt-compute-type", default="int8")
    serve_parser.add_argument("--ctx", type=int, default=2048)
    serve_parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    serve_parser.add_argument("--batch", type=int, default=256)
    serve_parser.add_argument("--max-tokens", type=int, default=256)
    serve_parser.add_argument("--temperature", type=float, default=0.7)
    serve_parser.add_argument("--top-p", type=float, default=0.9)
    serve_parser.add_argument("--repeat-penalty", type=float, default=1.1)
    serve_parser.add_argument("--output-dir", default="outputs")
    serve_parser.add_argument("--checkpoint-dir", default="checkpoints")
    serve_parser.add_argument("--tts-rate", type=int, default=175)
    serve_parser.add_argument("--tts-volume", type=float, default=1.0)
    serve_parser.add_argument("--tts-voice", default=None)
    serve_parser.add_argument("--system-prompt", default=None)

    return parser


def configure_logging(verbose: bool = True) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as file_handle:
        json.dump(data, file_handle, indent=2, ensure_ascii=False)
    tmp_path.replace(path)


def run_cli(args: argparse.Namespace) -> int:
    configure_logging(verbose=not getattr(args, "quiet", False))

    config = PipelineConfig(
        llm_model_path=Path(args.model),
        stt_model_size=args.stt_model,
        stt_device=args.stt_device,
        stt_compute_type=args.stt_compute_type,
        llm_n_ctx=args.ctx,
        llm_n_threads=args.threads,
        llm_n_batch=args.batch,
        llm_temperature=args.temperature,
        llm_top_p=args.top_p,
        llm_repeat_penalty=args.repeat_penalty,
        llm_max_tokens=args.max_tokens,
        output_dir=Path(args.output_dir),
        checkpoint_dir=Path(args.checkpoint_dir),
        keep_temp_files=False,
        language=args.language,
        system_prompt=args.system_prompt or PipelineConfig.system_prompt,
        tts_rate=args.tts_rate,
        tts_volume=args.tts_volume,
        tts_voice_name=args.tts_voice,
    )

    workflow = AIWorkflow(config=config, verbose=not args.quiet)

    try:
        result = workflow.run(
            audio_path=Path(args.audio),
            resume=not args.no_resume,
            save_intermediate=args.no_clear_checkpoint,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

        if args.save_json:
            save_json(Path(args.save_json), result)

        return 0
    except InterruptedError:
        LOGGER.warning("Stopped by user. Partial progress remains in checkpoint.")
        return 130
    except Exception as exc:
        LOGGER.error("Run failed: %s", exc)
        return 1


def create_flask_app(config: PipelineConfig, verbose: bool = True):
    if Flask is None:
        raise ImportError("Flask is not installed.")

    configure_logging(verbose=verbose)
    workflow = AIWorkflow(config=config, verbose=verbose)
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/process_audio")
    def process_audio():
        if "audio" not in request.files:
            return jsonify({"error": "Missing 'audio' file field."}), 400

        uploaded = request.files["audio"]
        suffix = Path(uploaded.filename or "input.wav").suffix or ".wav"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            uploaded.save(tmp_file.name)
            tmp_path = Path(tmp_file.name)

        try:
            result = workflow.run(audio_path=tmp_path, resume=False, save_intermediate=False)
            return jsonify(result)
        except InterruptedError as exc:
            return jsonify({"error": str(exc)}), 499
        except Exception as exc:
            LOGGER.exception("API request failed.")
            return jsonify({"error": str(exc)}), 500
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                LOGGER.exception("Failed to delete temporary upload: %s", tmp_path)

    return app


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        return run_cli(args)

    if args.command == "serve":
        config = PipelineConfig(
            llm_model_path=Path(args.model),
            stt_model_size=args.stt_model,
            stt_device=args.stt_device,
            stt_compute_type=args.stt_compute_type,
            llm_n_ctx=args.ctx,
            llm_n_threads=args.threads,
            llm_n_batch=args.batch,
            llm_temperature=args.temperature,
            llm_top_p=args.top_p,
            llm_repeat_penalty=args.repeat_penalty,
            llm_max_tokens=args.max_tokens,
            output_dir=Path(args.output_dir),
            checkpoint_dir=Path(args.checkpoint_dir),
            tts_rate=args.tts_rate,
            tts_volume=args.tts_volume,
            tts_voice_name=args.tts_voice,
            system_prompt=args.system_prompt or PipelineConfig.system_prompt,
        )
        app = create_flask_app(config=config, verbose=True)
        app.run(host=args.host, port=args.port, debug=False, threaded=True)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
