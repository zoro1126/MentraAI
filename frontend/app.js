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

    // Use optional chaining so that removed/missing fields default to ''
    const getVal = (id) => (document.getElementById(id)?.value ?? '').trim();

    const profile = {
        user_id: state.userId || 'anonymous',
        first_name: getVal('profile-first-name'),
        last_name: getVal('profile-last-name'),
        age: document.getElementById('profile-age')?.value || '',
        occupation: getVal('profile-occupation'),
        profession: getVal('profile-profession'),
        hobbies: getVal('profile-hobbies'),
        country: getVal('profile-country'),   // may be absent — defaults to ''
        state: getVal('profile-state'),
        city: getVal('profile-city'),
    };

    // Basic validation: require at least a first name
    if (!profile.first_name) {
        showToast('Please enter at least your first name.');
        return;
    }

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
            showToast(data.error || 'Failed to save profile.');
        }
    } catch (err) {
        console.error('Profile save error:', err);
        hideLoading();
        showToast('Network error. Is the server running?');
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
// PDF CLINICAL REPORT GENERATOR
// ============================================================

function generateClinicalReport() {
    if (!state.plan) {
        showToast('Please generate your plan first before downloading.');
        return;
    }

    const plan  = state.plan;
    const prof  = state.profile    || {};
    const phq   = state.phq9Result || {};
    const now   = new Date();
    const dateStr = now.toLocaleDateString('en-IN', { day: '2-digit', month: 'long', year: 'numeric' });
    const timeStr = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

    const esc = (s) => String(s || '—')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    const fullName = [prof.first_name, prof.last_name].filter(Boolean).join(' ') || 'Patient';

    const severityPalette = {
        'Minimal':           { bg: '#dcfce7', text: '#16a34a', border: '#86efac' },
        'Mild':              { bg: '#fef9c3', text: '#ca8a04', border: '#fde047' },
        'Moderate':          { bg: '#ffedd5', text: '#ea580c', border: '#fdba74' },
        'Moderately Severe': { bg: '#fee2e2', text: '#dc2626', border: '#fca5a5' },
        'Severe':            { bg: '#fce7f3', text: '#be185d', border: '#f9a8d4' },
    };
    const sev = severityPalette[phq.severity] || { bg: '#ede9fe', text: '#7c3aed', border: '#c4b5fd' };

    const phqScore = phq.total_score !== undefined ? phq.total_score : '—';
    const phqPct   = phq.total_score !== undefined ? Math.round((phq.total_score / 27) * 100) : 0;
    const scoreColor = sev.text;

    const copingHTML = (plan.coping_steps || []).map((s, i) => `
      <div class="list-item">
        <div class="list-num">${i + 1}</div>
        <div class="list-text">${esc(s)}</div>
      </div>`).join('');

    const remindersHTML = (plan.reminders || []).map(r => `
      <div class="reminder-row"><span>🔔</span><span>${esc(r)}</span></div>`).join('');

    const insightsHTML = (plan.stress_insights || []).map(s => `
      <div class="insight-row"><span class="arr">→</span><span>${esc(s)}</span></div>`).join('');

    const resourcesHTML = (plan.resources || []).map(r => `
      <div class="res-card">
        <div class="res-name">${esc(r.name)}</div>
        <div class="res-detail">${esc(r.detail)}</div>
      </div>`).join('');

    const ia = plan.interview_analysis || null;
    const interviewSection = (ia && ia.analyzed) ? `
      <div class="section">
        <div class="sec-hdr purple-h"><span>💬</span><h2>Interview Analysis</h2></div>
        <div class="sec-body">
          <div class="kv-grid">
            <div class="kv-item"><span class="kv-lbl">Engagement</span><span class="kv-val">${esc(ia.engagement)}</span></div>
            <div class="kv-item"><span class="kv-lbl">Words Spoken</span><span class="kv-val">${ia.word_count}</span></div>
            <div class="kv-item"><span class="kv-lbl">Sentiment</span><span class="kv-val">${esc(ia.sentiment)}</span></div>
            <div class="kv-item"><span class="kv-lbl">Risk Indicators</span>
              <span class="kv-val" style="color:${ia.risk_flag ? '#dc2626' : '#16a34a'};font-weight:700">
                ${ia.risk_flag ? '⚠️ Present' : '✅ None Detected'}</span></div>
          </div>
          ${(ia.insights || []).length > 0 ? '<div style="margin-top:14px"><b style="font-size:.82rem;color:#374151">Key Insights</b><ul class="plain-list" style="margin-top:8px">' +
            ia.insights.map(x => `<li>${esc(x)}</li>`).join('') + '</ul></div>' : ''}
        </div>
      </div>` : '';

    const cvSection = state.cvData ? `
      <div class="section">
        <div class="sec-hdr blue-h"><span>🎥</span><h2>Behavioral &amp; Stress Analysis (CV)</h2></div>
        <div class="sec-body">
          <div class="kv-grid">
            <div class="kv-item"><span class="kv-lbl">Detected Behavior</span><span class="kv-val">${esc(state.cvData.behavior || state.cvData.emotion)}</span></div>
            <div class="kv-item"><span class="kv-lbl">Confidence</span><span class="kv-val">${state.cvData.confidence !== undefined ? (state.cvData.confidence * 100).toFixed(0) + '%' : '—'}</span></div>
            <div class="kv-item"><span class="kv-lbl">Stress Score</span><span class="kv-val">${state.cvData.stress !== undefined ? state.cvData.stress.toFixed(4) : '—'}</span></div>
            <div class="kv-item"><span class="kv-lbl">Blink Rate</span><span class="kv-val">${state.cvData.blink_rate !== undefined ? state.cvData.blink_rate.toFixed(0) + '/min' : '—'}</span></div>
            <div class="kv-item"><span class="kv-lbl">Eye Aperture (EAR)</span><span class="kv-val">${state.cvData.eye !== undefined ? state.cvData.eye.toFixed(4) : '—'}</span></div>
            <div class="kv-item"><span class="kv-lbl">Head Pose (Pitch/Yaw)</span><span class="kv-val">${state.cvData.head_pitch !== undefined ? `${state.cvData.head_pitch.toFixed(2)} / ${(state.cvData.head_yaw || 0).toFixed(2)}` : '—'}</span></div>
          </div>
        </div>
      </div>` : '';

    const locationStr = [prof.city, prof.state, prof.country].filter(Boolean).join(', ') || 'India';

    const profileHTML = `
      <div class="kv-grid">
        <div class="kv-item"><span class="kv-lbl">Full Name</span><span class="kv-val">${esc(fullName)}</span></div>
        <div class="kv-item"><span class="kv-lbl">Age</span><span class="kv-val">${esc(prof.age)}</span></div>
        <div class="kv-item"><span class="kv-lbl">Occupation</span><span class="kv-val">${esc(prof.occupation)}</span></div>
        <div class="kv-item"><span class="kv-lbl">Field / Profession</span><span class="kv-val">${esc(prof.profession)}</span></div>
        <div class="kv-item kv-wide"><span class="kv-lbl">Location</span><span class="kv-val">${esc(locationStr)}</span></div>
        ${prof.hobbies ? `<div class="kv-item kv-wide"><span class="kv-lbl">Hobbies &amp; Interests</span><span class="kv-val">${esc(prof.hobbies)}</span></div>` : ''}
      </div>`;

    const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>MentraAI Report — ${esc(fullName)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;font-size:13.5px;line-height:1.65;color:#111827;background:#fff}

/* COVER */
.cover{min-height:100vh;display:flex;flex-direction:column;padding:60px 72px;
  background:linear-gradient(135deg,#0f0c29 0%,#302b63 50%,#24243e 100%);
  color:#fff;page-break-after:always;position:relative;overflow:hidden}
.cover::before{content:'';position:absolute;top:-120px;right:-120px;width:500px;height:500px;
  border-radius:50%;background:radial-gradient(circle,rgba(99,102,241,.25) 0%,transparent 70%)}
.cover::after{content:'';position:absolute;bottom:-80px;left:-80px;width:400px;height:400px;
  border-radius:50%;background:radial-gradient(circle,rgba(168,85,247,.2) 0%,transparent 70%)}

.cover-nav{display:flex;align-items:center;gap:14px;margin-bottom:auto;position:relative;z-index:1}
.logo-pill{width:52px;height:52px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#a855f7);
  display:flex;align-items:center;justify-content:center;font-size:26px;
  box-shadow:0 0 32px rgba(99,102,241,.5)}
.logo-txt{font-size:1.8rem;font-weight:800;letter-spacing:-.5px}
.logo-txt span{color:#a5b4fc}

.cover-body{position:relative;z-index:1}
.badge{display:inline-block;padding:4px 14px;background:rgba(99,102,241,.3);
  border:1px solid rgba(99,102,241,.5);border-radius:20px;font-size:.7rem;font-weight:600;
  letter-spacing:2px;text-transform:uppercase;color:#c7d2fe;margin-bottom:24px}
.cover-title{font-size:3rem;font-weight:800;line-height:1.15;letter-spacing:-1.5px;margin-bottom:12px;
  background:linear-gradient(135deg,#fff 30%,#a5b4fc 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.cover-sub{font-size:1.1rem;color:#c7d2fe;font-weight:400;margin-bottom:48px}

.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:40px}
.info-box{padding:20px 24px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);
  border-radius:12px}
.info-lbl{font-size:.68rem;text-transform:uppercase;letter-spacing:1.2px;color:#a5b4fc;font-weight:600;margin-bottom:4px}
.info-val{font-size:1.05rem;font-weight:700;color:#fff}

.disclaimer{margin-top:48px;padding:14px 20px;background:rgba(239,68,68,.08);
  border:1px solid rgba(239,68,68,.25);border-radius:10px;font-size:.74rem;color:#fca5a5;
  line-height:1.6;position:relative;z-index:1}
.cover-foot{margin-top:40px;padding-top:24px;border-top:1px solid rgba(255,255,255,.1);
  display:flex;justify-content:space-between;font-size:.73rem;color:rgba(255,255,255,.4);
  position:relative;z-index:1}

/* PAGES */
.page{padding:52px 64px;page-break-after:always}
.page:last-child{page-break-after:auto}
.page-hdr{display:flex;justify-content:space-between;align-items:center;
  padding-bottom:16px;border-bottom:2px solid #e5e7eb;margin-bottom:36px}
.phdr-brand{font-size:.73rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#6366f1}
.phdr-name{font-size:.73rem;color:#9ca3af}

/* SECTIONS */
.section{margin-bottom:32px;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb}
.sec-hdr{display:flex;align-items:center;gap:12px;padding:15px 22px}
.sec-hdr h2{font-size:.95rem;font-weight:700;letter-spacing:-.2px}
.sec-hdr span{font-size:1.15rem}
.sec-body{padding:22px;background:#fff}

.indigo-h{background:linear-gradient(135deg,#eef2ff,#e0e7ff);color:#3730a3}
.green-h {background:linear-gradient(135deg,#f0fdf4,#dcfce7);color:#15803d}
.purple-h{background:linear-gradient(135deg,#faf5ff,#ede9fe);color:#7e22ce}
.blue-h  {background:linear-gradient(135deg,#eff6ff,#dbeafe);color:#1d4ed8}
.amber-h {background:linear-gradient(135deg,#fffbeb,#fef3c7);color:#b45309}
.red-h   {background:linear-gradient(135deg,#fff1f2,#ffe4e6);color:#be123c}
.teal-h  {background:linear-gradient(135deg,#f0fdfa,#ccfbf1);color:#0f766e}

/* KV */
.kv-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px 24px}
.kv-item{display:flex;flex-direction:column;gap:3px}
.kv-wide{grid-column:1/-1}
.kv-lbl{font-size:.67rem;text-transform:uppercase;letter-spacing:.8px;color:#9ca3af;font-weight:600}
.kv-val{font-size:.93rem;font-weight:600;color:#111827}

/* PHQ-9 */
.phq-block{display:flex;align-items:center;gap:32px;padding:22px;background:#fff}
.phq-circle{width:108px;height:108px;border-radius:50%;display:flex;flex-direction:column;
  align-items:center;justify-content:center;border:5px solid ${scoreColor};flex-shrink:0}
.phq-num{font-size:2.2rem;font-weight:800;color:${scoreColor};line-height:1}
.phq-den{font-size:.72rem;color:#9ca3af}
.severity-pill{display:inline-block;padding:5px 16px;border-radius:20px;font-size:.82rem;font-weight:700;
  background:${sev.bg};color:${sev.text};border:1.5px solid ${sev.border};margin-bottom:10px}
.bar-track{width:100%;height:11px;background:#f3f4f6;border-radius:6px;overflow:hidden;margin:8px 0}
.bar-fill{height:100%;width:${phqPct}%;background:linear-gradient(90deg,#6366f1,${scoreColor});border-radius:6px}
.phq-interp{font-size:.82rem;color:#6b7280;line-height:1.7;font-style:italic}

/* ADVICE */
.advice-box{padding:18px 22px;background:linear-gradient(135deg,#f5f3ff,#ede9fe);
  border-left:5px solid #7c3aed;border-radius:0 10px 10px 0;font-size:.9rem;line-height:1.8;
  color:#1f2937;margin:0 22px 22px}

/* NUMBERED LIST */
.list-item{display:flex;align-items:flex-start;gap:14px;padding:11px 0;border-bottom:1px solid #f3f4f6}
.list-item:last-child{border-bottom:none}
.list-num{width:27px;height:27px;min-width:27px;border-radius:50%;
  background:linear-gradient(135deg,#6366f1,#a855f7);color:#fff;
  font-size:.73rem;font-weight:700;display:flex;align-items:center;justify-content:center}
.list-text{font-size:.86rem;color:#374151;line-height:1.6;padding-top:3px}

/* REMINDERS */
.reminder-row{display:flex;gap:10px;align-items:flex-start;padding:9px 12px;margin-bottom:5px;
  background:#f0fdfa;border-left:3px solid #14b8a6;border-radius:0 7px 7px 0;
  font-size:.84rem;color:#134e4a}

/* INSIGHTS */
.insight-row{display:flex;gap:10px;align-items:flex-start;padding:7px 0;font-size:.84rem;
  color:#374151;border-bottom:1px solid #f3f4f6}
.insight-row:last-child{border-bottom:none}
.arr{color:#7c3aed;font-weight:700;flex-shrink:0}

/* RESOURCES */
.res-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:22px}
.res-card{padding:14px;background:#fff1f2;border:1px solid #fecdd3;border-radius:10px}
.res-name{font-weight:700;font-size:.83rem;color:#111827;margin-bottom:3px}
.res-detail{font-size:.76rem;color:#e11d48}

/* PLAIN LIST */
.plain-list{padding-left:18px}
.plain-list li{font-size:.83rem;color:#374151;padding:3px 0}

/* SIGNATURE */
.sig-block{margin-top:36px;padding:22px;border:1px solid #e5e7eb;border-radius:12px;
  display:grid;grid-template-columns:1fr 1fr;gap:40px;background:#fafafa}
.sig-line{border-top:1.5px solid #d1d5db;padding-top:8px;font-size:.72rem;color:#9ca3af}

@media print {
  @page{size:A4;margin:0}
  body{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .cover{min-height:100vh}
}
</style>
</head>
<body>

<!-- COVER -->
<div class="cover">
  <div class="cover-nav">
    <div class="logo-pill">🧠</div>
    <div class="logo-txt">Mentra<span>AI</span></div>
  </div>
  <div class="cover-body">
    <div class="badge">Confidential Clinical Report</div>
    <div class="cover-title">Mental Health<br>Assessment Report</div>
    <div class="cover-sub">AI-powered screening &amp; personalised wellness plan</div>
    <div class="info-grid">
      <div class="info-box"><div class="info-lbl">Patient</div><div class="info-val">${esc(fullName)}</div></div>
      <div class="info-box"><div class="info-lbl">Report Date</div><div class="info-val">${dateStr}</div></div>
      <div class="info-box"><div class="info-lbl">PHQ-9 Result</div>
        <div class="info-val" style="color:${sev.text}">${phqScore}/27 — ${esc(phq.severity)}</div></div>
      <div class="info-box"><div class="info-lbl">Platform</div><div class="info-val">MentraAI v2.0</div></div>
    </div>
    <div class="disclaimer">
      ⚠️ <strong>Important:</strong> This report is generated by an AI screening tool and is <strong>not a clinical diagnosis</strong>.
      Please consult a qualified mental health professional for diagnosis and treatment.
    </div>
    <div class="cover-foot">
      <span>MentraAI — AI Mental Health Companion</span>
      <span>Generated ${dateStr} at ${timeStr}</span>
    </div>
  </div>
</div>

<!-- PAGE 2: PROFILE + PHQ-9 -->
<div class="page">
  <div class="page-hdr">
    <span class="phdr-brand">MentraAI Clinical Report</span>
    <span class="phdr-name">${esc(fullName)} | ${dateStr}</span>
  </div>

  <div class="section">
    <div class="sec-hdr indigo-h"><span>👤</span><h2>Patient Profile</h2></div>
    <div class="sec-body">${profileHTML}</div>
  </div>

  <div class="section">
    <div class="sec-hdr green-h"><span>📋</span><h2>PHQ-9 Depression Screening</h2></div>
    <div class="phq-block">
      <div class="phq-circle">
        <div class="phq-num">${phqScore}</div>
        <div class="phq-den">out of 27</div>
      </div>
      <div style="flex:1">
        <div class="severity-pill">${esc(phq.severity || '—')} Depression</div>
        <div class="bar-track"><div class="bar-fill"></div></div>
        <div style="display:flex;justify-content:space-between;font-size:.7rem;color:#9ca3af;margin-top:4px">
          <span>0 — Minimal</span><span>14 — Moderate</span><span>27 — Severe</span>
        </div>
        <div class="phq-interp">${esc(phq.interpretation)}</div>
      </div>
    </div>
  </div>

  ${cvSection}
</div>

<!-- PAGE 3: ADVICE + INSIGHTS + INTERVIEW -->
<div class="page">
  <div class="page-hdr">
    <span class="phdr-brand">MentraAI Clinical Report</span>
    <span class="phdr-name">${esc(fullName)} | ${dateStr}</span>
  </div>

  ${plan.profile_summary ? `
  <div class="section">
    <div class="sec-hdr purple-h"><span>🔍</span><h2>Clinical Summary</h2></div>
    <div class="sec-body"><p style="font-size:.9rem;color:#374151;line-height:1.8">${esc(plan.profile_summary)}</p></div>
  </div>` : ''}

  ${insightsHTML ? `
  <div class="section">
    <div class="sec-hdr amber-h"><span>📊</span><h2>Stress &amp; Behavioral Insights</h2></div>
    <div class="sec-body">${insightsHTML}</div>
  </div>` : ''}

  <div class="section">
    <div class="sec-hdr purple-h"><span>🤖</span><h2>AI-Generated Advice</h2></div>
    <div class="advice-box">${esc(plan.advice)}</div>
  </div>

  ${interviewSection}
</div>

<!-- PAGE 4: COPING + REMINDERS + RESOURCES -->
<div class="page">
  <div class="page-hdr">
    <span class="phdr-brand">MentraAI Clinical Report</span>
    <span class="phdr-name">${esc(fullName)} | ${dateStr}</span>
  </div>

  ${copingHTML ? `
  <div class="section">
    <div class="sec-hdr teal-h"><span>🛠️</span><h2>Personalised Coping Steps</h2></div>
    <div class="sec-body">${copingHTML}</div>
  </div>` : ''}

  ${remindersHTML ? `
  <div class="section">
    <div class="sec-hdr blue-h"><span>🔔</span><h2>Daily Wellness Reminders</h2></div>
    <div class="sec-body">${remindersHTML}</div>
  </div>` : ''}

  <div class="section">
    <div class="sec-hdr red-h"><span>🆘</span><h2>Crisis &amp; Support Resources</h2></div>
    <div class="res-grid">${resourcesHTML}</div>
  </div>

  <div class="sig-block">
    <div><div class="sig-line">Patient Signature / Date</div></div>
    <div><div class="sig-line">Reviewing Clinician / Date</div></div>
  </div>

  <p style="margin-top:24px;font-size:.7rem;color:#8b5cf6;text-align:center;line-height:1.8">
    This document was generated by MentraAI — an AI-assisted mental health screening platform.<br>
    For clinical decisions, always consult a licensed mental health professional.<br>
    <strong>iCall (India): 9152987821 | Vandrevala Foundation: 1860-2662-345 (24/7 free)</strong>
  </p>
</div>

</body>
</html>`;

    const win = window.open('', '_blank', 'width=960,height=780');
    if (!win) {
        showToast('Pop-up blocked. Please allow pop-ups and try again.');
        return;
    }
    win.document.write(html);
    win.document.close();
    // Wait for Google Fonts to load, then print
    win.addEventListener('load', () => {
        setTimeout(() => { win.focus(); win.print(); }, 900);
    });
    showToast('Opening clinical report — save as PDF from the print dialog…');
}


// ============================================================

document.getElementById('save-plan-btn').addEventListener('click', generateClinicalReport);


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
// STT (Speech-to-Text) TOGGLE — Web Speech API
// ============================================================

(function setupSTT() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const btn = document.getElementById('stt-toggle-btn');
    const label = document.getElementById('stt-toggle-label');
    const indicator = document.getElementById('mic-indicator');
    const textarea = document.getElementById('interview-text-input');

    if (!btn) return;  // guard

    if (!SpeechRecognition) {
        btn.title = 'Speech recognition not supported in this browser';
        btn.style.opacity = '0.4';
        btn.style.cursor = 'not-allowed';
        btn.addEventListener('click', () => showToast('Voice input not supported in this browser. Please type your answer.'));
        return;
    }

    let recognition = null;
    let sttActive = false;

    function startSTT() {
        recognition = new SpeechRecognition();
        recognition.lang = 'en-IN';
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;

        let finalTranscript = textarea ? textarea.value : '';

        recognition.onresult = (event) => {
            let interim = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const t = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalTranscript += t + ' ';
                } else {
                    interim = t;
                }
            }
            if (textarea) textarea.value = finalTranscript + interim;
        };

        recognition.onerror = (e) => {
            console.warn('STT error:', e.error);
            stopSTT();
            showToast(`Voice error: ${e.error}. Please type your answer.`);
        };

        recognition.onend = () => {
            if (sttActive) recognition.start();  // keep going if not manually stopped
        };

        recognition.start();
        sttActive = true;
        if (label) label.textContent = 'Stop';
        if (indicator) indicator.classList.remove('hidden');
        btn.classList.add('btn-mic-active');
    }

    function stopSTT() {
        sttActive = false;
        if (recognition) { try { recognition.stop(); } catch (_) {} recognition = null; }
        if (label) label.textContent = 'Voice';
        if (indicator) indicator.classList.add('hidden');
        btn.classList.remove('btn-mic-active');
    }

    btn.addEventListener('click', () => {
        if (sttActive) { stopSTT(); }
        else { startSTT(); }
    });

    // Stop STT whenever the interview advances (submit/skip)
    ['done-question-btn', 'skip-question-btn'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', stopSTT, { capture: true });
    });
})();


// ============================================================
// INITIALIZATION
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    // Pre-fill demo credentials
    document.getElementById('login-email').value    = 'demo@mentra.ai';
    document.getElementById('login-password').value  = 'demo123';

    // Wire up the profile → PHQ-9 nav button to also load questions
    const profileForwardBtn = document.getElementById('profile-next-nav-btn');
    if (profileForwardBtn) {
        profileForwardBtn.addEventListener('click', (e) => {
            e.preventDefault();
            loadPHQ9Questions();
            showScreen('screen-phq9');
        });
    }
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
