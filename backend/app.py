#!/usr/bin/env python3
"""
app.py - Unified Flask backend for MentraAI Mental Health Assistant.

Serves the frontend and provides REST API endpoints for:
  - User authentication (mock)
  - User profile management
  - PHQ-9 questionnaire submission & scoring
  - CV (computer vision) emotion/stress analysis via webcam frames
  - LLM-based personal plan generation
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from cv_pipeline import CVPipeline
from llm_pipeline import LLMEngine

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("mentra_api")

# ---------------------------------------------------------------------------
# In-memory stores (replace with a real DB in production)
# ---------------------------------------------------------------------------
USERS: Dict[str, Dict[str, Any]] = {
    "demo@mentra.ai": {
        "id": "u-demo-001",
        "email": "demo@mentra.ai",
        "password": "demo123",
        "name": "Demo User",
    }
}

PROFILES: Dict[str, Dict[str, Any]] = {}       # keyed by user id
ASSESSMENTS: Dict[str, Dict[str, Any]] = {}    # keyed by user id
PLANS: Dict[str, Dict[str, Any]] = {}          # keyed by user id
TRANSCRIPTS: Dict[str, list] = {}              # keyed by user id — interview transcripts
INTERVIEW_CV: Dict[str, list] = {}             # keyed by user id — CV snapshots during interview

# ---------------------------------------------------------------------------
# Structured Interview Questions (10 categories)
# ---------------------------------------------------------------------------
INTERVIEW_QUESTIONS = [
    {
        "id": 1,
        "category": "Warm-Up",
        "color": "#4ade80",
        "icon": "🟢",
        "questions": [
            "Hey, how are you feeling right now, in your own words?",
            "How has your day been so far?"
        ],
        "purpose": "Baseline tone, speech pace, emotional openness",
        "detects": ["baseline_tone", "speech_pace", "emotional_openness"]
    },
    {
        "id": 2,
        "category": "Emotional Awareness",
        "color": "#3b82f6",
        "icon": "🔵",
        "questions": [
            "What emotions have you been experiencing the most lately?",
            "Do your feelings change throughout the day, or stay mostly the same?"
        ],
        "purpose": "Emotional variability vs flatness, vocabulary richness",
        "detects": ["emotional_variability", "vocabulary_richness"]
    },
    {
        "id": 3,
        "category": "Energy & Motivation",
        "color": "#facc15",
        "icon": "🟡",
        "questions": [
            "How easy or difficult has it been to get started on things lately?",
            "Do you feel mentally or physically tired most of the time?"
        ],
        "purpose": "Fatigue detection, anhedonia (deeper context beyond PHQ-9)",
        "detects": ["fatigue", "anhedonia"]
    },
    {
        "id": 4,
        "category": "Thought Patterns",
        "color": "#fb923c",
        "icon": "🟠",
        "questions": [
            "What kind of thoughts have been on your mind the most recently?",
            "Do you find yourself overthinking or replaying things in your head?"
        ],
        "purpose": "Rumination, negative loops, anxiety markers",
        "detects": ["rumination", "negative_loops", "anxiety_markers"],
        "critical": True
    },
    {
        "id": 5,
        "category": "Stress & Triggers",
        "color": "#ef4444",
        "icon": "🔴",
        "questions": [
            "What has been stressing you out the most recently?",
            "When you feel stressed, what usually causes it?"
        ],
        "purpose": "Combine with CV movement spikes and voice tension",
        "detects": ["stress_sources", "trigger_awareness"]
    },
    {
        "id": 6,
        "category": "Social Connection",
        "color": "#a855f7",
        "icon": "🟣",
        "questions": [
            "Have you been talking to people regularly, or keeping more to yourself?",
            "Do you feel supported by the people around you?"
        ],
        "purpose": "Isolation, perceived vs actual support",
        "detects": ["isolation", "perceived_support"]
    },
    {
        "id": 7,
        "category": "Self-Perception",
        "color": "#1f2937",
        "icon": "⚫",
        "questions": [
            "How do you feel about yourself these days?",
            "Have you been more critical of yourself than usual?"
        ],
        "purpose": "Low self-worth, internal dialogue tone",
        "detects": ["self_worth", "internal_dialogue"]
    },
    {
        "id": 8,
        "category": "Coping Behavior",
        "color": "#92400e",
        "icon": "🟤",
        "questions": [
            "What do you usually do when you start feeling overwhelmed?",
            "Is there anything that helps you feel even slightly better?"
        ],
        "purpose": "Healthy vs unhealthy coping, awareness of coping",
        "detects": ["coping_style", "coping_awareness"]
    },
    {
        "id": 9,
        "category": "Future Outlook",
        "color": "#e5e7eb",
        "icon": "⚪",
        "questions": [
            "How do you feel about the near future?",
            "Do you feel hopeful about things improving?"
        ],
        "purpose": "Hopelessness — strong depression marker",
        "detects": ["hopelessness", "future_orientation"],
        "critical": True
    },
    {
        "id": 10,
        "category": "Gentle Risk Check",
        "color": "#ef4444",
        "icon": "🔺",
        "questions": [
            "Sometimes when people feel really overwhelmed, they may have thoughts about wanting to escape everything. Have you felt anything like that?"
        ],
        "purpose": "Risk without being aggressive — should trigger escalation logic",
        "detects": ["risk_ideation", "escape_thoughts"],
        "critical": True,
        "risk_check": True
    }
]


def analyze_interview_transcripts(transcripts: list) -> Dict[str, Any]:
    """Analyze interview transcripts to extract signals for plan generation.

    Uses keyword-based heuristics. In production, replace with LLM analysis.
    """
    if not transcripts:
        return {"analyzed": False}

    all_text = " ".join(
        t.get("response", "") for t in transcripts
    ).lower()

    word_count = len(all_text.split())

    # Negative / concerning keyword detection
    negative_words = [
        "hopeless", "worthless", "nothing", "empty", "alone", "lonely",
        "can't", "unable", "exhausted", "overwhelmed", "numb", "trapped",
        "failure", "useless", "pointless", "terrible", "awful", "scared",
        "anxious", "worried", "panic", "dread", "tired", "sleep",
        "crying", "cry", "hurt", "pain", "escape", "end",
        "overthink", "ruminate", "replay", "loop"
    ]
    positive_words = [
        "hopeful", "grateful", "happy", "joy", "better", "improving",
        "supported", "friends", "family", "love", "exercise", "hobby",
        "meditation", "walk", "nature", "thankful", "motivated",
        "purpose", "goal", "progress", "calm", "peaceful", "relaxed"
    ]

    neg_count = sum(1 for w in negative_words if w in all_text)
    pos_count = sum(1 for w in positive_words if w in all_text)

    # Risk flag check — the most critical one
    risk_keywords = ["escape", "end it", "give up", "better off", "no point",
                     "hurt myself", "don't want to be here", "disappear"]
    risk_flag = any(kw in all_text for kw in risk_keywords)

    # Engagement: word count per question
    engagement = "low" if word_count < 30 else "moderate" if word_count < 100 else "high"

    # Sentiment ratio
    total_signals = neg_count + pos_count
    sentiment = "neutral"
    if total_signals > 0:
        pos_ratio = pos_count / total_signals
        if pos_ratio > 0.65:
            sentiment = "positive"
        elif pos_ratio < 0.35:
            sentiment = "negative"

    # Category-specific insights
    insights = []
    for t in transcripts:
        cat = t.get("category", "")
        resp = (t.get("response", "")).lower()
        if cat == "Thought Patterns" and any(w in resp for w in ["overthink", "replay", "loop", "ruminate", "can't stop"]):
            insights.append("Rumination patterns detected in thought analysis")
        if cat == "Social Connection" and any(w in resp for w in ["alone", "lonely", "nobody", "isolated", "myself"]):
            insights.append("Signs of social isolation noted")
        if cat == "Future Outlook" and any(w in resp for w in ["hopeless", "no future", "won't get better", "pointless"]):
            insights.append("Hopelessness indicators present — key depression marker")
        if cat == "Coping Behavior" and any(w in resp for w in ["drink", "alcohol", "drug", "smoke", "avoid", "ignore"]):
            insights.append("Potentially unhealthy coping mechanisms reported")

    return {
        "analyzed": True,
        "word_count": word_count,
        "engagement": engagement,
        "sentiment": sentiment,
        "negative_signals": neg_count,
        "positive_signals": pos_count,
        "risk_flag": risk_flag,
        "insights": insights,
    }

# ---------------------------------------------------------------------------
# CV Pipeline singleton
# ---------------------------------------------------------------------------
cv_pipeline: Optional[CVPipeline] = None


def get_cv_pipeline() -> CVPipeline:
    global cv_pipeline
    if cv_pipeline is None:
        LOGGER.info("Initializing CV pipeline …")
        cv_pipeline = CVPipeline()
    return cv_pipeline


# ---------------------------------------------------------------------------
# LLM Engine singleton
# ---------------------------------------------------------------------------
_llm_engine: Optional[LLMEngine] = None
_llm_lock = threading.Lock()

LLM_MODEL_PATH = Path(__file__).resolve().parent / "models" / "Qwen2.5-7B-Instruct-Q4_K_M.gguf"


def get_llm_engine() -> LLMEngine:
    """Lazily initialize the LLM engine (thread-safe singleton)."""
    global _llm_engine
    if _llm_engine is not None:
        return _llm_engine
    with _llm_lock:
        if _llm_engine is not None:
            return _llm_engine
        LOGGER.info("Initializing LLM engine with model: %s", LLM_MODEL_PATH)
        _llm_engine = LLMEngine(
            model_path=LLM_MODEL_PATH,
            n_ctx=4096,
            n_threads=max(1, (os.cpu_count() or 4) - 1),
            n_batch=512,
            temperature=0.7,
            top_p=0.9,
            repeat_penalty=1.1,
            max_tokens=1024,
            stop_sequences=("User:", "System:"),
        )
        _llm_engine.load()
        return _llm_engine


def llm_analyze_user_data(
    profile: Dict[str, Any],
    assessment: Dict[str, Any],
    cv_data: Optional[Dict[str, Any]],
    transcripts: list,
    interview_analysis: Dict[str, Any],
) -> Dict[str, Any]:
    """Use the LLM to analyze all collected user data and generate a comprehensive plan."""
    # Build a detailed prompt with all user information
    prompt_parts = []

    # Profile info
    name = profile.get("first_name", "User")
    prompt_parts.append(f"Patient Name: {name} {profile.get('last_name', '')}")
    if profile.get("age"):
        prompt_parts.append(f"Age: {profile['age']}")
    if profile.get("occupation"):
        prompt_parts.append(f"Occupation: {profile['occupation']}")
    if profile.get("profession"):
        prompt_parts.append(f"Field: {profile['profession']}")
    if profile.get("hobbies"):
        prompt_parts.append(f"Hobbies: {profile['hobbies']}")
    if profile.get("country"):
        location = profile['country']
        if profile.get('state'):
            location = f"{profile['state']}, {location}"
        if profile.get('city'):
            location = f"{profile['city']}, {location}"
        prompt_parts.append(f"Location: {location}")

    # PHQ-9 results
    phq_score = assessment.get("total_score", 0)
    severity = assessment.get("severity", "Minimal")
    prompt_parts.append(f"\nPHQ-9 Assessment Score: {phq_score}/27 — Severity: {severity}")

    # CV data
    if cv_data:
        prompt_parts.append(f"\nFacial/Video Analysis:")
        prompt_parts.append(f"  Dominant Emotion: {cv_data.get('emotion', 'N/A')}")
        prompt_parts.append(f"  Stress Level: {cv_data.get('stress', 'N/A')}")
        prompt_parts.append(f"  Confidence: {cv_data.get('confidence', 'N/A')}")
        if cv_data.get('blink_rate') is not None:
            prompt_parts.append(f"  Blink Rate: {cv_data['blink_rate']:.0f}/min")

    # Interview analysis
    if interview_analysis and interview_analysis.get("analyzed"):
        ia = interview_analysis
        prompt_parts.append(f"\nInterview Analysis:")
        prompt_parts.append(f"  Engagement: {ia.get('engagement', 'N/A')} ({ia.get('word_count', 0)} words)")
        prompt_parts.append(f"  Sentiment: {ia.get('sentiment', 'N/A')}")
        prompt_parts.append(f"  Risk Flag: {'YES' if ia.get('risk_flag') else 'No'}")
        for ins in ia.get("insights", []):
            prompt_parts.append(f"  Insight: {ins}")

    # Transcript snippets
    if transcripts:
        prompt_parts.append(f"\nKey Interview Responses:")
        for t in transcripts[:15]:  # Limit to avoid exceeding context
            cat = t.get("category", "")
            q = t.get("question", "")
            r = t.get("response", "")
            if r and r != "(no response)":
                prompt_parts.append(f"  [{cat}] Q: {q}")
                prompt_parts.append(f"           A: {r}")

    user_data_text = "\n".join(prompt_parts)

    system_prompt = (
        "You are an expert clinical psychologist AI assistant for MentraAI, "
        "a mental health support platform. Analyze the provided patient data "
        "and generate a comprehensive, empathetic, and personalized mental health response.\n\n"
        "You MUST respond with a valid JSON object (no markdown, no code fences) with these exact keys:\n"
        '{"summary": "A 2-3 sentence summary of the patient\'s current state",'
        ' "advice": "A warm, personalized 3-5 sentence message to the patient",'
        ' "stress_level": "One of: Minimal, Mild, Moderate, Moderately Severe, Severe",'
        ' "stress_insights": ["insight 1", "insight 2", "insight 3"],'
        ' "coping_steps": ["step 1", "step 2", "step 3", "step 4", "step 5"],'
        ' "reminders": ["reminder 1", "reminder 2", "reminder 3"],'
        ' "risk_assessment": "low/moderate/high"}'
    )

    user_prompt = (
        f"Here is the complete assessment data for a patient:\n\n"
        f"{user_data_text}\n\n"
        f"Analyze all the data above and generate the JSON response."
    )

    try:
        engine = get_llm_engine()
        response_text, completed = engine.generate(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
        )

        LOGGER.info("LLM response (first 500 chars): %s", response_text[:500])

        # Try to parse JSON from the response
        # Strip any markdown fences if present
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        # Find the first { and last }
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            cleaned = cleaned[start:end + 1]

        parsed = json.loads(cleaned)
        return {
            "llm_generated": True,
            "summary": parsed.get("summary", ""),
            "advice": parsed.get("advice", ""),
            "stress_level": parsed.get("stress_level", severity),
            "stress_insights": parsed.get("stress_insights", []),
            "coping_steps": parsed.get("coping_steps", []),
            "reminders": parsed.get("reminders", []),
            "risk_assessment": parsed.get("risk_assessment", "low"),
        }
    except Exception as exc:
        LOGGER.warning("LLM analysis failed, falling back to heuristic: %s", exc)
        return {"llm_generated": False}


# ---------------------------------------------------------------------------
# PHQ-9 scoring helper
# ---------------------------------------------------------------------------
PHQ9_QUESTIONS = [
    "Little interest or pleasure in doing things",
    "Feeling down, depressed, or hopeless",
    "Trouble falling or staying asleep, or sleeping too much",
    "Feeling tired or having little energy",
    "Poor appetite or overeating",
    "Feeling bad about yourself — or that you are a failure or have let yourself or your family down",
    "Trouble concentrating on things, such as reading the newspaper or watching television",
    "Moving or speaking so slowly that other people could have noticed? Or the opposite — being so fidgety or restless that you have been moving around a lot more than usual",
    "Thoughts that you would be better off dead, or of hurting yourself in some way",
]

PHQ9_OPTIONS = [
    "Not at all",
    "Several days",
    "More than half the days",
    "Nearly every day",
]


def score_phq9(answers: list[int]) -> Dict[str, Any]:
    """Score PHQ-9 and return severity information."""
    total = sum(answers)
    if total <= 4:
        severity = "Minimal"
        color = "#4ade80"
    elif total <= 9:
        severity = "Mild"
        color = "#facc15"
    elif total <= 14:
        severity = "Moderate"
        color = "#fb923c"
    elif total <= 19:
        severity = "Moderately Severe"
        color = "#f87171"
    else:
        severity = "Severe"
        color = "#ef4444"

    return {
        "total_score": total,
        "max_score": 27,
        "severity": severity,
        "color": color,
        "interpretation": (
            f"Your PHQ-9 score is {total}/27 indicating {severity.lower()} depression. "
            "This is a screening tool, not a diagnosis. Please consult a mental health professional."
        ),
    }


# ---------------------------------------------------------------------------
# Generate a personal plan (heuristic-based; replace with LLM in production)
# ---------------------------------------------------------------------------
def generate_personal_plan(
    profile: Dict[str, Any],
    assessment: Dict[str, Any],
    cv_data: Optional[Dict[str, Any]] = None,
    interview_analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a personalized mental health plan based on all collected data."""
    severity = assessment.get("severity", "Minimal")
    phq_score = assessment.get("total_score", 0)
    name = profile.get("first_name", "User")
    hobbies = profile.get("hobbies", "")
    occupation = profile.get("occupation", "")

    # If risk flag is set from interview, escalate severity
    if interview_analysis and interview_analysis.get("risk_flag"):
        severity = "Severe"  # Escalate to ensure crisis resources are shown

    # Build profile summary
    profile_summary = f"{name}"
    if profile.get("age"):
        profile_summary += f", {profile['age']} years old"
    if occupation:
        profile_summary += f", works as {occupation}"
    if profile.get("profession"):
        profile_summary += f" ({profile['profession']})"

    # Build stress insights
    stress_insights = []
    if cv_data:
        emotion = cv_data.get("emotion", "calm")
        stress_val = cv_data.get("stress", 0)
        confidence = cv_data.get("confidence", 0)
        # Friendly emotion labels for new FACS set
        emotion_labels = {
            "happy": "Happy", "calm": "Calm", "sad": "Sad",
            "surprised": "Surprised", "fear": "Fearful",
            "angry": "Angry", "disgust": "Disgusted",
            "anxious": "Anxious", "tired": "Tired",
        }
        emotion_display = emotion_labels.get(emotion, emotion.capitalize())
        stress_insights.append(f"Detected emotion: {emotion_display} ({confidence:.0%} confidence)")
        if stress_val > 0.3:
            stress_insights.append("Elevated stress levels observed during video analysis")
        elif stress_val < -0.2:
            stress_insights.append("You appeared calm and relaxed during the session")
        else:
            stress_insights.append("Moderate stress levels observed")
        blink = cv_data.get("blink_rate")
        if blink is not None:
            if blink > 25:
                stress_insights.append(f"Elevated blink rate ({blink:.0f}/min) — possible anxiety signal")
            elif blink < 8:
                stress_insights.append(f"Low blink rate ({blink:.0f}/min) — possible fatigue or dissociation")

    # Interview insights
    if interview_analysis and interview_analysis.get("analyzed"):
        ia = interview_analysis
        stress_insights.append(f"Interview engagement: {ia['engagement']} ({ia['word_count']} words)")
        stress_insights.append(f"Sentiment: {ia['sentiment']}")
        if ia.get("risk_flag"):
            stress_insights.append("⚠️ Risk indicators detected — crisis resources prioritized")
        for insight in ia.get("insights", []):
            stress_insights.append(insight)

    stress_insights.append(f"PHQ-9 Score: {phq_score}/27 — {severity} depression")

    # Coping steps based on severity
    coping_steps = []
    if severity in ("Minimal", "Mild"):
        coping_steps = [
            "Maintain your current healthy routines",
            "Practice mindfulness meditation for 10 minutes daily",
            "Engage in physical exercise at least 3 times a week",
            f"Continue enjoying your hobbies: {hobbies}" if hobbies else "Explore new hobbies that bring you joy",
            "Keep a gratitude journal — write 3 things you're thankful for each day",
            "Ensure 7-8 hours of quality sleep each night",
        ]
    elif severity == "Moderate":
        coping_steps = [
            "Consider speaking with a mental health professional",
            "Establish a structured daily routine with fixed wake/sleep times",
            "Practice deep breathing exercises when feeling overwhelmed",
            "Limit screen time, especially before bed",
            "Connect with friends or family regularly — social support is crucial",
            "Try cognitive reframing: challenge negative thought patterns",
            f"Set aside time for activities you enjoy: {hobbies}" if hobbies else "Rediscover activities that once brought you pleasure",
        ]
    else:
        coping_steps = [
            "We strongly recommend consulting a mental health professional soon",
            "Reach out to a trusted person about how you're feeling",
            "Crisis helpline: 988 Suicide & Crisis Lifeline (call or text 988)",
            "Focus on basic self-care: eating, sleeping, and hygiene",
            "Avoid making major life decisions during this time",
            "Practice grounding techniques: 5-4-3-2-1 sensory exercise",
            "Consider a structured therapy approach like CBT",
            "Take things one day at a time — recovery is a journey",
        ]

    # Add interview-specific coping steps
    if interview_analysis and interview_analysis.get("analyzed"):
        for insight in interview_analysis.get("insights", []):
            if "rumination" in insight.lower():
                coping_steps.append("Practice thought-stopping techniques when you catch yourself in a loop")
            if "isolation" in insight.lower():
                coping_steps.append("Schedule at least one social interaction per day, even a short phone call")
            if "unhealthy coping" in insight.lower():
                coping_steps.append("Identify one healthy replacement for each unhealthy coping mechanism")

    # Resources
    resources = [
        {"name": "988 Suicide & Crisis Lifeline", "detail": "Call or text 988"},
        {"name": "Crisis Text Line", "detail": "Text HOME to 741741"},
        {"name": "NAMI Helpline", "detail": "1-800-950-NAMI (6264)"},
        {"name": "MentalHealth.gov", "detail": "https://www.mentalhealth.gov"},
    ]

    # Reminders
    reminders = [
        "Morning mindfulness session at 7:00 AM",
        "Midday check-in: rate your mood 1-10",
        "Evening wind-down: no screens after 9:00 PM",
        "Weekly progress reflection every Sunday",
    ]

    # AI advice message — enhanced with interview context
    interview_context = ""
    if interview_analysis and interview_analysis.get("analyzed"):
        if interview_analysis["sentiment"] == "negative":
            interview_context = " During our conversation, we noticed some patterns that suggest you may be going through a difficult time. "
        elif interview_analysis["sentiment"] == "positive":
            interview_context = " Your responses during our conversation showed resilience and self-awareness, which are strong protective factors. "

    if severity in ("Minimal", "Mild"):
        advice = (
            f"Hey {name}, your assessment suggests you're doing relatively well."
            f"{interview_context}"
            "Keep nurturing your mental health with the suggested practices. "
            "Remember, prevention is just as important as treatment. Stay connected "
            "with the people and activities that bring you joy."
        )
    elif severity == "Moderate":
        advice = (
            f"Hi {name}, your results suggest you may be experiencing moderate symptoms."
            f"{interview_context}"
            "This is not uncommon and there's a lot you can do to feel better. "
            "Consider reaching out to a counselor or therapist who can provide "
            "personalized support. The coping strategies below are a great starting point."
        )
    else:
        advice = (
            f"Dear {name}, your assessment indicates significant symptoms that deserve attention."
            f"{interview_context}"
            "Please know that help is available and reaching out is a sign of strength, not weakness. "
            "We encourage you to contact a mental health professional or one of the crisis "
            "resources listed below. You don't have to face this alone."
        )

    return {
        "profile_summary": profile_summary,
        "stress_level": severity,
        "stress_insights": stress_insights,
        "coping_steps": coping_steps,
        "reminders": reminders,
        "resources": resources,
        "advice": advice,
        "interview_analysis": interview_analysis if interview_analysis else None,
        "generated_at": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
CORS(app)


# ---- Static frontend ----
@app.route("/")
def serve_index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(str(FRONTEND_DIR), path)


# ---- Auth ----
@app.post("/api/login")
def login():
    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    user = USERS.get(email)
    if user and user["password"] == password:
        token = str(uuid.uuid4())
        return jsonify({"success": True, "token": token, "user_id": user["id"], "name": user["name"]})
    return jsonify({"success": False, "error": "Invalid email or password."}), 401


@app.post("/api/signup")
def signup():
    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    name = data.get("name", "User")

    if email in USERS:
        return jsonify({"success": False, "error": "Email already registered."}), 409

    user_id = f"u-{uuid.uuid4().hex[:8]}"
    USERS[email] = {"id": user_id, "email": email, "password": password, "name": name}
    token = str(uuid.uuid4())
    return jsonify({"success": True, "token": token, "user_id": user_id, "name": name}), 201


# ---- Profile ----
@app.post("/api/profile")
def save_profile():
    data = request.get_json(force=True)
    user_id = data.get("user_id", "anonymous")
    profile = {
        "first_name": data.get("first_name", ""),
        "last_name": data.get("last_name", ""),
        "age": data.get("age", ""),
        "occupation": data.get("occupation", ""),
        "profession": data.get("profession", ""),
        "hobbies": data.get("hobbies", ""),
        "country": data.get("country", ""),
        "state": data.get("state", ""),
        "city": data.get("city", ""),
    }
    PROFILES[user_id] = profile
    return jsonify({"success": True, "profile": profile})


@app.get("/api/profile/<user_id>")
def get_profile(user_id):
    profile = PROFILES.get(user_id)
    if profile:
        return jsonify({"success": True, "profile": profile})
    return jsonify({"success": False, "error": "Profile not found."}), 404


# ---- PHQ-9 ----
@app.get("/api/phq9/questions")
def get_phq9_questions():
    return jsonify({
        "questions": PHQ9_QUESTIONS,
        "options": PHQ9_OPTIONS,
    })


@app.post("/api/phq9/submit")
def submit_phq9():
    data = request.get_json(force=True)
    user_id = data.get("user_id", "anonymous")
    answers = data.get("answers", [])
    if len(answers) != 9:
        return jsonify({"success": False, "error": "Exactly 9 answers required."}), 400

    try:
        answers = [int(a) for a in answers]
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Answers must be integers 0-3."}), 400

    result = score_phq9(answers)
    ASSESSMENTS[user_id] = result
    return jsonify({"success": True, **result})


# ---- Interview Questions ----
@app.get("/api/interview/questions")
def get_interview_questions():
    return jsonify({"success": True, "questions": INTERVIEW_QUESTIONS})


@app.post("/api/interview/save_response")
def save_interview_response():
    """Save a single interview response (question + user's spoken answer)."""
    data = request.get_json(force=True)
    user_id = data.get("user_id", "anonymous")
    entry = {
        "category": data.get("category", ""),
        "question": data.get("question", ""),
        "response": data.get("response", ""),
        "question_id": data.get("question_id", 0),
        "timestamp": datetime.now().isoformat(),
        "cv_snapshot": data.get("cv_snapshot", None),
    }

    if user_id not in TRANSCRIPTS:
        TRANSCRIPTS[user_id] = []
    TRANSCRIPTS[user_id].append(entry)

    return jsonify({"success": True, "saved": len(TRANSCRIPTS[user_id])})


@app.get("/api/interview/transcript/<user_id>")
def get_transcript(user_id):
    t = TRANSCRIPTS.get(user_id, [])
    return jsonify({"success": True, "transcript": t})


# ---- CV Analysis (single frame) ----
@app.post("/api/cv/analyze_frame")
def analyze_frame():
    """Receive a base64-encoded JPEG frame, run CV pipeline, return results."""
    data = request.get_json(force=True)
    frame_b64 = data.get("frame", "")

    if not frame_b64:
        return jsonify({"success": False, "error": "No frame data provided."}), 400

    try:
        # Decode base64 → numpy array
        img_bytes = base64.b64decode(frame_b64)
        np_arr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({"success": False, "error": "Could not decode frame."}), 400

        pipeline = get_cv_pipeline()
        result = pipeline.process_frame(frame)

        if result is None:
            return jsonify({"success": True, "detected": False, "message": "No face detected."})

        # Serialize landmarks as nested list for JSON (truncate to 468 standard points)
        landmarks_json = None
        if result.get("landmarks") is not None:
            lm = result["landmarks"]
            landmarks_json = lm[:468].tolist() if hasattr(lm, 'tolist') else list(lm[:468])

        payload = {"success": True, "detected": True, **result}
        payload["landmarks"] = landmarks_json
        return jsonify(payload)

    except Exception as exc:
        LOGGER.exception("CV analysis failed.")
        return jsonify({"success": False, "error": str(exc)}), 500


# ---- Generate Plan ----
@app.post("/api/plan/generate")
def generate_plan():
    data = request.get_json(force=True)
    user_id = data.get("user_id", "anonymous")
    cv_data = data.get("cv_data", None)

    profile = PROFILES.get(user_id, {"first_name": "User"})
    assessment = ASSESSMENTS.get(user_id, {"total_score": 0, "severity": "Minimal"})

    # Analyze interview transcripts if available
    transcripts = TRANSCRIPTS.get(user_id, [])
    interview_analysis = analyze_interview_transcripts(transcripts)

    # Try LLM-powered analysis first
    llm_result = llm_analyze_user_data(
        profile, assessment, cv_data, transcripts, interview_analysis
    )

    if llm_result.get("llm_generated"):
        # Use LLM-generated plan, augmented with standard resources
        plan = {
            "profile_summary": llm_result.get("summary", ""),
            "stress_level": llm_result.get("stress_level", assessment.get("severity", "Minimal")),
            "stress_insights": llm_result.get("stress_insights", []),
            "coping_steps": llm_result.get("coping_steps", []),
            "reminders": llm_result.get("reminders", []),
            "resources": [
                {"name": "988 Suicide & Crisis Lifeline", "detail": "Call or text 988"},
                {"name": "Crisis Text Line", "detail": "Text HOME to 741741"},
                {"name": "NAMI Helpline", "detail": "1-800-950-NAMI (6264)"},
                {"name": "MentalHealth.gov", "detail": "https://www.mentalhealth.gov"},
            ],
            "advice": llm_result.get("advice", ""),
            "interview_analysis": interview_analysis if interview_analysis else None,
            "llm_generated": True,
            "risk_assessment": llm_result.get("risk_assessment", "low"),
            "generated_at": datetime.now().isoformat(),
        }
    else:
        # Fallback to heuristic-based plan
        plan = generate_personal_plan(profile, assessment, cv_data, interview_analysis)
        plan["llm_generated"] = False

    PLANS[user_id] = plan
    return jsonify({"success": True, **plan})


@app.get("/api/plan/<user_id>")
def get_plan(user_id):
    plan = PLANS.get(user_id)
    if plan:
        return jsonify({"success": True, **plan})
    return jsonify({"success": False, "error": "No plan found."}), 404


# ---- Dashboard ----
@app.get("/api/dashboard/<user_id>")
def get_dashboard(user_id):
    """Aggregate all user data into one dashboard response."""
    profile = PROFILES.get(user_id, {})
    assessment = ASSESSMENTS.get(user_id, {})
    transcripts = TRANSCRIPTS.get(user_id, [])
    plan = PLANS.get(user_id, {})
    interview_analysis = analyze_interview_transcripts(transcripts) if transcripts else {}

    return jsonify({
        "success": True,
        "profile": profile,
        "assessment": assessment,
        "interview": {
            "transcript_count": len(transcripts),
            "transcripts": transcripts,
            "analysis": interview_analysis,
        },
        "plan": plan,
        "generated_at": datetime.now().isoformat(),
    })


# ---- Health Check ----
@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
