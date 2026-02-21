# MentraAI Backend

This is the production-ready FastAPI backend for **MentraAI**, a mental health analytics and AI therapist system.

## Key Features

- **Modular Architecture**: Cleanly separated into configurations, database models, Pydantic schemas, CRUD operations, core logic, and API routes.
- **SQLite Database**: Persistent storage for journal entries and chat history via SQLAlchemy.
- **Advanced Analytics**: Computation of the Emotional Stability Index, Burnout Risk, Isolation Risk, and Journal Streaks.
- **Local LLM Integration**: Connects to a local `llama-server` to provide empathetic, CBT-guided responses while safely detecting and intercepting crisis keywords.
- **Asynchronous Operations**: Fully utilizes async patterns via `httpx` and `async/await` in endpoints.

---

## 📁 Project Structure

```text
backend/
├── app/
│   ├── main.py        # Application entry point and CORS configuration
│   ├── config.py      # App configurations mapped from env 
│   ├── database.py    # SQLAlchemy database setup
│   ├── models.py      # DB ORM models (JournalEntry, ChatSession)
│   ├── schemas.py     # Pydantic validation schemas
│   ├── crud.py        # Database manipulation logic
│   ├── analytics.py   # Mental health metrics and risk calculations
│   ├── llm.py         # Talk-to-LLM logic and safety overrides
│   └── routers/
│       ├── journal.py     # Endpoints for journaling
│       ├── chat.py        # Endpoints for chat sessions
│       ├── dashboard.py   # Endpoints for aggregated metrics
│       └── mood.py        # (Implicitly handled via the journal and dashboard API)
├── requirements.txt   # Dependencies
└── README.md
```

---

## 🛠 Prerequisites

- Python 3.9+
- A running instance of `llama.cpp` using the server mode (`llama-server`)

---

## 🚀 Setup & Installation

**1. Navigate to the backend directory**
```bash
cd backend
```

**2. Create a virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

---

## 🧠 Starting the Local LLM (llama-server)

You need to run a local LLM server compatible with the OpenAI API or `llama.cpp`'s completion endpoint on port `8080`.

Example using `llama.cpp`:
```bash
./llama-server -m path/to/your/model.gguf -c 2048 --port 8080
```

> **Note**: The backend expects the model to be exposed at `http://localhost:8080/completion`. This can be adjusted in `backend/app/config.py`.

---

## ▶️ Running the Application

Start the FastAPI application via Uvicorn:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- The API will be available at: `http://localhost:8000`
- Interactive API Documentation (Swagger UI): `http://localhost:8000/docs`
- Alternative Documentation (ReDoc): `http://localhost:8000/redoc`

---

## 📡 Endpoints Overview

- **`POST /journal`**: Save an entry (mood, stress, sleep, etc.)
- **`GET /journal/entries`**: Fetch all previous entries
- **`GET /journal/entries/last7`**: Fetch the recent 7 days to evaluate trends
- **`GET /dashboard/overview`**: Aggregated mental health insights based on analytics.py
- **`POST /chat`**: Send a message to the AI Therapist
