"""
train.py — Behavior Classification Training Pipeline
=====================================================
Loads CLNF AU / Pose / Gaze files from backend/data/,
applies temporal windowing and feature aggregation, trains
a LightGBM multi-class classifier, evaluates it, and saves
the model + label encoder to disk.

Run:
    python backend/train.py
"""

from __future__ import annotations

import logging
import os
import pickle
import random
import re
import warnings
from pathlib import Path
from typing import Iterator

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.exceptions import UndefinedMetricWarning
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

warnings.filterwarnings("ignore", category=UndefinedMetricWarning)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("train")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RANDOM_SEED: int = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

DATA_DIR: Path = Path("backend/data")
MODEL_OUT: Path = Path("backend/behavior_model.pkl")
ENCODER_OUT: Path = Path("backend/label_encoder.pkl")

WINDOW_SIZE: int = 30          # frames  (≈ 1 s @ 30 fps)
TEST_SIZE: float = 0.20

# Feature columns to extract from each file type
AU_COLS: list[str] = [
    "AU01_r", "AU02_r", "AU04_r", "AU05_r", "AU06_r",
    "AU09_r", "AU12_r", "AU15_r", "AU20_r",
]

POSE_COLS: list[str] = ["Rx", "Ry", "Rz"]          # pitch / yaw / roll

GAZE_COLS: list[str] = []  # derived from gaze vectors; computed below

BEHAVIOR_LABELS: list[str] = [
    "engaged",
    "disengaged",
    "low_energy",
    "agitated",
    "tense",
    "overaroused",
    "withdrawn",
    "positive_engagement",
    "cognitive_load",
    "ambiguous",
]

# Statistical aggregation functions applied per window
AGG_FUNCS: dict[str, callable] = {
    "mean": np.mean,
    "std":  np.std,
    "max":  np.max,
    "min":  np.min,
}

# ---------------------------------------------------------------------------
# Rule-based label assignment
# ---------------------------------------------------------------------------
# Heuristic rules derived from FACS / AU literature:
#   AU01+AU04         → cognitive_load / tense
#   AU05 (wide eyes)  → overaroused / agitated
#   AU06+AU12         → positive_engagement / engaged
#   AU15+AU20         → low_energy / withdrawn / disengaged
#   High pose motion  → agitated
#   Averted gaze      → withdrawn / disengaged
#
# The rule set produces a "soft vote" across candidate labels;
# the most-voted one wins.
# ---------------------------------------------------------------------------

def _assign_label(window_mean: dict[str, float]) -> str:
    """Assign a behaviour label to a window based on mean feature values."""
    votes: dict[str, int] = {lbl: 0 for lbl in BEHAVIOR_LABELS}

    au01 = window_mean.get("AU01_r", 0.0)
    au02 = window_mean.get("AU02_r", 0.0)
    au04 = window_mean.get("AU04_r", 0.0)
    au05 = window_mean.get("AU05_r", 0.0)
    au06 = window_mean.get("AU06_r", 0.0)
    au09 = window_mean.get("AU09_r", 0.0)
    au12 = window_mean.get("AU12_r", 0.0)
    au15 = window_mean.get("AU15_r", 0.0)
    au20 = window_mean.get("AU20_r", 0.0)

    rx   = abs(window_mean.get("Rx", 0.0))   # pitch
    ry   = abs(window_mean.get("Ry", 0.0))   # yaw
    rz   = abs(window_mean.get("Rz", 0.0))   # roll
    pose_motion = rx + ry + rz

    gaze_x = abs(window_mean.get("gaze_angle_x", 0.0))
    gaze_y = abs(window_mean.get("gaze_angle_y", 0.0))
    gaze_aversion = gaze_x + gaze_y

    # ---- positive engagement / happy ----
    if au06 > 0.5 and au12 > 0.5:
        votes["positive_engagement"] += 3
        votes["engaged"] += 1

    # ---- general engagement ----
    if gaze_aversion < 0.15 and pose_motion < 0.3:
        votes["engaged"] += 2

    # ---- cognitive load / furrowed brow ----
    if au04 > 0.4 and au01 > 0.3:
        votes["cognitive_load"] += 3
    if au04 > 0.4 and au09 > 0.3:
        votes["tense"] += 2
        votes["cognitive_load"] += 1

    # ---- overaroused / agitated ----
    if au05 > 0.5:
        votes["overaroused"] += 2
    if pose_motion > 0.6:
        votes["agitated"] += 3
        votes["overaroused"] += 1

    # ---- low energy / sad / withdrawn ----
    if au15 > 0.4 and au20 > 0.3:
        votes["low_energy"] += 3
        votes["withdrawn"] += 1
    if gaze_aversion > 0.35 and pose_motion < 0.25:
        votes["withdrawn"] += 2
        votes["disengaged"] += 1

    # ---- disengaged ----
    if gaze_aversion > 0.30 or pose_motion > 0.4:
        votes["disengaged"] += 1
    if au02 > 0.6:          # raised outer brow → surprise / disengagement
        votes["disengaged"] += 1

    # ---- tense ----
    if au04 > 0.5 and au05 > 0.3:
        votes["tense"] += 2

    # ---- fallback ----
    if all(v == 0 for v in votes.values()):
        return "ambiguous"

    return max(votes, key=votes.get)


# ---------------------------------------------------------------------------
# DataLoader
# ---------------------------------------------------------------------------

class DataLoader:
    """
    Locates and loads CLNF AU / Pose / Gaze file triplets from `data_dir`.

    Multiple sessions can share the same directory (flat layout):
        302_CLNF_AUs.txt
        302_CLNF_pose.txt
        302_CLNF_gaze.txt
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def _session_ids(self) -> list[str]:
        """Return sorted list of session IDs that have all three files."""
        pattern = re.compile(r"^(\d+(?:_P)?)_CLNF_AUs\.txt$")
        ids: list[str] = []
        for fname in os.listdir(self.data_dir):
            m = pattern.match(fname)
            if m:
                sid = m.group(1)
                if (
                    (self.data_dir / f"{sid}_CLNF_pose.txt").exists()
                    and (self.data_dir / f"{sid}_CLNF_gaze.txt").exists()
                ):
                    ids.append(sid)
        return sorted(ids)

    def iter_sessions(self) -> Iterator[tuple[str, pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
        """Yield (session_id, au_df, pose_df, gaze_df) for each complete session."""
        for sid in self._session_ids():
            try:
                au_df   = self._load_csv(self.data_dir / f"{sid}_CLNF_AUs.txt")
                pose_df = self._load_csv(self.data_dir / f"{sid}_CLNF_pose.txt")
                gaze_df = self._load_csv(self.data_dir / f"{sid}_CLNF_gaze.txt")
                yield sid, au_df, pose_df, gaze_df
            except Exception as exc:
                log.warning("Session %s skipped — %s", sid, exc)

    @staticmethod
    def _load_csv(path: Path) -> pd.DataFrame:
        df = pd.read_csv(path, skipinitialspace=True)
        # Normalise column names (strip whitespace)
        df.columns = [c.strip() for c in df.columns]
        return df


# ---------------------------------------------------------------------------
# FeatureBuilder
# ---------------------------------------------------------------------------

class FeatureBuilder:
    """
    Aligns AU / Pose / Gaze frames and builds temporal window features.

    Gaze angle is derived from the 3-D gaze direction vectors:
        gaze_angle_x = mean angle in x  (average of left/right eye)
        gaze_angle_y = mean angle in y
    """

    def __init__(self, window_size: int = WINDOW_SIZE) -> None:
        self.window_size = window_size

    # ------------------------------------------------------------------
    def build_session_frames(
        self,
        au_df: pd.DataFrame,
        pose_df: pd.DataFrame,
        gaze_df: pd.DataFrame,
    ) -> pd.DataFrame | None:
        """
        Merge and clean frame-level features for one session.
        Returns a DataFrame with columns [AU_COLS + POSE_COLS + gaze_angle_x/y]
        or None if the session is too short.
        """
        # Keep only 'success==1' frames (OpenFace tracking confidence)
        if "success" in au_df.columns:
            au_df   = au_df[au_df["success"] == 1]
        if "success" in pose_df.columns:
            pose_df = pose_df[pose_df["success"] == 1]
        if "success" in gaze_df.columns:
            gaze_df = gaze_df[gaze_df["success"] == 1]

        # Extract needed AU columns (ignore missing gracefully)
        au_cols_present   = [c for c in AU_COLS   if c in au_df.columns]
        pose_cols_present = [c for c in POSE_COLS if c in pose_df.columns]

        au_data   = au_df[au_cols_present].reset_index(drop=True)
        pose_data = pose_df[pose_cols_present].reset_index(drop=True)
        gaze_data = self._compute_gaze_angles(gaze_df).reset_index(drop=True)

        # Align by minimum length
        n = min(len(au_data), len(pose_data), len(gaze_data))
        if n < self.window_size:
            return None

        frames = pd.concat(
            [au_data.iloc[:n], pose_data.iloc[:n], gaze_data.iloc[:n]],
            axis=1,
        )

        # Forward-fill then back-fill NaN
        frames = frames.ffill().bfill()

        # Drop rows that are still NaN (rare edge case)
        frames = frames.dropna()

        return frames if len(frames) >= self.window_size else None

    @staticmethod
    def _compute_gaze_angles(gaze_df: pd.DataFrame) -> pd.DataFrame:
        """
        Derive gaze_angle_x and gaze_angle_y from the 3-D gaze vectors.

        OpenFace gaze columns:
            x_0, y_0, z_0  — left-eye gaze direction (unit vector)
            x_1, y_1, z_1  — right-eye gaze direction
        """
        result = pd.DataFrame()

        if all(c in gaze_df.columns for c in ["x_0", "y_0", "z_0", "x_1", "y_1", "z_1"]):
            # Average both eyes; arctan for intuitive angle (radians)
            gx = (gaze_df["x_0"] + gaze_df["x_1"]) / 2.0
            gy = (gaze_df["y_0"] + gaze_df["y_1"]) / 2.0
            gz = (gaze_df["z_0"] + gaze_df["z_1"]) / 2.0

            # Clamp gz away from zero before division
            gz = gz.where(gz.abs() > 1e-6, other=np.sign(gz) * 1e-6)
            gz = gz.where(gz != 0, other=1e-6)

            result["gaze_angle_x"] = np.arctan2(gx.values, gz.abs().values)
            result["gaze_angle_y"] = np.arctan2(gy.values, gz.abs().values)
        else:
            result["gaze_angle_x"] = 0.0
            result["gaze_angle_y"] = 0.0

        return result

    # ------------------------------------------------------------------
    def extract_window_features(self, frames: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """
        Split `frames` into non-overlapping windows of `window_size`.

        Returns
        -------
        X : (n_windows, n_features) float64 feature matrix
        label_means : (n_windows,) dict list — mean values per window for labelling
        """
        feature_rows: list[np.ndarray] = []
        label_mean_rows: list[dict] = []

        values = frames.values.astype(np.float64)
        cols   = list(frames.columns)
        n_windows = len(values) // self.window_size

        for i in range(n_windows):
            block = values[i * self.window_size: (i + 1) * self.window_size]

            row_parts: list[float] = []
            for func in AGG_FUNCS.values():
                row_parts.extend(func(block, axis=0).tolist())

            feature_rows.append(row_parts)
            label_mean_rows.append(dict(zip(cols, np.mean(block, axis=0).tolist())))

        return np.array(feature_rows, dtype=np.float64), label_mean_rows


# ---------------------------------------------------------------------------
# LabelBuilder
# ---------------------------------------------------------------------------

class LabelBuilder:
    """Assigns behaviour labels to windows using heuristics."""

    @staticmethod
    def assign(label_means: list[dict]) -> list[str]:
        return [_assign_label(m) for m in label_means]


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------

class Trainer:
    """Wraps LightGBM training, evaluation, and model persistence."""

    def __init__(self) -> None:
        self.encoder = LabelEncoder()
        self.model: lgb.LGBMClassifier | None = None

    # ------------------------------------------------------------------
    def fit(self, X: np.ndarray, y_raw: np.ndarray) -> None:
        y = self.encoder.fit_transform(y_raw)

        log.info("Class distribution:")
        unique, counts = np.unique(y_raw, return_counts=True)
        for lbl, cnt in zip(unique, counts):
            log.info("  %-22s %d windows", lbl, cnt)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=TEST_SIZE,
            random_state=RANDOM_SEED,
            stratify=y,
        )
        log.info(
            "Train samples: %d  |  Test samples: %d  |  Features: %d",
            len(X_train), len(X_test), X.shape[1],
        )

        self.model = lgb.LGBMClassifier(
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=64,
            n_jobs=-1,
            random_state=RANDOM_SEED,
            verbose=-1,
        )

        log.info("Training LightGBM …")
        self.model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(50)],
        )

        log.info("Evaluating …")
        y_pred = self.model.predict(X_test)

        acc = accuracy_score(y_test, y_pred)
        log.info("Accuracy: %.4f", acc)
        print("\n" + "=" * 60)
        print(f"  Accuracy : {acc:.4f}")
        print("=" * 60)
        print("\nClassification Report:\n")
        print(
            classification_report(
                y_test, y_pred,
                target_names=self.encoder.classes_,
                zero_division=0,
            )
        )
        print("Confusion Matrix:")
        print(confusion_matrix(y_test, y_pred))
        print()

    # ------------------------------------------------------------------
    def save(self, model_path: Path, encoder_path: Path) -> None:
        with open(model_path, "wb") as f:
            pickle.dump(self.model, f)
        with open(encoder_path, "wb") as f:
            pickle.dump(self.encoder, f)
        log.info("Model saved  → %s", model_path)
        log.info("Encoder saved→ %s", encoder_path)


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

class Pipeline:
    """
    End-to-end orchestrator:
      1. Discover sessions
      2. Load & align features
      3. Create windows + aggregate
      4. Assign labels
      5. Train & evaluate
      6. Save artefacts
    """

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.loader  = DataLoader(data_dir)
        self.builder = FeatureBuilder(WINDOW_SIZE)
        self.labeller = LabelBuilder()
        self.trainer  = Trainer()

    # ------------------------------------------------------------------
    def run(self) -> None:
        log.info("Starting pipeline — data dir: %s", DATA_DIR)

        all_X: list[np.ndarray] = []
        all_y: list[str] = []

        session_ids = self.loader._session_ids()
        total = len(session_ids)
        log.info("Found %d sessions", total)

        for idx, (sid, au_df, pose_df, gaze_df) in enumerate(
            self.loader.iter_sessions(), start=1
        ):
            log.info("[%d/%d] Processing session %s", idx, total, sid)

            frames = self.builder.build_session_frames(au_df, pose_df, gaze_df)
            if frames is None:
                log.warning("  Session %s skipped — not enough valid frames", sid)
                continue

            X_sess, label_means = self.builder.extract_window_features(frames)
            if len(X_sess) == 0:
                log.warning("  Session %s skipped — no windows extracted", sid)
                continue

            y_sess = self.labeller.assign(label_means)
            all_X.append(X_sess)
            all_y.extend(y_sess)
            log.info("  → %d windows  (%d frames)", len(X_sess), len(frames))

        if not all_X:
            log.error("No data collected. Aborting.")
            return

        X = np.vstack(all_X)
        y = np.array(all_y)
        log.info("Total windows: %d  |  Total features: %d", len(X), X.shape[1])

        self.trainer.fit(X, y)
        self.trainer.save(MODEL_OUT, ENCODER_OUT)

        log.info("Pipeline complete ✓")


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pipeline = Pipeline(data_dir=DATA_DIR)
    pipeline.run()
