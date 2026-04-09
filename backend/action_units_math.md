# Facial Action Units (FACS) Math & Logic

To improve the accuracy of emotion detection in the CV pipeline, we need to transition from broad heuristic ratios to specific Facial Action Units (AUs) as defined in the Facial Action Coding System (FACS). 

By calculating these individual muscle movements using MediaPipe Face Mesh landmarks, we can build a much more robust and granular emotional profile. Below is the mathematical logic and the key landmarks needed to calculate these AUs.

## 1. Core Measurements (Normalization)
To account for different face sizes and distances from the camera, all distances must be normalized.
*   **Reference Distance ($D_{ref}$)**: The distance between the outer corners of the eyes or the distance from the chin to the nose root.
    *   `L_EYE_OUTER (33)`, `R_EYE_OUTER (263)`
    *   $D_{ref} = \sqrt{(x_{263} - x_{33})^2 + (y_{263} - y_{33})^2}$

---

## 2. Eyebrow Action Units
Eyebrows are critical for distinguishing surprise, sadness, and anger.

### AU1: Inner Brow Raiser (Sadness, Surprise)
*   **Logic**: Distance from the inner eyebrows to the inner eye corners increases.
*   **Landmarks**: `L_BROW_INNER (107)`, `L_EYE_INNER (133)` (and right side equivalent: `336` and `362`).
*   **Math**: 
    $$ AU1_{left} = \frac{\text{dist}(107, 133)}{D_{ref}} $$
    $$ AU1 = \frac{AU1_{left} + AU1_{right}}{2} $$

### AU2: Outer Brow Raiser (Surprise)
*   **Logic**: Distance from the outer eyebrows to the outer eye corners increases.
*   **Landmarks**: `L_BROW_OUTER (70)`, `L_EYE_OUTER (33)`
*   **Math**: 
    $$ AU2_{left} = \frac{\text{dist}(70, 33)}{D_{ref}} $$

### AU4: Brow Lowerer / Furrow (Anger, Concentration, Stress)
*   **Logic**: Distance between the two inner eyebrows decreases (furrowing), and distance from eyebrows to eyes decreases (lowering).
*   **Landmarks**: `L_BROW_INNER (107)`, `R_BROW_INNER (336)`
*   **Math**: 
    $$ AU4_{furrow} = \frac{\text{dist}(107, 336)}{D_{ref}} $$
    *(A smaller value means a higher AU4 activation)*

---

## 3. Eye Action Units
Important for distinguishing between real and fake smiles, as well as fear vs. surprise.

### AU5: Upper Lid Raiser (Surprise, Fear)
*   **Logic**: Distance between the upper eyelid and lower eyelid increases significantly beyond baseline EAR.
*   **Landmarks**: `L_EYE_TOP (159)`, `L_EYE_BOTTOM (145)`
*   **Math**: 
    $$ AU5 = \text{EAR} > \text{EAR}_{baseline} \times 1.2 $$

### AU6: Cheek Raiser / Lid Compressor (True Smile, Pain)
*   **Logic**: The cheeks raise, pushing up the lower eyelid, decreasing the distance between the lower eyelid and the cheek center. This causes the eye to squint slightly (Duchenne marker).
*   **Landmarks**: `L_CHEEK (205)`, `L_EYE_BOTTOM (145)`
*   **Math**:
    $$ AU6_{left} = \frac{\text{dist}(205, 145)}{D_{ref}} $$
    *(A smaller value indicates cheek raising)*

---

## 4. Mouth & Lip Action Units
Critical for happiness, sadness, disgust, and fear.

### AU12: Lip Corner Puller (Happiness / Smile)
*   **Logic**: The corners of the mouth move outwards and upwards. Distance between the mouth corners increases, and distance from mouth corner to eye decreases.
*   **Landmarks**: `L_MOUTH_CORNER (61)`, `R_MOUTH_CORNER (291)`
*   **Math**: 
    $$ AU12_{width} = \frac{\text{dist}(61, 291)}{D_{ref}} $$
    *(A value significantly larger than baseline indicates a smile)*

### AU15: Lip Corner Depressor (Sadness, Disappointment)
*   **Logic**: The corners of the mouth move downwards relative to the center of the lip.
*   **Landmarks**: `MOUTH_CORNER (61)`, `LIP_BOT_CENTER (17)`
*   **Math**:
    Calculate the Y-axis difference: 
    $$ AU15 = (y_{61} - y_{17}) $$
    *(If mouth corners drop below the center lower lip, AU15 is active)*

### AU20: Lip Stretcher (Fear, Panic)
*   **Logic**: The mouth is stretched horizontally but not pulled upwards like a smile. 
*   **Math**: High mouth width (like AU12) but WITHOUT the upward cheek movement (no AU6) and NO upward corner movement.

### AU9: Nose Wrinkler (Disgust)
*   **Logic**: The skin along the bridge of the nose wrinkles, pulling the inner cheeks up. Distance between the top of the nose and the inner corners of the eyes changes.
*   **Landmarks**: `NOSE_BRIDGE (6)`, `NOSE_TIP (1)`
*   **Math**: 
    $$ AU9 = \frac{\text{dist}(6, 1)}{D_{ref}} $$
    *(A smaller distance indicates nose wrinkling)*

---

## Emotion Classification based on AUs
Once AUs are calculated relative to a user's resting baseline, emotions can be mapped much more accurately using FACS rules:

*   **Happy**: AU6 (Cheek Raiser) + AU12 (Lip Corner Puller)
*   **Sad**: AU1 (Inner Brow Raiser) + AU4 (Brow Lowerer) + AU15 (Lip Corner Depressor)
*   **Surprised**: AU1 + AU2 (Outer Brow Raiser) + AU5 (Upper Lid Raiser) + AU26 (Jaw Drop)
*   **Fear**: AU1 + AU2 + AU4 + AU5 + AU20 (Lip Stretcher)
*   **Angry**: AU4 (Brow Lowerer) + AU5 (Upper Lid Raiser) + AU7 (Lid Tightener) + AU23 (Lip Tightener)
*   **Disgust**: AU9 (Nose Wrinkler) + AU15 (Lip Corner Depressor)
*   **Anxiety/Stress**: Constant shifting, high baseline AU4 (Furrow), high Blink Rate, low-intensity AU20.

## Implementation Next Steps
1. Update `FeatureExtractor` in `cv_pipeline.py` to calculate these specific AUs using normalization ($D_{ref}$).
2. Update the `EmotionDetector.baselines` to track the resting state of these AUs during the calibration phase.
3. Replace the heuristic `detect` method with a rule-engine that scores emotions based on combinations of these AUs.
