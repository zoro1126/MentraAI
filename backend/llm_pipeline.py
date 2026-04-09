#!/usr/bin/env python3
"""
llm_pipeline.py

Lightweight LLM inference module for MentraAI.

Provides:
  - LLMEngine  — llama-cpp-python wrapper for local GGUF models.

STT and TTS have been removed.  User responses are now collected via a
text input box in the frontend; the LLM interprets text answers together
with behaviour labels produced by the DAIC-WOZ-trained LightGBM model.

Dependencies:
    pip install llama-cpp-python
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

LOGGER = logging.getLogger("llm_pipeline")

# ---------------------------------------------------------------------------
# Optional import
# ---------------------------------------------------------------------------
try:
    from llama_cpp import Llama
except Exception as exc:                    # pragma: no cover
    Llama = None
    _LLAMA_CPP_IMPORT_ERROR = exc


# ---------------------------------------------------------------------------
# Behavior label metadata (for prompt enrichment)
# ---------------------------------------------------------------------------
BEHAVIOR_DESCRIPTIONS: dict[str, str] = {
    "engaged":              "actively attentive, alert, and participating",
    "disengaged":           "mentally checked-out, low attention, avoidant gaze",
    "low_energy":           "fatigued, slow responses, drooping face",
    "agitated":             "restless, rapid movement, visible tension",
    "tense":                "stiff posture, furrowed brow, suppressed expression",
    "overaroused":          "wide eyes, high alertness bordering on panic",
    "withdrawn":            "closed-off, avoiding eye contact, minimal expression",
    "positive_engagement":  "smiling, open, emotionally warm and responsive",
    "cognitive_load":       "deep concentration, furrowed brow, reduced blinking",
    "ambiguous":            "mixed or unclear facial signals",
}

BEHAVIOR_STRESS_MAP: dict[str, str] = {
    "engaged":              "low",
    "disengaged":           "moderate",
    "low_energy":           "moderate",
    "agitated":             "high",
    "tense":                "high",
    "overaroused":          "high",
    "withdrawn":            "moderate",
    "positive_engagement":  "low",
    "cognitive_load":       "moderate",
    "ambiguous":            "unknown",
    "calibrating":          "unknown",
    "unavailable":          "unknown",
}


def behavior_to_insight(label: str, confidence: float) -> str:
    """Convert a behavior label + confidence into a human-readable insight string."""
    desc = BEHAVIOR_DESCRIPTIONS.get(label, label)
    conf_str = f"{confidence:.0%}" if confidence > 0 else "—"
    return f"Detected behavior: {label.replace('_', ' ').title()} ({conf_str} confidence) — {desc}"


# ---------------------------------------------------------------------------
# LLMEngine
# ---------------------------------------------------------------------------

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
        max_tokens: int = 512,
        stop_sequences: Tuple[str, ...] = ("User:", "System:"),
    ) -> None:
        self.model_path     = Path(model_path)
        self.n_ctx          = n_ctx
        self.n_threads      = n_threads
        self.n_batch        = n_batch
        self.temperature    = temperature
        self.top_p          = top_p
        self.repeat_penalty = repeat_penalty
        self.max_tokens     = max_tokens
        self.stop_sequences = stop_sequences
        self._llm: Optional[Any] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def load(self) -> None:
        with self._lock:
            if self._llm is not None:
                return
            if Llama is None:
                raise ImportError(
                    "llama-cpp-python is not installed."
                ) from _LLAMA_CPP_IMPORT_ERROR
            if not self.model_path.exists():
                raise FileNotFoundError(f"LLM model not found: {self.model_path}")

            LOGGER.info("Loading LLM: %s", self.model_path)
            self._llm = Llama(
                model_path=str(self.model_path),
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_batch=self.n_batch,
                verbose=False,
            )
            LOGGER.info("LLM loaded.")

    # ------------------------------------------------------------------
    @staticmethod
    def build_prompt(system_prompt: str, user_prompt: str) -> str:
        return (
            f"System: {system_prompt.strip()}\n"
            f"User: {user_prompt.strip()}\n"
            f"Assistant:"
        )

    # ------------------------------------------------------------------
    def generate(
        self,
        user_prompt: str,
        system_prompt: str,
        stop_event: Optional[threading.Event] = None,
        checkpoint_callback: Optional[Callable[[str], None]] = None,
        checkpoint_every: int = 5,
    ) -> Tuple[str, bool]:
        """
        Generate a response from the LLM.

        Parameters
        ----------
        user_prompt : str
        system_prompt : str
        stop_event : threading.Event, optional
        checkpoint_callback : callable, optional  — called with partial text
        checkpoint_every : int — token interval for checkpoint callbacks

        Returns
        -------
        (response_text, completed_bool)
        """
        if self._llm is None:
            self.load()

        assert self._llm is not None
        prompt = self.build_prompt(system_prompt=system_prompt, user_prompt=user_prompt)
        LOGGER.debug("LLM prompt length: %d chars", len(prompt))

        chunks: List[str] = []
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
                LOGGER.warning("LLM generation interrupted.")
                completed = False
                break

            token_text = chunk["choices"][0]["text"]
            chunks.append(token_text)
            token_count += 1

            if checkpoint_callback is not None and token_count % max(1, checkpoint_every) == 0:
                checkpoint_callback("".join(chunks).strip())

        response = "".join(chunks).strip()
        if checkpoint_callback is not None:
            checkpoint_callback(response)

        LOGGER.debug("LLM done. completed=%s chars=%d", completed, len(response))
        return response, completed

    # ------------------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            self._llm = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Behavior-aware system prompt builder
# ---------------------------------------------------------------------------

def build_behavior_system_prompt() -> str:
    """
    Return a system prompt that instructs the LLM to incorporate behavior labels
    (from the LightGBM DAIC-WOZ model) when generating mental-health analysis.
    """
    label_list = "\n".join(
        f"  • {lbl.replace('_', ' ').title()}: {desc}"
        for lbl, desc in BEHAVIOR_DESCRIPTIONS.items()
    )
    return (
        "You are an expert clinical psychologist AI assistant for MentraAI, "
        "a mental health support platform. Analyze the provided patient data "
        "and generate a comprehensive, empathetic, and personalized mental health response.\n\n"
        "The facial behavior data is produced by a LightGBM model trained on the DAIC-WOZ "
        "depression corpus using CLNF facial-feature windows. The possible behavior labels are:\n"
        f"{label_list}\n\n"
        "Interpret the detected behavior label holistically alongside PHQ-9 scores, "
        "interview responses, and stress metrics. Do NOT over-rely on a single signal.\n\n"
        "You MUST respond with a valid JSON object (no markdown, no code fences) with these exact keys:\n"
        '{"summary": "A 2-3 sentence summary of the patient\'s current state",'
        ' "advice": "A warm, personalized 3-5 sentence message to the patient",'
        ' "stress_level": "One of: Minimal, Mild, Moderate, Moderately Severe, Severe",'
        ' "stress_insights": ["insight 1", "insight 2", "insight 3"],'
        ' "coping_steps": ["step 1", "step 2", "step 3", "step 4", "step 5"],'
        ' "reminders": ["reminder 1", "reminder 2", "reminder 3"],'
        ' "risk_assessment": "low/moderate/high"}'
    )
