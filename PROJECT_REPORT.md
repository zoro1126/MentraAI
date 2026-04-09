# MentraAI Project Report

## 1. Overview
MentraAI is a mental health assistant application designed to provide personalized wellness support through a combination of CV (Computer Vision), STT (Speech-to-Text), and LLM (Large Language Model) technologies. It features a structured interview system, emotion and stress tracking, and generates personalized mental health plans based on user data.

## 2. Technical Stack

| Component | Technology | Use Case |
| :--- | :--- | :--- |
| **Frontend** | HTML5, CSS3, JavaScript (Vanilla) | User interface and client-side logic |
| **Backend** | Python, Flask | API endpoints and orchestration |
| **Computer Vision** | MediaPipe, OpenCV | Facial landmark tracking, emotion, and stress analysis |
| **LLM Inference** | Llama-cpp-python | Local execution of GGUF models (e.g., Qwen2.5) |
| **Speech-to-Text** | Faster-Whisper, Web Speech API | Transcribing user responses and interview system |
| **Text-to-Speech** | pyttsx3, Web Speech API | AI verbal communication during interviews |

## 3. Project Architecture

The project follows a classic client-server architecture with modular processing pipelines in the backend.

### 3.1. Directory Structure
```text
MentraAI/
├── backend/
│   ├── app.py              # Main Flask server and API definitions
│   ├── cv_pipeline.py      # Facial analysis and emotion detection logic
│   ├── llm_pipeline.py     # LLM, STT, and TTS orchestration pipeline
│   ├── models/             # Directory for local AI models (GGUF, Whisper, etc.)
│   └── requirements.txt     # Python dependencies
├── frontend/
│   ├── index.html          # Main application UI
│   ├── styles.css          # Modern UI styling
│   ├── app.js              # Frontend logic, state management, and STT handling
│   └── particles.js        # Background animation effects
└── .venv/                  # Python virtual environment
```

### 3.2. Data Flow
1. **Input Collection**: The frontend captures camera frames (CV) and microphone audio (STT).
2. **Real-time CV**: Frames are sent to the `/api/cv/analyze_frame` endpoint, where `cv_pipeline.py` uses MediaPipe to extract facial landmarks and calculate emotions/stress in real-time.
3. **Structured Interview**: A conversational loop guides the user through PHQ-9 and wellness questions. Responses are saved as transcripts.
4. **LLM Orchestration**: The `llm_pipeline.py` provides the logic for generating responses using local GGUF models.
5. **Plan Generation**: All collected data (PHQ-9 score, CV history, interview transcripts) is fed into the LLM to generate a personalized wellness report via the `/api/plan/generate` endpoint.

## 4. Key Features
- **Emotion Tracking**: Real-time analysis of facial expressions (Calm, Anxious, Stressed, etc.).
- **PHQ-9 Assessment**: Standardized depression screening tool implemented digitally.
- **AI Wellness Interview**: Voice-interactive interview system using browser SpeechRecognition and local AI analysis.
- **Privacy-First**: Designed for local model execution to ensure user data remains private.
- **Resilient Pipeline**: Uses adaptive landmarks to handle facial occlusions (e.g., beards).
