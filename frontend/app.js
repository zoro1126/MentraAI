/**
 * app.js — MentraAI Frontend Application Logic
 *
 * Handles all 5 screens:
 *   1. Login / Sign Up
 *   2. User Details (Profile)
 *   3. PHQ-9 Questionnaire
 *   4. AI Video Call / CV Analysis + STT/TTS Interview
 *   5. Personal Plan / AI Advice
 *
 * Integrates with the Flask backend API.
 * Uses Web Speech API for STT (SpeechRecognition) and TTS (SpeechSynthesis).
 */

// ============================================================
// CONFIG
// ============================================================
const API_BASE = '';  // Same origin — served by Flask

// ============================================================
// STATE
// ============================================================
const state = {
    userId: null,
    token: null,
    userName: '',
    profile: {},
    phq9Answers: new Array(9).fill(null),
    phq9Result: null,
    cvData: null,       // Latest CV analysis result
    cvHistory: [],      // Rolling history of CV results
    plan: null,
    cameraStream: null,
    cvInterval: null,
    landmarksVisible: false,   // Landmark overlay toggle
    lastLandmarks: null,       // Most recent landmark array from CV

    // Interview state
    interviewQuestions: [],      // Loaded from backend
    interviewFlat: [],           // Flattened question list
    interviewCurrentIdx: 0,
    interviewActive: false,
    interviewCompleted: false,
    interviewResolve: null,      // Resolve fn for waiting on user text submit
};

// ============================================================
// UTILITY FUNCTIONS
// ============================================================

/** Navigate to a screen by ID */
function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    const target = document.getElementById(screenId);
    if (target) {
        target.classList.add('active');
        // Re-trigger animations
        target.querySelectorAll('.fade-in-up').forEach(el => {
            el.style.animation = 'none';
            void el.offsetHeight;
            el.style.animation = '';
        });
    }
}

/** Show toast notification */
function showToast(message, duration = 3000) {
    const toast = document.getElementById('toast');
    const msgEl = document.getElementById('toast-message');
    msgEl.textContent = message;
    toast.classList.remove('hidden');
    void toast.offsetHeight;
    toast.classList.add('show');

    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.classList.add('hidden'), 300);
    }, duration);
}

/** Show / hide loading overlay */
function showLoading(text = 'Loading…') {
    const overlay = document.getElementById('loading-overlay');
    document.getElementById('loading-text').textContent = text;
    overlay.classList.remove('hidden');
}

function hideLoading() {
    document.getElementById('loading-overlay').classList.add('hidden');
}

/** API helper */
async function api(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const config = {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    };
    if (options.body && typeof options.body === 'object') {
        config.body = JSON.stringify(options.body);
    }
    const res = await fetch(url, config);
    const data = await res.json();
    return { ok: res.ok, status: res.status, data };
}


// ============================================================
// 1. LOGIN / SIGN UP
// ============================================================

document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    const errorEl = document.getElementById('login-error');

    errorEl.classList.add('hidden');

    if (!email || !password) {
        errorEl.textContent = 'Please fill in all fields.';
        errorEl.classList.remove('hidden');
        return;
    }

    showLoading('Signing in…');
    try {
        const { ok, data } = await api('/api/login', {
            method: 'POST',
            body: { email, password },
        });

        if (ok && data.success) {
            state.userId = data.user_id;
            state.token = data.token;
            state.userName = data.name;
            hideLoading();
            showToast(`Welcome back, ${data.name}!`);
            showScreen('screen-profile');
        } else {
            hideLoading();
            errorEl.textContent = data.error || 'Login failed.';
            errorEl.classList.remove('hidden');
        }
    } catch (err) {
        hideLoading();
        errorEl.textContent = 'Network error. Is the server running?';
        errorEl.classList.remove('hidden');
    }
});

// Show signup modal
document.getElementById('show-signup').addEventListener('click', () => {
    document.getElementById('signup-modal').classList.remove('hidden');
});

document.getElementById('close-signup').addEventListener('click', () => {
    document.getElementById('signup-modal').classList.add('hidden');
});

document.getElementById('signup-modal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) {
        e.currentTarget.classList.add('hidden');
    }
});

document.getElementById('signup-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('signup-name').value.trim();
    const email = document.getElementById('signup-email').value.trim();
    const password = document.getElementById('signup-password').value;
    const errorEl = document.getElementById('signup-error');

    errorEl.classList.add('hidden');

    showLoading('Creating account…');
    try {
        const { ok, data } = await api('/api/signup', {
            method: 'POST',
            body: { name, email, password },
        });

        if (ok && data.success) {
            state.userId = data.user_id;
            state.token = data.token;
            state.userName = data.name;
            hideLoading();
            document.getElementById('signup-modal').classList.add('hidden');
            showToast(`Account created! Welcome, ${data.name}`);
            showScreen('screen-profile');
        } else {
            hideLoading();
            errorEl.textContent = data.error || 'Sign up failed.';
            errorEl.classList.remove('hidden');
        }
    } catch (err) {
        hideLoading();
        errorEl.textContent = 'Network error. Is the server running?';
        errorEl.classList.remove('hidden');
    }
});


// ============================================================
// 2. USER PROFILE
// ============================================================

document.getElementById('profile-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const profile = {
        user_id: state.userId || 'anonymous',
        first_name: document.getElementById('profile-first-name').value.trim(),
        last_name: document.getElementById('profile-last-name').value.trim(),
        age: document.getElementById('profile-age').value,
        occupation: document.getElementById('profile-occupation').value.trim(),
        profession: document.getElementById('profile-profession').value.trim(),
        hobbies: document.getElementById('profile-hobbies').value.trim(),
        country: document.getElementById('profile-country').value.trim(),
        state: document.getElementById('profile-state').value.trim(),
        city: document.getElementById('profile-city').value.trim(),
    };

    showLoading('Saving profile…');
    try {
        const { ok, data } = await api('/api/profile', {
            method: 'POST',
            body: profile,
        });

        if (ok && data.success) {
            state.profile = data.profile;
            hideLoading();
            showToast('Profile saved!');
            loadPHQ9Questions();
            showScreen('screen-phq9');
        } else {
            hideLoading();
            showToast('Failed to save profile.');
        }
    } catch (err) {
        hideLoading();
        showToast('Network error.');
    }
});


// ============================================================
// 3. PHQ-9 QUESTIONNAIRE
// ============================================================

async function loadPHQ9Questions() {
    try {
        const { ok, data } = await api('/api/phq9/questions');
        if (!ok) return;

        const container = document.getElementById('phq9-questions-container');
        container.innerHTML = '';

        data.questions.forEach((question, qi) => {
            const div = document.createElement('div');
            div.className = 'phq9-question';
            div.innerHTML = `
                <div class="q-label">
                    <span class="q-num">Q${qi + 1}.</span>
                    <span>${question}</span>
                </div>
                <div class="phq9-options">
                    ${data.options.map((opt, oi) => `
                        <div class="phq9-option">
                            <input type="radio" name="phq9_q${qi}" id="phq9_q${qi}_o${oi}" value="${oi}">
                            <label for="phq9_q${qi}_o${oi}">${opt}</label>
                        </div>
                    `).join('')}
                </div>
            `;
            container.appendChild(div);
        });

        container.addEventListener('change', updatePHQ9Progress);
    } catch (err) {
        console.error('Failed to load PHQ-9 questions:', err);
    }
}

function updatePHQ9Progress() {
    let answered = 0;
    for (let i = 0; i < 9; i++) {
        const selected = document.querySelector(`input[name="phq9_q${i}"]:checked`);
        if (selected) {
            state.phq9Answers[i] = parseInt(selected.value, 10);
            answered++;
        }
    }

    const pct = (answered / 9) * 100;
    document.querySelector('.progress-bar-fill').style.width = `${pct}%`;
    document.querySelector('.progress-label').textContent = `${answered} / 9`;

    const submitBtn = document.getElementById('phq9-submit-btn');
    submitBtn.disabled = answered < 9;
}

document.getElementById('phq9-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    if (state.phq9Answers.some(a => a === null)) {
        showToast('Please answer all questions.');
        return;
    }

    showLoading('Analyzing your responses…');
    try {
        const { ok, data } = await api('/api/phq9/submit', {
            method: 'POST',
            body: {
                user_id: state.userId || 'anonymous',
                answers: state.phq9Answers,
            },
        });

        if (ok && data.success) {
            state.phq9Result = data;
            hideLoading();
            showToast(`Assessment complete: ${data.severity} (${data.total_score}/27)`);
            // Load interview questions before navigating
            loadInterviewQuestions();
            showScreen('screen-video');
        } else {
            hideLoading();
            showToast(data.error || 'Failed to submit assessment.');
        }
    } catch (err) {
        hideLoading();
        showToast('Network error.');
    }
});


// ============================================================
// 4. AI VIDEO CALL / CV ANALYSIS
// ============================================================

const webcamVideo = document.getElementById('webcam-video');
const webcamCanvas = document.getElementById('webcam-canvas');
const canvasCtx = webcamCanvas.getContext('2d');

document.getElementById('start-camera-btn').addEventListener('click', startCamera);
document.getElementById('stop-camera-btn').addEventListener('click', stopCamera);

async function startCamera() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: { width: 640, height: 480, facingMode: 'user' },
            audio: false,
        });
        state.cameraStream = stream;
        webcamVideo.srcObject = stream;

        document.getElementById('video-placeholder').classList.add('hidden');
        document.getElementById('start-camera-btn').classList.add('hidden');
        document.getElementById('stop-camera-btn').classList.remove('hidden');
        document.getElementById('toggle-landmarks-btn').classList.remove('hidden');
        document.getElementById('cv-status').textContent = 'Analyzing — please look at the camera';

        addTranscriptEntry('📹 Camera started. Beginning emotion and stress analysis…');

        // Start sending frames to backend
        state.cvInterval = setInterval(captureAndAnalyze, 1000);
    } catch (err) {
        showToast('Could not access camera. Please allow camera permission.');
        console.error('Camera error:', err);
    }
}

function stopCamera() {
    if (state.cameraStream) {
        state.cameraStream.getTracks().forEach(t => t.stop());
        state.cameraStream = null;
    }
    if (state.cvInterval) {
        clearInterval(state.cvInterval);
        state.cvInterval = null;
    }

    // Hide landmark overlay
    state.landmarksVisible = false;
    document.getElementById('landmark-overlay').classList.add('hidden');
    document.getElementById('toggle-landmarks-btn').classList.add('hidden');
    document.getElementById('landmark-btn-label').textContent = 'Show Landmarks';

    webcamVideo.srcObject = null;
    document.getElementById('video-placeholder').classList.remove('hidden');
    document.getElementById('start-camera-btn').classList.remove('hidden');
    document.getElementById('stop-camera-btn').classList.add('hidden');
    document.getElementById('cv-status').textContent = 'Camera stopped';

    addTranscriptEntry('📹 Camera stopped. Analysis paused.');
}

// ---- Landmark Overlay ----
const landmarkOverlay = document.getElementById('landmark-overlay');
const landmarkCtx = landmarkOverlay.getContext('2d');

document.getElementById('toggle-landmarks-btn').addEventListener('click', () => {
    state.landmarksVisible = !state.landmarksVisible;
    const label = document.getElementById('landmark-btn-label');
    if (state.landmarksVisible) {
        landmarkOverlay.classList.remove('hidden');
        label.textContent = 'Hide Landmarks';
        // Sync canvas size to wrapper
        const wrapper = landmarkOverlay.parentElement;
        landmarkOverlay.width  = wrapper.offsetWidth;
        landmarkOverlay.height = wrapper.offsetHeight;
    } else {
        landmarkOverlay.classList.add('hidden');
        label.textContent = 'Show Landmarks';
    }
});

function drawLandmarkOverlay(landmarks) {
    const w = landmarkOverlay.width;
    const h = landmarkOverlay.height;
    landmarkCtx.clearRect(0, 0, w, h);

    if (!landmarks || landmarks.length === 0) return;

    // Key AU landmark indices to highlight
    const keyPoints = [
        33, 133, 159, 145, 362, 263, 386, 374,  // eyes
        107, 70, 105, 336, 300, 334,             // brows
        61, 291, 13, 14, 17, 0,                  // mouth
        1, 152, 6, 205, 425,                     // nose, chin, cheeks
    ];

    // Draw all landmarks as tiny dots (mirrored x to match video)
    for (const lm of landmarks) {
        const x = (1 - lm[0]) * w;  // mirror horizontally
        const y = lm[1] * h;
        landmarkCtx.beginPath();
        landmarkCtx.arc(x, y, 1.2, 0, Math.PI * 2);
        landmarkCtx.fillStyle = 'rgba(99,102,241,0.5)';
        landmarkCtx.fill();
    }

    // Highlight key AU points in bright colours
    const highlight = [
        { idx: 33,  color: '#4ade80' }, { idx: 263, color: '#4ade80' },
        { idx: 107, color: '#facc15' }, { idx: 336, color: '#facc15' },
        { idx: 70,  color: '#a855f7' }, { idx: 300, color: '#a855f7' },
        { idx: 61,  color: '#f87171' }, { idx: 291, color: '#f87171' },
        { idx: 1,   color: '#38bdf8' }, { idx: 205, color: '#fb923c' },
        { idx: 425, color: '#fb923c' },
    ];
    for (const { idx, color } of highlight) {
        if (idx >= landmarks.length) continue;
        const lm = landmarks[idx];
        const x = (1 - lm[0]) * w;
        const y = lm[1] * h;
        landmarkCtx.beginPath();
        landmarkCtx.arc(x, y, 3.5, 0, Math.PI * 2);
        landmarkCtx.fillStyle = color;
        landmarkCtx.shadowColor = color;
        landmarkCtx.shadowBlur = 6;
        landmarkCtx.fill();
        landmarkCtx.shadowBlur = 0;
    }
}

async function captureAndAnalyze() {
    if (!state.cameraStream) return;

    webcamCanvas.width = 640;
    webcamCanvas.height = 480;
    canvasCtx.drawImage(webcamVideo, 0, 0, 640, 480);

    const dataUrl = webcamCanvas.toDataURL('image/jpeg', 0.7);
    const base64 = dataUrl.split(',')[1];

    try {
        const { ok, data } = await api('/api/cv/analyze_frame', {
            method: 'POST',
            body: { frame: base64 },
        });

        if (ok && data.success && data.detected) {
            state.cvData = data;
            state.cvHistory.push(data);
            if (state.cvHistory.length > 60) state.cvHistory.shift();

            updateCVIndicators(data);
        } else if (ok && data.success && !data.detected) {
            document.getElementById('cv-status').textContent = 'No face detected — please look at the camera';
        }
    } catch (err) {
        console.error('CV analysis error:', err);
    }
}

function updateCVIndicators(data) {
    // Behavior label (from LightGBM model) — preferred over legacy emotion
    const behaviorEl = document.getElementById('cv-emotion');
    const label = data.behavior || data.emotion || '—';
    behaviorEl.textContent = label;

    const behaviorColors = {
        'engaged':             '#4ade80',
        'positive_engagement': '#4ade80',
        'disengaged':          '#94a3b8',
        'low_energy':          '#facc15',
        'withdrawn':           '#3b82f6',
        'cognitive_load':      '#a855f7',
        'tense':               '#fb923c',
        'agitated':            '#ef4444',
        'overaroused':         '#f87171',
        'ambiguous':           '#64748b',
        'calibrating':         '#facc15',
        'unavailable':         '#64748b',
    };
    behaviorEl.style.color = behaviorColors[label] || '#a0a0cc';

    // Confidence
    const confEl = document.getElementById('cv-confidence');
    if (data.confidence !== undefined) {
        confEl.textContent = `${(data.confidence * 100).toFixed(0)}%`;
    } else {
        confEl.textContent = '—';
    }

    // Stress bar (range -1 to +1 mapped to 0-100%)
    const stressPercent = ((data.stress + 1) / 2) * 100;
    const stressBar = document.getElementById('cv-stress-bar');
    stressBar.style.width = `${stressPercent}%`;
    const sr = Math.round(Math.min(255, (data.stress + 1) / 2 * 510));
    const sg = Math.round(Math.min(255, (1 - (data.stress + 1) / 2) * 510));
    stressBar.style.background = `rgb(${sr},${sg},80)`;
    document.getElementById('cv-stress-value').textContent = data.stress.toFixed(4);

    // EAR
    document.getElementById('cv-eye').textContent = data.eye !== undefined ? data.eye.toFixed(4) : '—';

    // Blink rate
    document.getElementById('cv-blink').textContent = data.blink_rate !== undefined ? `${data.blink_rate.toFixed(0)}/min` : '—';

    // Mouth
    document.getElementById('cv-mouth').textContent = data.mouth !== undefined ? data.mouth.toFixed(4) : '—';
    const mouthRelEl = document.getElementById('cv-mouth-rel');
    if (data.mouth_reliability !== undefined) {
        mouthRelEl.textContent = `(R:${data.mouth_reliability.toFixed(1)})`;
        mouthRelEl.style.color = data.mouth_reliability > 0.6 ? '#4ade80' : data.mouth_reliability > 0.3 ? '#facc15' : '#ef4444';
    }

    // Head pose
    const headEl = document.getElementById('cv-head-pose');
    if (data.head_pitch !== undefined) {
        headEl.textContent = `P:${data.head_pitch.toFixed(2)} Y:${data.head_yaw.toFixed(2)}`;
    }

    // FACS Action Unit bars
    const auDefs = [
        { id: 'au1',  val: data.au1,  range: [0.1, 0.35] },
        { id: 'au2',  val: data.au2,  range: [0.1, 0.40] },
        { id: 'au4',  val: data.au4,  range: [0.05, 0.35] },
        { id: 'au5',  val: data.au5,  range: [0.0,  0.30] },
        { id: 'au6',  val: data.au6,  range: [0.15, 0.45] },
        { id: 'au9',  val: data.au9,  range: [0.10, 0.30] },
        { id: 'au12', val: data.au12, range: [0.30, 0.60] },
        { id: 'au15', val: data.au15, range: [-0.05, 0.05] },
    ];
    for (const { id, val, range } of auDefs) {
        if (val === undefined) continue;
        const pct = Math.max(0, Math.min(100, ((val - range[0]) / (range[1] - range[0])) * 100));
        const barEl = document.getElementById(`${id}-bar`);
        const valEl = document.getElementById(`${id}-val`);
        if (barEl) barEl.style.width = `${pct}%`;
        if (valEl) valEl.textContent = val.toFixed(3);
    }

    // Landmark overlay
    if (data.landmarks && state.landmarksVisible) {
        state.lastLandmarks = data.landmarks;
        drawLandmarkOverlay(data.landmarks);
    }

    // Status line — show behavior
    const statusEl = document.getElementById('cv-status');
    if (label === 'calibrating') {
        statusEl.textContent = 'Calibrating — hold still (30 frames needed)…';
    } else {
        const conf = data.confidence !== undefined ? ` (${(data.confidence*100).toFixed(0)}%)` : '';
        statusEl.textContent = `Behavior: ${label}${conf} | Stress: ${data.stress > 0 ? '+' : ''}${data.stress.toFixed(2)}`;
    }
}

function addTranscriptEntry(text, type = 'system') {
    const container = document.getElementById('speech-transcript');
    const placeholder = container.querySelector('.placeholder-text');
    if (placeholder) placeholder.remove();

    const p = document.createElement('p');
    const time = new Date().toLocaleTimeString();

    if (type === 'ai') {
        p.innerHTML = `<span style="color: var(--accent-purple); font-size: 0.78rem;">[${time}] 🤖 AI:</span> ${text}`;
    } else if (type === 'user') {
        p.innerHTML = `<span style="color: var(--accent-green); font-size: 0.78rem;">[${time}] 🗣️ You:</span> <em>${text}</em>`;
    } else {
        p.innerHTML = `<span style="color: var(--text-muted); font-size: 0.78rem;">[${time}]</span> ${text}`;
    }

    p.style.marginBottom = '8px';
    p.style.animation = 'fadeIn 0.3s ease';
    container.appendChild(p);
    container.scrollTop = container.scrollHeight;
}


// ============================================================
// TEXT-INPUT INTERVIEW SYSTEM
// ============================================================

/**
 * Load interview questions from backend and flatten into a sequential list.
 */
async function loadInterviewQuestions() {
    try {
        const { ok, data } = await api('/api/interview/questions');
        if (ok && data.success) {
            state.interviewQuestions = data.questions;
            state.interviewFlat = [];
            data.questions.forEach((cat) => {
                cat.questions.forEach((q) => {
                    state.interviewFlat.push({
                        category:    cat.category,
                        icon:        cat.icon,
                        color:       cat.color,
                        purpose:     cat.purpose,
                        question:    q,
                        critical:    cat.critical || false,
                        risk_check:  cat.risk_check || false,
                        categoryId:  cat.id,
                    });
                });
            });
            console.log(`[Interview] ${state.interviewFlat.length} questions loaded.`);
        }
    } catch (err) {
        console.error('Failed to load interview questions:', err);
    }
}

/**
 * Wait for the user to submit or skip the current question.
 * Returns a Promise that resolves with the typed text (or '' for skip).
 */
function waitForUserInput() {
    return new Promise((resolve) => {
        state.interviewResolve = resolve;
    });
}

/**
 * Update the interview UI for the current question item.
 */
function updateInterviewUI(item, idx, total) {
    const pct = ((idx + 1) / total) * 100;
    document.getElementById('interview-progress-fill').style.width = `${pct}%`;
    document.getElementById('interview-progress-label').textContent = `${idx + 1} / ${total} questions`;

    const catEl = document.getElementById('interview-category');
    catEl.classList.remove('hidden');
    document.getElementById('interview-category-icon').textContent = item.icon;
    document.getElementById('interview-category-name').textContent = item.category;
    document.getElementById('interview-category-name').style.color = item.color;
    document.getElementById('interview-category-purpose').textContent = item.purpose;

    document.getElementById('interview-current-question').textContent = item.question;

    // Show and clear the text input
    const preview = document.getElementById('interview-response-preview');
    preview.classList.remove('hidden');
    const input = document.getElementById('interview-text-input');
    input.value = '';
    input.focus();
}

/**
 * Save a response to the backend.
 */
async function saveInterviewResponse(item, response) {
    try {
        await api('/api/interview/save_response', {
            method: 'POST',
            body: {
                user_id:     state.userId || 'anonymous',
                category:    item.category,
                question:    item.question,
                response:    response,
                question_id: item.categoryId,
                cv_snapshot: state.cvData ? {
                    behavior:   state.cvData.behavior,
                    emotion:    state.cvData.emotion,
                    stress:     state.cvData.stress,
                    confidence: state.cvData.confidence,
                    blink_rate: state.cvData.blink_rate,
                } : null,
            },
        });
    } catch (err) {
        console.error('Failed to save interview response:', err);
    }
}

/**
 * Run the full interview loop (text-input version).
 */
async function runInterview() {
    if (state.interviewFlat.length === 0) {
        showToast('No interview questions loaded.');
        return;
    }

    state.interviewActive = true;
    state.interviewCurrentIdx = 0;

    document.getElementById('start-interview-btn').classList.add('hidden');
    document.getElementById('done-question-btn').classList.remove('hidden');
    document.getElementById('skip-question-btn').classList.remove('hidden');

    addTranscriptEntry('💬 Interview started. Read each question and type your response, then click Submit.', 'system');

    for (let i = 0; i < state.interviewFlat.length; i++) {
        if (!state.interviewActive) break;

        state.interviewCurrentIdx = i;
        const item = state.interviewFlat[i];

        updateInterviewUI(item, i, state.interviewFlat.length);
        addTranscriptEntry(`${item.icon} [${item.category}] ${item.question}`, 'ai');

        // Wait until user clicks Submit or Skip
        const response = await waitForUserInput();

        if (!state.interviewActive) break;

        if (response) {
            addTranscriptEntry(response, 'user');
            await saveInterviewResponse(item, response);
        } else {
            addTranscriptEntry('(skipped)', 'user');
            await saveInterviewResponse(item, '(no response)');
        }

        await sleep(300);
    }

    // Done
    state.interviewActive   = false;
    state.interviewCompleted = true;

    document.getElementById('start-interview-btn').classList.remove('hidden');
    document.getElementById('start-interview-btn').querySelector('span').textContent = 'Restart Interview';
    document.getElementById('done-question-btn').classList.add('hidden');
    document.getElementById('skip-question-btn').classList.add('hidden');
    document.getElementById('interview-response-preview').classList.add('hidden');
    document.getElementById('interview-current-question').textContent = '✅ Interview complete! Click "Generate Personal Plan" to see your results.';

    addTranscriptEntry('✅ Interview completed. All responses recorded.', 'system');
    showToast('Interview complete! Generate your personalised plan now.');
}

/** Helper: sleep */
function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}


// ============================================================
// INTERVIEW BUTTON HANDLERS
// ============================================================

document.getElementById('start-interview-btn').addEventListener('click', () => {
    if (state.interviewActive) {
        // Stop the interview
        state.interviewActive = false;
        // Resolve any pending wait so the loop exits
        if (state.interviewResolve) {
            state.interviewResolve('');
            state.interviewResolve = null;
        }
        document.getElementById('start-interview-btn').querySelector('span').textContent = 'Start Interview';
        document.getElementById('done-question-btn').classList.add('hidden');
        document.getElementById('skip-question-btn').classList.add('hidden');
        document.getElementById('interview-response-preview').classList.add('hidden');
        addTranscriptEntry('⏹️ Interview paused by user.', 'system');
        showToast('Interview paused.');
    } else {
        runInterview();
    }
});

// Submit button — collect text and resolve the waiting promise
document.getElementById('done-question-btn').addEventListener('click', () => {
    if (!state.interviewResolve) return;
    const input = document.getElementById('interview-text-input');
    const text  = (input ? input.value : '').trim();
    const resolve = state.interviewResolve;
    state.interviewResolve = null;
    resolve(text || '');
    showToast('Response recorded — next question…');
});

// Skip button — resolve with empty string
document.getElementById('skip-question-btn').addEventListener('click', () => {
    if (!state.interviewResolve) return;
    const resolve = state.interviewResolve;
    state.interviewResolve = null;
    resolve('');
    showToast('Question skipped…');
});

// Allow pressing Enter+Ctrl / Cmd+Enter to submit from textarea
document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && state.interviewActive && state.interviewResolve) {
        document.getElementById('done-question-btn').click();
    }
});


// ============================================================
// GENERATE PLAN BUTTON
// ============================================================

document.getElementById('generate-plan-btn').addEventListener('click', async () => {
    // Stop camera if running
    stopCamera();

    // Stop interview if running
    if (state.interviewActive) {
        state.interviewActive = false;
        if (state.interviewResolve) {
            state.interviewResolve('');
            state.interviewResolve = null;
        }
    }

    // Compute average CV data from history
    let avgCvData = null;
    if (state.cvHistory.length > 0) {
        const validEntries = state.cvHistory.filter(d => d.emotion !== 'calibrating');
        if (validEntries.length > 0) {
            const avgStress = validEntries.reduce((s, d) => s + d.stress, 0) / validEntries.length;
            const avgBlink  = validEntries.reduce((s, d) => s + (d.blink_rate || 0), 0) / validEntries.length;
            const avgConf   = validEntries.reduce((s, d) => s + (d.confidence || 0), 0) / validEntries.length;

            // Most common behavior label
            const behaviorCounts = {};
            validEntries.forEach(d => {
                const lbl = d.behavior || d.emotion || 'ambiguous';
                behaviorCounts[lbl] = (behaviorCounts[lbl] || 0) + 1;
            });
            const dominantBehavior = Object.entries(behaviorCounts).sort((a, b) => b[1] - a[1])[0][0];

            avgCvData = {
                behavior:   dominantBehavior,
                emotion:    dominantBehavior,   // backward compat
                stress:     avgStress,
                blink_rate: avgBlink,
                confidence: avgConf,
            };
        }
    }

    showLoading('Generating your personal plan…');
    try {
        const { ok, data } = await api('/api/plan/generate', {
            method: 'POST',
            body: {
                user_id: state.userId || 'anonymous',
                cv_data: avgCvData,
            },
        });

        if (ok && data.success) {
            state.plan = data;
            hideLoading();
            renderPlan(data);
            showScreen('screen-plan');
            showToast('Your personal plan is ready!');
        } else {
            hideLoading();
            showToast('Failed to generate plan.');
        }
    } catch (err) {
        hideLoading();
        showToast('Network error.');
    }
});


// ============================================================
// 5. PERSONAL PLAN RENDERING
// ============================================================

function renderPlan(plan) {
    // Profile summary
    document.getElementById('plan-profile-summary').textContent = plan.profile_summary || '—';

    // Stress level badge
    const badge = document.getElementById('plan-stress-level');
    badge.textContent = plan.stress_level || '—';
    const severityColors = {
        'Minimal': '#4ade80',
        'Mild': '#facc15',
        'Moderate': '#fb923c',
        'Moderately Severe': '#f87171',
        'Severe': '#ef4444',
    };
    const badgeColor = severityColors[plan.stress_level] || '#6366f1';
    badge.style.background = `${badgeColor}22`;
    badge.style.color = badgeColor;
    badge.style.borderColor = badgeColor;

    // Stress insights
    const insightsList = document.getElementById('plan-stress-insights');
    insightsList.innerHTML = '';
    (plan.stress_insights || []).forEach(insight => {
        const li = document.createElement('li');
        li.textContent = insight;
        insightsList.appendChild(li);
    });

    // AI advice
    document.getElementById('plan-advice').textContent = plan.advice || '—';

    // Coping steps
    const copingList = document.getElementById('plan-coping-steps');
    copingList.innerHTML = '';
    (plan.coping_steps || []).forEach(step => {
        const li = document.createElement('li');
        li.textContent = step;
        copingList.appendChild(li);
    });

    // Reminders
    const reminderList = document.getElementById('plan-reminders');
    reminderList.innerHTML = '';
    (plan.reminders || []).forEach(reminder => {
        const li = document.createElement('li');
        li.textContent = reminder;
        reminderList.appendChild(li);
    });

    // Resources
    const resourcesGrid = document.getElementById('plan-resources');
    resourcesGrid.innerHTML = '';
    (plan.resources || []).forEach(resource => {
        const div = document.createElement('div');
        div.className = 'resource-item';
        div.innerHTML = `
            <div class="resource-name">${resource.name}</div>
            <div class="resource-detail">${resource.detail}</div>
        `;
        resourcesGrid.appendChild(div);
    });
}


// ============================================================
// PLAN ACTION BUTTONS
// ============================================================

document.getElementById('save-plan-btn').addEventListener('click', () => {
    if (!state.plan) return;
    const blob = new Blob([JSON.stringify(state.plan, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `mentra_plan_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Plan saved to file!');
});

document.getElementById('share-plan-btn').addEventListener('click', async () => {
    if (navigator.share && state.plan) {
        try {
            await navigator.share({
                title: 'My MentraAI Wellness Plan',
                text: state.plan.advice,
                url: window.location.href,
            });
        } catch {
            showToast('Share cancelled or not supported.');
        }
    } else {
        if (state.plan) {
            navigator.clipboard.writeText(state.plan.advice).then(() => {
                showToast('Advice copied to clipboard!');
            });
        }
    }
});

document.getElementById('followup-btn').addEventListener('click', () => {
    showToast('Follow-up booking feature coming soon!');
});


// ============================================================
// INITIALIZATION
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    // Pre-fill demo credentials
    document.getElementById('login-email').value    = 'demo@mentra.ai';
    document.getElementById('login-password').value  = 'demo123';
});


// ============================================================
// DASHBOARD
// ============================================================

/**
 * Load and render the complete dashboard from the backend.
 */
async function loadDashboard() {
    const userId = state.userId || 'anonymous';
    try {
        const { ok, data } = await api(`/api/dashboard/${userId}`);
        if (!ok || !data.success) {
            showToast('Could not load dashboard data.');
            return;
        }

        // --- Profile Card ---
        const dashProfile = document.getElementById('dash-profile');
        const p = data.profile;
        if (p && p.first_name) {
            let locationStr = '';
            if (p.city) locationStr += p.city;
            if (p.state) locationStr += (locationStr ? ', ' : '') + p.state;
            if (p.country) locationStr += (locationStr ? ', ' : '') + p.country;

            dashProfile.innerHTML = `
                <div class="dash-detail-grid">
                    <div class="dash-detail"><span class="dash-label">Name</span><span class="dash-value">${p.first_name} ${p.last_name}</span></div>
                    <div class="dash-detail"><span class="dash-label">Age</span><span class="dash-value">${p.age || '—'}</span></div>
                    <div class="dash-detail"><span class="dash-label">Occupation</span><span class="dash-value">${p.occupation || '—'}</span></div>
                    <div class="dash-detail"><span class="dash-label">Field</span><span class="dash-value">${p.profession || '—'}</span></div>
                    ${locationStr ? `<div class="dash-detail dash-detail-wide"><span class="dash-label">Location</span><span class="dash-value">${locationStr}</span></div>` : ''}
                    ${p.hobbies ? `<div class="dash-detail dash-detail-wide"><span class="dash-label">Hobbies</span><span class="dash-value">${p.hobbies}</span></div>` : ''}
                </div>
            `;
        } else {
            dashProfile.innerHTML = '<p class="placeholder-text">No profile data yet.</p>';
        }

        // --- PHQ-9 Card ---
        const dashPhq9 = document.getElementById('dash-phq9');
        const a = data.assessment;
        if (a && a.total_score !== undefined) {
            const severityColors = {
                'Minimal': '#4ade80', 'Mild': '#facc15',
                'Moderate': '#fb923c', 'Moderately Severe': '#f87171', 'Severe': '#ef4444'
            };
            const col = severityColors[a.severity] || '#6366f1';
            dashPhq9.innerHTML = `
                <div class="dash-phq9-score">
                    <div class="dash-big-number" style="color: ${col}">${a.total_score}<span class="dash-small">/27</span></div>
                    <div class="severity-badge" style="background: ${col}22; color: ${col}; border-color: ${col}">${a.severity}</div>
                </div>
                <p class="dash-description">${a.interpretation || ''}</p>
            `;
        } else {
            dashPhq9.innerHTML = '<p class="placeholder-text">No assessment data yet.</p>';
        }

        // --- Interview Card ---
        const dashInterview = document.getElementById('dash-interview');
        const iv = data.interview;
        if (iv && iv.transcript_count > 0) {
            const analysis = iv.analysis || {};
            let interviewHtml = `
                <div class="dash-interview-stats">
                    <div class="dash-stat"><span class="dash-stat-num">${iv.transcript_count}</span><span class="dash-stat-label">Questions Answered</span></div>
                    <div class="dash-stat"><span class="dash-stat-num">${analysis.word_count || 0}</span><span class="dash-stat-label">Words Spoken</span></div>
                    <div class="dash-stat"><span class="dash-stat-num">${analysis.engagement || '—'}</span><span class="dash-stat-label">Engagement</span></div>
                    <div class="dash-stat"><span class="dash-stat-num">${analysis.sentiment || '—'}</span><span class="dash-stat-label">Sentiment</span></div>
                </div>
            `;

            if (analysis.insights && analysis.insights.length > 0) {
                interviewHtml += '<div class="dash-insights"><h4>Key Insights</h4><ul>';
                analysis.insights.forEach(ins => {
                    interviewHtml += `<li>${ins}</li>`;
                });
                interviewHtml += '</ul></div>';
            }

            if (analysis.risk_flag) {
                interviewHtml += '<div class="dash-risk-alert">⚠️ Risk indicators were detected during the interview</div>';
            }

            dashInterview.innerHTML = interviewHtml;
        } else {
            dashInterview.innerHTML = '<p class="placeholder-text">No interview data yet.</p>';
        }

        // --- Plan Card ---
        const dashPlan = document.getElementById('dash-plan');
        const pl = data.plan;
        if (pl && pl.advice) {
            let planHtml = '';

            if (pl.profile_summary) {
                planHtml += `<div class="dash-summary-block"><h4>Summary</h4><p>${pl.profile_summary}</p></div>`;
            }

            planHtml += `<div class="dash-summary-block"><h4>AI Advice</h4><p class="advice-text">${pl.advice}</p></div>`;

            if (pl.llm_generated) {
                planHtml += '<div class="dash-llm-badge">✨ Generated by AI (Qwen2.5)</div>';
            }

            if (pl.stress_insights && pl.stress_insights.length > 0) {
                planHtml += '<div class="dash-summary-block"><h4>Stress Insights</h4><ul class="insight-list">';
                pl.stress_insights.forEach(si => {
                    planHtml += `<li>${si}</li>`;
                });
                planHtml += '</ul></div>';
            }

            if (pl.coping_steps && pl.coping_steps.length > 0) {
                planHtml += '<div class="dash-summary-block"><h4>Coping Steps</h4><ol class="coping-list">';
                pl.coping_steps.forEach(cs => {
                    planHtml += `<li>${cs}</li>`;
                });
                planHtml += '</ol></div>';
            }

            dashPlan.innerHTML = planHtml;
        } else {
            dashPlan.innerHTML = '<p class="placeholder-text">No plan generated yet. Complete the assessment process to see your AI-generated insights.</p>';
        }

    } catch (err) {
        console.error('Dashboard load error:', err);
        showToast('Error loading dashboard.');
    }
}
