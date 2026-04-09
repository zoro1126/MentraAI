import cv2
import mediapipe as mp
import numpy as np

# ---------------- Compatibility: support both old and new MediaPipe ----------------
def _make_face_mesh():
    """
    MediaPipe 0.10+ removed mp.solutions in favour of the Tasks API.
    Try the legacy path first (0.9.x), then fall back to the Tasks API.
    Returns a wrapper with a .process(rgb_frame) method that looks identical
    to the old FaceMesh object so the rest of the code stays unchanged.
    """
    # --- Legacy path (mediapipe <= 0.9) ---
    try:
        solutions = mp.solutions          # raises AttributeError on 0.10+
        mesh = solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,        # Enable iris landmarks for better accuracy
            min_detection_confidence=0.4,  # Lower threshold for bearded / occluded faces
            min_tracking_confidence=0.4,
        )

        class _LegacyWrapper:
            def __init__(self, m):  self._m = m
            def process(self, rgb): return self._m.process(rgb)
            def close(self):        self._m.close()

        return _LegacyWrapper(mesh)

    except AttributeError:
        pass

    # --- New Tasks API path (mediapipe >= 0.10) ---
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python.core.base_options import BaseOptions
    import urllib.request, os, tempfile

    # Download the lite face-landmarker model if not already present
    model_path = os.path.join(tempfile.gettempdir(), "face_landmarker.task")
    if not os.path.exists(model_path):
        url = ("https://storage.googleapis.com/mediapipe-models/"
               "face_landmarker/face_landmarker/float16/1/face_landmarker.task")
        print("[LandmarkTracker] Downloading face_landmarker model …")
        urllib.request.urlretrieve(url, model_path)
        print("[LandmarkTracker] Download complete.")

    options = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        num_faces=1,
        running_mode=vision.RunningMode.IMAGE,
    )
    landmarker = vision.FaceLandmarker.create_from_options(options)

    class _TasksWrapper:
        """Thin shim that makes the Tasks API look like the old FaceMesh."""
        def __init__(self, lm):
            self._lm = lm

        def process(self, rgb):
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            detection = self._lm.detect(mp_image)

            class _Result:
                pass

            r = _Result()
            if detection.face_landmarks:
                r.multi_face_landmarks = detection.face_landmarks
            else:
                r.multi_face_landmarks = None
            return r

        def close(self):
            self._lm.close()

    return _TasksWrapper(landmarker)


# ---------------- Landmark Tracker ----------------
class LandmarkTracker:
    def __init__(self):
        self.mesh = _make_face_mesh()
        self._consecutive_failures = 0
        self._max_failures = 10  # Re-init mesh after N consecutive failures

    def get_landmarks(self, frame) -> list | None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.mesh.process(rgb)
        if not result.multi_face_landmarks:
            self._consecutive_failures += 1
            # Try contrast enhancement for difficult faces
            if self._consecutive_failures >= 3:
                enhanced = self._enhance_frame(rgb)
                result = self.mesh.process(enhanced)
            if not result.multi_face_landmarks:
                if self._consecutive_failures >= self._max_failures:
                    self._reinit()
                return None

        self._consecutive_failures = 0
        landmarks = []
        face = result.multi_face_landmarks[0]
        lm_list = face.landmark if hasattr(face, "landmark") else face
        for lm in lm_list:
            landmarks.append([lm.x, lm.y, getattr(lm, 'z', 0.0)])
        return np.array(landmarks)

    def _enhance_frame(self, rgb_frame):
        """Apply CLAHE histogram equalization to improve detection on
        occluded / bearded faces in variable lighting."""
        lab = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2LAB)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        lab[:, :, 0] = clahe.apply(lab[:, :, 0])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)

    def _reinit(self):
        """Re-init the face mesh after long failure streaks."""
        try:
            self.mesh.close()
        except Exception:
            pass
        self.mesh = _make_face_mesh()
        self._consecutive_failures = 0
        print("[LandmarkTracker] Re-initialized face mesh after detection failures.")

    def __del__(self):
        if hasattr(self, "mesh"):
            self.mesh.close()


# ============================================================================
# ENHANCED FEATURE EXTRACTOR
#
# Uses multiple landmark groups to be robust against facial hair / beards:
#
#   1. Eye Aspect Ratio (EAR) — 6-point per eye, standard formula
#   2. Eyebrow raise — distance from brow to upper-eye boundary
#   3. Mouth openness — OPTIONAL, with reliability weighting
#   4. Head pose — pitch/yaw/roll from nose, chin, eye corners
#   5. Blink rate — counted over a rolling window
#   6. Forehead tension — brow contraction (inner brow distance)
#   7. Jaw clench proxy — chin-to-nose-tip distance variation
#   8. Overall movement — landmark drift between consecutive frames
# ============================================================================

class FeatureExtractor:
    """Multi-signal feature extractor resilient to beard occlusion."""

    # --- 6-point Eye Aspect Ratio landmarks ---
    # Left eye
    L_EYE_OUTER  = 33;   L_EYE_INNER  = 133
    L_EYE_TOP_1  = 159;  L_EYE_TOP_2  = 158
    L_EYE_BOT_1  = 145;  L_EYE_BOT_2  = 153
    # Right eye
    R_EYE_OUTER  = 362;  R_EYE_INNER  = 263
    R_EYE_TOP_1  = 386;  R_EYE_TOP_2  = 385
    R_EYE_BOT_1  = 374;  R_EYE_BOT_2  = 380

    # --- Eyebrow landmarks ---
    L_BROW_INNER = 107;  L_BROW_OUTER = 70;   L_BROW_MID = 105
    R_BROW_INNER = 336;  R_BROW_OUTER = 300;  R_BROW_MID = 334

    # --- Mouth landmarks ---
    MOUTH_TOP     = 13;  MOUTH_BOTTOM  = 14
    MOUTH_LEFT    = 61;  MOUTH_RIGHT   = 291
    LIP_TOP_INNER = 0;   LIP_BOT_INNER = 17

    # --- Head pose landmarks ---
    NOSE_TIP = 1;  CHIN = 152
    L_EYE_CORNER = 33;  R_EYE_CORNER = 263
    L_MOUTH_CORNER = 61; R_MOUTH_CORNER = 291

    # --- Forehead / Inner brow distance for tension ---
    INNER_BROW_L = 107;  INNER_BROW_R = 336

    # --- AU-specific landmarks ---
    # AU6: Cheek raiser — cheek center approximation
    L_CHEEK = 205;  R_CHEEK = 425
    # AU9: Nose wrinkler
    NOSE_BRIDGE = 6
    # AU15: Lip corner depressor uses MOUTH_LEFT(61), LIP_BOT_INNER(17)

    # --- Blink detection ---
    EAR_BLINK_THRESHOLD = 0.21  # Below this = blink; adaptive after calibration

    def __init__(self):
        self._blink_buffer = []       # rolling EAR values
        self._blink_count = 0
        self._blink_cooldown = 0
        self._blink_window = 90       # frames to track blink rate (~3s at 30fps)
        self._blink_events = []       # timestamps of blinks (frame indices)
        self._frame_idx = 0

    def _dist(self, a, b):
        return float(np.linalg.norm(a[:2] - b[:2]))

    def _dist3d(self, a, b):
        return float(np.linalg.norm(a - b))

    # ---- Eye Aspect Ratio (6-point, standard Soukupová–Čech formula) ----
    def _ear_single(self, lm, outer, inner, top1, top2, bot1, bot2):
        horizontal = self._dist(lm[outer], lm[inner])
        if horizontal < 1e-6:
            return 0.3  # safe default
        v1 = self._dist(lm[top1], lm[bot1])
        v2 = self._dist(lm[top2], lm[bot2])
        return (v1 + v2) / (2.0 * horizontal)

    def eye_aspect_ratio(self, lm) -> float:
        """Average EAR across both eyes."""
        left_ear = self._ear_single(
            lm, self.L_EYE_OUTER, self.L_EYE_INNER,
            self.L_EYE_TOP_1, self.L_EYE_TOP_2,
            self.L_EYE_BOT_1, self.L_EYE_BOT_2
        )
        right_ear = self._ear_single(
            lm, self.R_EYE_OUTER, self.R_EYE_INNER,
            self.R_EYE_TOP_1, self.R_EYE_TOP_2,
            self.R_EYE_BOT_1, self.R_EYE_BOT_2
        )
        return (left_ear + right_ear) / 2.0

    # ---- Eyebrow raise (distance from brow to eye, normalized) ----
    def brow_raise(self, lm) -> float:
        """Higher value = eyebrows raised more (surprise / alertness)."""
        l_raise = self._dist(lm[self.L_BROW_MID], lm[self.L_EYE_TOP_1])
        r_raise = self._dist(lm[self.R_BROW_MID], lm[self.R_EYE_TOP_1])
        return (l_raise + r_raise) / 2.0

    # ---- Inner brow contraction (forehead tension / furrowing) ----
    def brow_furrow(self, lm) -> float:
        """Smaller value = brows drawn together = worry / concentration."""
        return self._dist(lm[self.INNER_BROW_L], lm[self.INNER_BROW_R])

    # ---- Mouth Aspect Ratio (with reliability estimate) ----
    def mouth_aspect_ratio(self, lm) -> tuple:
        """Returns (MAR, reliability).
        reliability is 0.0–1.0 indicating how trustworthy the mouth reading is.
        When lower jaw landmarks appear noisy (beard), reliability drops."""
        horizontal = self._dist(lm[self.MOUTH_LEFT], lm[self.MOUTH_RIGHT])
        if horizontal < 1e-6:
            return 0.0, 0.0

        v_outer = self._dist(lm[self.MOUTH_TOP], lm[self.MOUTH_BOTTOM])
        v_inner = self._dist(lm[self.LIP_TOP_INNER], lm[self.LIP_BOT_INNER])
        mar = (v_outer + v_inner) / (2.0 * horizontal)

        # Reliability heuristic: if the outer and inner measurements disagree
        # significantly, the beard is likely occluding landmarks.
        if max(v_outer, v_inner) < 1e-6:
            reliability = 0.2
        else:
            agreement = min(v_outer, v_inner) / max(v_outer, v_inner)
            reliability = min(1.0, agreement * 1.2)  # scale up a bit
            # If MAR is very small AND agreement is low → definitely occluded
            if mar < 0.05 and agreement < 0.5:
                reliability = max(0.1, reliability * 0.5)

        return mar, reliability

    # ---- Head Pose Estimation ----
    def head_pose(self, lm) -> dict:
        """Estimate head pitch, yaw, roll from key landmarks (2D normalized coords)."""
        nose = lm[self.NOSE_TIP][:2]
        chin = lm[self.CHIN][:2]
        l_eye = lm[self.L_EYE_CORNER][:2]
        r_eye = lm[self.R_EYE_CORNER][:2]

        # Yaw: asymmetry of nose relative to eye midpoint
        eye_mid = (l_eye + r_eye) / 2.0
        eye_dist = self._dist(lm[self.L_EYE_CORNER], lm[self.R_EYE_CORNER])
        yaw = (nose[0] - eye_mid[0]) / max(eye_dist, 1e-6)

        # Pitch: nose-chin vertical vs eye line
        face_height = self._dist(lm[self.NOSE_TIP], lm[self.CHIN])
        pitch = (nose[1] - eye_mid[1]) / max(face_height, 1e-6)

        # Roll: angle of eye line
        dx = r_eye[0] - l_eye[0]
        dy = r_eye[1] - l_eye[1]
        roll = float(np.degrees(np.arctan2(dy, dx)))

        return {"pitch": float(pitch), "yaw": float(yaw), "roll": roll}

    # ---- Blink Detection & Rate ----
    def update_blink(self, ear, threshold=None):
        """Track blinks and return blink rate (blinks per minute estimate)."""
        self._frame_idx += 1
        thresh = threshold or self.EAR_BLINK_THRESHOLD

        if self._blink_cooldown > 0:
            self._blink_cooldown -= 1

        if ear < thresh and self._blink_cooldown == 0:
            self._blink_events.append(self._frame_idx)
            self._blink_cooldown = 5  # prevent double-count

        # Remove old events outside window
        cutoff = self._frame_idx - self._blink_window
        self._blink_events = [e for e in self._blink_events if e > cutoff]

        # Blinks per minute (assuming ~30fps)
        window_sec = self._blink_window / 30.0
        bpm = (len(self._blink_events) / window_sec) * 60.0 if window_sec > 0 else 0
        return round(bpm, 1)

    # ---- Movement (weighted: more weight on stable landmarks) ----
    def movement(self, prev, curr) -> float:
        if prev is None:
            return 0.0
        # Use upper-face landmarks (less affected by beard)
        stable_idx = [
            self.NOSE_TIP, self.L_EYE_OUTER, self.R_EYE_OUTER,
            self.L_EYE_INNER, self.R_EYE_INNER,
            self.L_BROW_MID, self.R_BROW_MID, self.CHIN,
        ]
        deltas = []
        for idx in stable_idx:
            if idx < len(prev) and idx < len(curr):
                deltas.append(np.linalg.norm(curr[idx][:2] - prev[idx][:2]))
        return float(np.mean(deltas)) if deltas else 0.0

    # ============================================================
    # FACS Action Unit Calculations (normalized by D_ref)
    # ============================================================

    def _d_ref(self, lm) -> float:
        """Reference distance: outer eye corners (L=33, R=263)."""
        d = self._dist(lm[self.L_EYE_OUTER], lm[self.R_EYE_OUTER])
        return max(d, 1e-6)

    def au1_inner_brow_raiser(self, lm) -> float:
        """AU1: Inner brow raiser — inner brow to inner eye corner distance.
        Higher value = inner brows raised (sadness, surprise)."""
        dref = self._d_ref(lm)
        left  = self._dist(lm[107], lm[133]) / dref
        right = self._dist(lm[336], lm[362]) / dref
        return (left + right) / 2.0

    def au2_outer_brow_raiser(self, lm) -> float:
        """AU2: Outer brow raiser — outer brow to outer eye corner distance.
        Higher value = outer brows raised (surprise)."""
        dref = self._d_ref(lm)
        left  = self._dist(lm[self.L_BROW_OUTER], lm[self.L_EYE_OUTER]) / dref
        right = self._dist(lm[self.R_BROW_OUTER], lm[self.R_EYE_OUTER]) / dref
        return (left + right) / 2.0

    def au4_brow_lowerer(self, lm) -> float:
        """AU4: Brow lowerer / furrow — distance between inner brows normalized.
        Smaller value = higher activation (anger, stress, concentration)."""
        dref = self._d_ref(lm)
        return self._dist(lm[self.INNER_BROW_L], lm[self.INNER_BROW_R]) / dref

    def au5_upper_lid_raiser(self, lm, ear_baseline: float = 0.28) -> float:
        """AU5: Upper lid raiser — EAR significantly above baseline.
        Returns fractional excess above 1.2× baseline (surprise, fear)."""
        ear = self.eye_aspect_ratio(lm)
        threshold = ear_baseline * 1.2
        return max(0.0, (ear - threshold) / max(threshold, 1e-6))

    def au6_cheek_raiser(self, lm) -> float:
        """AU6: Cheek raiser / Duchenne marker — lower eyelid to cheek distance.
        Smaller value = cheeks raised = genuine smile or pain."""
        dref = self._d_ref(lm)
        left  = self._dist(lm[self.L_CHEEK], lm[self.L_EYE_BOT_1]) / dref
        right = self._dist(lm[self.R_CHEEK], lm[self.R_EYE_BOT_1]) / dref
        return (left + right) / 2.0

    def au9_nose_wrinkler(self, lm) -> float:
        """AU9: Nose wrinkler — nose bridge to nose tip distance.
        Smaller value = nose wrinkling (disgust)."""
        dref = self._d_ref(lm)
        return self._dist(lm[self.NOSE_BRIDGE], lm[self.NOSE_TIP]) / dref

    def au12_lip_corner_puller(self, lm) -> float:
        """AU12: Lip corner puller — mouth width normalized.
        Higher value = wider smile (happiness)."""
        dref = self._d_ref(lm)
        return self._dist(lm[self.MOUTH_LEFT], lm[self.MOUTH_RIGHT]) / dref

    def au15_lip_corner_depressor(self, lm) -> float:
        """AU15: Lip corner depressor — Y-axis: mouth corner vs lip bottom center.
        Positive (corner above center) = neutral; negative = sad drooping."""
        # y increases downward in image coords
        # If corner y > lip_bot_center y → corners are lower → sadness
        corner_y = (lm[self.MOUTH_LEFT][1] + lm[self.MOUTH_RIGHT][1]) / 2.0
        center_y = lm[self.LIP_BOT_INNER][1]
        dref = self._d_ref(lm)
        return float(corner_y - center_y) / dref

    def au20_lip_stretcher(self, lm) -> float:
        """AU20: Lip stretcher — wide mouth WITHOUT cheek raising.
        Approximated as AU12 width minus AU6 cheek contribution."""
        return self.au12_lip_corner_puller(lm) - (1.0 - self.au6_cheek_raiser(lm))

    # ---- Master Extract ----
    def extract(self, lm, prev_lm) -> dict:
        ear = self.eye_aspect_ratio(lm)
        mar, mouth_reliability = self.mouth_aspect_ratio(lm)
        brow_r = self.brow_raise(lm)
        brow_f = self.brow_furrow(lm)
        pose = self.head_pose(lm)
        blink_rate = self.update_blink(ear)
        mov = self.movement(prev_lm, lm)

        # FACS Action Units
        au1  = self.au1_inner_brow_raiser(lm)
        au2  = self.au2_outer_brow_raiser(lm)
        au4  = self.au4_brow_lowerer(lm)
        au5  = self.au5_upper_lid_raiser(lm)
        au6  = self.au6_cheek_raiser(lm)
        au9  = self.au9_nose_wrinkler(lm)
        au12 = self.au12_lip_corner_puller(lm)
        au15 = self.au15_lip_corner_depressor(lm)
        au20 = self.au20_lip_stretcher(lm)

        return {
            "eye":               round(ear, 5),
            "mouth":             round(mar, 5),
            "mouth_reliability": round(mouth_reliability, 3),
            "brow_raise":        round(brow_r, 5),
            "brow_furrow":       round(brow_f, 5),
            "blink_rate":        blink_rate,
            "head_pitch":        round(pose["pitch"], 4),
            "head_yaw":          round(pose["yaw"], 4),
            "head_roll":         round(pose["roll"], 2),
            "movement":          round(mov, 5),
            # Action Units (normalized)
            "au1":  round(au1,  5),
            "au2":  round(au2,  5),
            "au4":  round(au4,  5),
            "au5":  round(au5,  5),
            "au6":  round(au6,  5),
            "au9":  round(au9,  5),
            "au12": round(au12, 5),
            "au15": round(au15, 5),
            "au20": round(au20, 5),
        }


# ============================================================================
# ENHANCED EMOTION DETECTOR
#
# Key improvements for bearded / occluded faces:
#   - Mouth features are weighted by their reliability score
#   - Eyebrow raise/furrow used as primary signals alongside EAR
#   - Head pose contributes to anxiety / disengagement detection
#   - Blink rate: low = fatigued/staring, high = anxious
#   - Multi-signal fusion instead of single-threshold rules
# ============================================================================

class EmotionDetector:
    """
    Adaptive multi-signal emotion detector.

    Calibration collects baselines for ALL features so thresholds are
    relative to the individual's resting state (handles beards, distance,
    camera angle automatically).
    """

    BASELINE_FRAMES = 60   # ~2s at 30fps

    # AU keys tracked during calibration
    _AU_KEYS = ["eye", "mouth", "brow_raise", "brow_furrow",
                "blink_rate", "movement", "head_pitch", "head_yaw",
                "au1", "au2", "au4", "au5", "au6",
                "au9", "au12", "au15", "au20"]

    def __init__(self):
        self._cal_buffers = {}
        self._calibrated = False

        # Dynamic baselines (set after calibration)
        # AU values are normalized by D_ref so these are reasonable defaults.
        self.baselines = {
            "eye":        0.28,
            "mouth":      0.05,
            "brow_raise": 0.04,
            "brow_furrow": 0.12,
            "blink_rate": 15.0,
            "movement":   0.02,
            "head_pitch": 0.0,
            "head_yaw":   0.0,
            # FACS AU baselines (resting face)
            "au1":  0.18,   # inner brow-to-eye ratio at rest
            "au2":  0.20,   # outer brow-to-eye ratio at rest
            "au4":  0.28,   # inner-brow gap ratio at rest
            "au5":  0.0,    # lid raiser → 0 at rest
            "au6":  0.30,   # cheek-to-lower-lid ratio at rest
            "au9":  0.18,   # nose bridge-tip ratio at rest
            "au12": 0.44,   # mouth width ratio at rest
            "au15": 0.0,    # lip corner Y-diff at rest (neutral)
            "au20": 0.0,    # lip stretcher at rest
        }

    def _update_calibration(self, features):
        for key in self._AU_KEYS:
            if key not in self._cal_buffers:
                self._cal_buffers[key] = []
            val = features.get(key, 0)
            if key == "movement" and val == 0:
                continue  # skip zero-movement frames
            self._cal_buffers[key].append(val)

        # Check if we have enough samples
        eye_samples = len(self._cal_buffers.get("eye", []))
        if eye_samples >= self.BASELINE_FRAMES:
            for key in self._AU_KEYS:
                buf = self._cal_buffers.get(key, [])
                if buf:
                    self.baselines[key] = float(np.median(buf))
                    if key == "movement":
                        self.baselines[key] = max(self.baselines[key], 0.003)
                    elif key == "mouth":
                        self.baselines[key] = max(self.baselines[key], 0.01)
                    elif key == "au4":
                        self.baselines[key] = max(self.baselines[key], 0.05)

            self._calibrated = True
            parts = "  ".join(f"{k}={v:.4f}" for k, v in self.baselines.items())
            print(f"[EmotionDetector] Calibrated — {parts}")

    def detect(self, features) -> dict:
        """
        FACS-based emotion detection.
        Scores emotions using Facial Action Unit combinations per the FACS standard.
        All AUs are compared relative to the calibrated resting baseline.
        """
        if not self._calibrated:
            self._update_calibration(features)
            return {"emotion": "calibrating", "confidence": 0.0, "signals": {}}

        # ── Pull features ──────────────────────────────────────────────────────
        ear   = features["eye"]
        mar   = features["mouth"]
        mrel  = features.get("mouth_reliability", 0.5)
        blink = features.get("blink_rate", self.baselines["blink_rate"])
        mov   = features["movement"]
        pitch = features.get("head_pitch", 0.0)
        yaw   = features.get("head_yaw", 0.0)

        au1  = features.get("au1",  self.baselines["au1"])
        au2  = features.get("au2",  self.baselines["au2"])
        au4  = features.get("au4",  self.baselines["au4"])
        au5  = features.get("au5",  self.baselines["au5"])
        au6  = features.get("au6",  self.baselines["au6"])
        au9  = features.get("au9",  self.baselines["au9"])
        au12 = features.get("au12", self.baselines["au12"])
        au15 = features.get("au15", self.baselines["au15"])
        au20 = features.get("au20", self.baselines["au20"])

        # ── Baselines ─────────────────────────────────────────────────────────
        b_eye   = max(self.baselines["eye"],   1e-6)
        b_blink = max(self.baselines["blink_rate"], 5.0)
        b_mov   = max(self.baselines["movement"], 1e-6)
        b_au1   = max(self.baselines["au1"],   1e-6)
        b_au2   = max(self.baselines["au2"],   1e-6)
        b_au4   = max(self.baselines["au4"],   1e-6)
        b_au6   = max(self.baselines["au6"],   1e-6)
        b_au9   = max(self.baselines["au9"],   1e-6)
        b_au12  = max(self.baselines["au12"],  1e-6)
        b_au15  = self.baselines["au15"]       # can be negative

        # ── Derived ratios ────────────────────────────────────────────────────
        ear_r     = ear   / b_eye
        blink_r   = blink / b_blink
        mov_r     = mov   / b_mov
        # AU activation deltas vs baseline
        d_au1  = au1  - b_au1           # +ve → inner brow raised
        d_au2  = au2  - b_au2           # +ve → outer brow raised
        d_au4  = b_au4 - au4            # +ve → brows closer (furrowed)
        d_au5  = au5                    # already an excess value
        d_au6  = b_au6 - au6           # +ve → cheeks raised (smaller dist)
        d_au9  = b_au9 - au9           # +ve → nose wrinkling
        d_au12 = au12 - b_au12         # +ve → wider smile
        d_au15 = au15 - b_au15         # +ve → corners drooping

        def _clamp(v): return max(0.0, min(1.0, v))

        scores  = {}
        signals = {}

        # ══════════════════════════════════════════════════════════════════════
        # HAPPY  — AU6 (Cheek Raiser) + AU12 (Lip Corner Puller)
        # Duchenne smile: cheeks must raise (AU6) AND corners pull (AU12)
        # ══════════════════════════════════════════════════════════════════════
        au6_act  = _clamp(d_au6  / max(b_au6  * 0.15, 0.01))   # 15% drop → full
        au12_act = _clamp(d_au12 / max(b_au12 * 0.15, 0.01))   # 15% wider → full
        happy = 0.55 * au6_act + 0.45 * au12_act
        scores["happy"] = _clamp(happy)
        signals["happy"] = f"AU6={au6_act:.2f} AU12={au12_act:.2f}"

        # ══════════════════════════════════════════════════════════════════════
        # SAD  — AU1 + AU4 + AU15
        # Inner brow raises, brows furrow, lip corners drop
        # ══════════════════════════════════════════════════════════════════════
        au1_act  = _clamp(d_au1 / max(b_au1 * 0.20, 0.01))
        au4_act  = _clamp(d_au4 / max(b_au4 * 0.20, 0.01))
        au15_act = _clamp(d_au15 / 0.02) if d_au15 > 0 else 0.0  # 0.02 D_ref drop
        sad = 0.30 * au1_act + 0.35 * au4_act + 0.35 * au15_act
        scores["sad"] = _clamp(sad)
        signals["sad"] = f"AU1={au1_act:.2f} AU4={au4_act:.2f} AU15={au15_act:.2f}"

        # ══════════════════════════════════════════════════════════════════════
        # SURPRISED  — AU1 + AU2 + AU5 + jaw drop (MAR)
        # All brow AUs activate + eyes widen + mouth opens
        # ══════════════════════════════════════════════════════════════════════
        au2_act = _clamp(d_au2 / max(b_au2 * 0.20, 0.01))
        mar_base = max(self.baselines["mouth"], 0.01)
        jaw_act  = _clamp((mar - mar_base * 2.0) / max(mar_base, 0.01)) * mrel
        surprised = 0.25 * au1_act + 0.25 * au2_act + 0.25 * d_au5 + 0.25 * jaw_act
        scores["surprised"] = _clamp(surprised)
        signals["surprised"] = f"AU1={au1_act:.2f} AU2={au2_act:.2f} AU5={d_au5:.2f} jaw={jaw_act:.2f}"

        # ══════════════════════════════════════════════════════════════════════
        # FEAR  — AU1 + AU2 + AU4 + AU5 + AU20
        # Brows rise AND furrow (oblique shape) + eye widen + lips stretch
        # ══════════════════════════════════════════════════════════════════════
        au20_act = _clamp(au20 / max(abs(self.baselines["au20"]) + 0.05, 0.01)) if au20 > 0 else 0.0
        fear = 0.20 * au1_act + 0.20 * au2_act + 0.20 * au4_act + 0.20 * d_au5 + 0.20 * au20_act
        scores["fear"] = _clamp(fear)
        signals["fear"] = f"AU1={au1_act:.2f} AU2={au2_act:.2f} AU4={au4_act:.2f} AU5={d_au5:.2f} AU20={au20_act:.2f}"

        # ══════════════════════════════════════════════════════════════════════
        # ANGRY  — AU4 (strong) + AU5 + blink inhibition
        # Dominant brow furrow + lid raiser (glare) + low blink
        # ══════════════════════════════════════════════════════════════════════
        glare = _clamp(ear_r - 1.0) if ear_r > 1.0 else 0.0   # eyes wide open
        angry = 0.50 * au4_act + 0.30 * glare + 0.20 * _clamp(1.0 - blink_r)
        scores["angry"] = _clamp(angry)
        signals["angry"] = f"AU4={au4_act:.2f} glare={glare:.2f} blink_r={blink_r:.2f}"

        # ══════════════════════════════════════════════════════════════════════
        # DISGUST  — AU9 + AU15
        # Nose wrinkle + lip corner depression
        # ══════════════════════════════════════════════════════════════════════
        au9_act = _clamp(d_au9 / max(b_au9 * 0.15, 0.01))
        disgust = 0.55 * au9_act + 0.45 * au15_act
        scores["disgust"] = _clamp(disgust)
        signals["disgust"] = f"AU9={au9_act:.2f} AU15={au15_act:.2f}"

        # ══════════════════════════════════════════════════════════════════════
        # ANXIOUS/STRESSED  — persistent AU4 + high blink + high movement + AU20
        # ══════════════════════════════════════════════════════════════════════
        anxious = (
            0.30 * au4_act
            + 0.25 * _clamp((blink_r - 1.5) / 1.0)
            + 0.25 * _clamp((mov_r  - 2.0) / 2.0)
            + 0.20 * au20_act
        )
        scores["anxious"] = _clamp(anxious)
        signals["anxious"] = f"AU4={au4_act:.2f} blink_r={blink_r:.2f} mov_r={mov_r:.2f} AU20={au20_act:.2f}"

        # ══════════════════════════════════════════════════════════════════════
        # TIRED  — drooping eyes (low EAR) + low blink + head dip
        # ══════════════════════════════════════════════════════════════════════
        eye_droop  = _clamp((1.0 - ear_r) / 0.25) if ear_r < 1.0 else 0.0
        blink_low  = _clamp((0.6 - blink_r) / 0.6) if blink_r < 0.6 else 0.0
        head_dip   = _clamp((pitch - (self.baselines["head_pitch"] + 0.05)) / 0.10)
        tired = 0.50 * eye_droop + 0.30 * blink_low + 0.20 * head_dip
        scores["tired"] = _clamp(tired)
        signals["tired"] = f"ear_r={ear_r:.2f} blink_r={blink_r:.2f} pitch={pitch:.3f}"

        # ══════════════════════════════════════════════════════════════════════
        # CALM / NEUTRAL  — low AU activation across the board, stable movement
        # ══════════════════════════════════════════════════════════════════════
        max_au_act = max(au1_act, au2_act, au4_act, d_au5, au6_act,
                         au9_act, au12_act, au15_act, au20_act)
        stability  = _clamp(1.0 - mov_r / 3.0)
        blink_norm = _clamp(1.0 - abs(blink_r - 1.0))
        calm = 0.50 * (1.0 - max_au_act) + 0.30 * stability + 0.20 * blink_norm
        scores["calm"] = _clamp(calm)
        signals["calm"] = f"au_max={max_au_act:.2f} mov_r={mov_r:.2f} blink_r={blink_r:.2f}"

        # ── Pick winner ───────────────────────────────────────────────────────
        best = max(scores, key=scores.get)
        conf = scores[best]

        if conf < 0.15:
            best = "calm"
            conf = scores["calm"]

        return {
            "emotion":    best,
            "confidence": round(conf, 3),
            "signals":    signals,
        }


# ============================================================================
# ENHANCED STRESS ANALYZER
# ============================================================================

class StressAnalyzer:
    def __init__(self):
        self.history = []
        self.window = 60   # ~2s smoothing window

    def compute_score(self, features, emotion_result, detector: "EmotionDetector") -> float:
        """
        Score is computed relative to calibrated baselines.
        Uses all available features for a more nuanced stress picture.
        """
        score = 0.0

        ear = features["eye"]
        mov = features["movement"]
        blink = features.get("blink_rate", 15)
        brow_f = features.get("brow_furrow", detector.baselines.get("brow_furrow", 0.12))
        mouth_rel = features.get("mouth_reliability", 0.5)

        base_eye = detector.baselines["eye"]
        base_mov = detector.baselines["movement"]
        base_blink = max(detector.baselines.get("blink_rate", 15), 5.0)
        base_brow_f = detector.baselines.get("brow_furrow", 0.12)

        # Eye: drooping → fatigue/stress; wider open → alert
        ear_ratio = ear / base_eye if base_eye > 0 else 1.0
        if ear_ratio < 0.80:
            score -= 0.25 * (1 - ear_ratio)
        elif ear_ratio > 1.20:
            score += 0.15 * (ear_ratio - 1)

        # Movement: jittery → stress
        mov_ratio = mov / base_mov if base_mov > 0 else 0
        if mov_ratio > 2.0:
            score -= min(0.30, 0.12 * mov_ratio)

        # Blink rate: very high → anxiety/stress, very low → dissociation
        blink_ratio = blink / base_blink if base_blink > 0 else 1.0
        if blink_ratio > 2.0:
            score -= 0.15
        elif blink_ratio < 0.4:
            score -= 0.10

        # Brow furrow: contracted brows → tension
        furrow_ratio = brow_f / base_brow_f if base_brow_f > 0 else 1.0
        if furrow_ratio < 0.85:
            score -= 0.15

        # Emotion modifier
        emotion = emotion_result.get("emotion", "calm")
        emotion_map = {
            "tired":       -0.35,
            "anxious":     -0.45,
            "fear":        -0.55,
            "angry":       -0.50,
            "sad":         -0.40,
            "disgust":     -0.30,
            "surprised":   -0.10,
            "happy":       +0.45,
            "calm":        +0.40,
            "calibrating":  0.00,
        }
        score += emotion_map.get(emotion, 0)

        return max(-1.0, min(1.0, score))

    def update(self, features, emotion_result, detector: "EmotionDetector") -> float:
        score = self.compute_score(features, emotion_result, detector)
        self.history.append(score)
        if len(self.history) > self.window:
            self.history.pop(0)
        return sum(self.history) / len(self.history)


# ============================================================================
# CV PIPELINE
# ============================================================================

class CVPipeline:
    def __init__(self):
        self.tracker        = LandmarkTracker()
        self.extractor      = FeatureExtractor()
        self.emotion        = EmotionDetector()
        self.stress         = StressAnalyzer()
        self.prev_landmarks = None

    def process_frame(self, frame) -> dict | None:
        lm = self.tracker.get_landmarks(frame)
        if lm is None:
            return None

        features = self.extractor.extract(lm, self.prev_landmarks)
        emotion_result = self.emotion.detect(features)
        emotion_str = emotion_result["emotion"]
        stress = self.stress.update(features, emotion_result, self.emotion)

        self.prev_landmarks = lm

        return {
            "emotion":     emotion_str,
            "confidence":  emotion_result.get("confidence", 0),
            "stress":      round(float(stress), 4),
            "eye":         features["eye"],
            "mouth":       features["mouth"],
            "mouth_reliability": features["mouth_reliability"],
            "brow_raise":  features["brow_raise"],
            "brow_furrow": features["brow_furrow"],
            "blink_rate":  features["blink_rate"],
            "head_pitch":  features["head_pitch"],
            "head_yaw":    features["head_yaw"],
            "head_roll":   features["head_roll"],
            "movement":    features["movement"],
            # FACS Action Units
            "au1":  features.get("au1"),
            "au2":  features.get("au2"),
            "au4":  features.get("au4"),
            "au5":  features.get("au5"),
            "au6":  features.get("au6"),
            "au9":  features.get("au9"),
            "au12": features.get("au12"),
            "au15": features.get("au15"),
            "au20": features.get("au20"),
            # Raw landmarks for frontend overlay (numpy array — serialized by API layer)
            "landmarks": lm,
        }

    def __del__(self):
        for attr in ("tracker", "extractor", "emotion", "stress"):
            if hasattr(self, attr):
                delattr(self, attr)


# ============================================================================
# OVERLAY (for standalone testing)
# ============================================================================

def _draw_overlay(frame, result):
    """Draw a semi-transparent HUD on the frame with live stats."""
    h, w = frame.shape[:2]

    stress = result["stress"]
    r = int(min(255, (stress + 1) / 2 * 510))
    g = int(min(255, (1 - (stress + 1) / 2) * 510))
    stress_color = (0, g, r)

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (340, 240), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    font = cv2.FONT_HERSHEY_SIMPLEX
    emotion_label = result['emotion'].upper()
    conf = result.get('confidence', 0)
    if result['emotion'] == "calibrating":
        emotion_label = "CALIBRATING..."
        stress_color = (0, 200, 200)

    lines = [
        (f"Emotion : {emotion_label} ({conf:.0%})",         (1.0, 1.0, 1.0)),
        (f"Stress  : {result['stress']:+.4f}",              stress_color),
        (f"EAR     : {result['eye']:.5f}",                  (0.8, 0.8, 0.8)),
        (f"Mouth   : {result['mouth']:.5f} (R:{result['mouth_reliability']:.1f})", (0.8, 0.8, 0.8)),
        (f"Brow Raise: {result['brow_raise']:.5f}",         (0.8, 0.8, 0.8)),
        (f"Blink/m : {result['blink_rate']:.0f}",           (0.8, 0.8, 0.8)),
        (f"Head P/Y: {result['head_pitch']:.3f}/{result['head_yaw']:.3f}", (0.8, 0.8, 0.8)),
        (f"Movemnt : {result['movement']:.5f}",             (0.8, 0.8, 0.8)),
    ]

    for i, (text, col) in enumerate(lines):
        if isinstance(col, tuple) and isinstance(col[0], float):
            bgr = tuple(int(c * 255) for c in reversed(col))
        else:
            bgr = col
        cv2.putText(frame, text, (10, 24 + i * 26),
                    font, 0.55, bgr, 1, cv2.LINE_AA)

    # Stress bar
    bar_x, bar_y, bar_w, bar_h = 10, 230, 320, 8
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (60, 60, 60), -1)
    fill = int((stress + 1) / 2 * bar_w)
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill, bar_y + bar_h), stress_color, -1)

    cv2.putText(frame, "ESC to quit", (w - 115, h - 10),
                font, 0.45, (160, 160, 160), 1, cv2.LINE_AA)

    return frame


# ============================================================================
# MAIN (standalone testing)
# ============================================================================

if __name__ == "__main__":
    cap      = cv2.VideoCapture(0)
    pipeline = CVPipeline()
    counter  = 0
    last_result = None

    cv2.namedWindow("CV Pipeline", cv2.WINDOW_NORMAL)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[ERROR] Could not read from webcam.")
            break

        result = pipeline.process_frame(frame)
        if result:
            last_result = result
            if counter % 60 == 0:
                print(result)

        if last_result:
            frame = _draw_overlay(frame, last_result)

        cv2.imshow("CV Pipeline", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            print("[INFO] ESC pressed — exiting.")
            break
        if cv2.getWindowProperty("CV Pipeline", cv2.WND_PROP_VISIBLE) < 1:
            break

        counter += 1

    cap.release()
    cv2.destroyAllWindows()