# MentraAI System Design Document

This document outlines the architecture, technology stack, directory structure, and API integration flows for the MentraAI application.

---

## 1. Overview and Technology Stack
MentraAI is a monolithic web application decoupled into a RESTful backend and a vanilla frontend. It provides users with a private AI therapist and a mood tracking journal, analyzing the telemetry to forecast burnout and isolation risks.

**Backend Frameworks:**
*   **Python 3.x**
*   **FastAPI:** High-performance async API routing framework.
*   **SQLAlchemy / SQLite:** ORM and lightweight relational database for persisting user profiles, chat sessions, and journal metrics.
*   **Pydantic:** Strict type enforcement and data validation for API requests and responses.
*   **Llama.cpp (Local LLM):** Connects to a locally hosted `llama-server` to generate private, therapeutic AI responses without relying on external APIs.

**Frontend Frameworks:**
*   **HTML5 / CSS3:** Semantic markup with a custom, vanilla CSS glassmorphism design system (utilizing variables for dark mode consistency).
*   **Vanilla JavaScript (ES6):** Handles async data fetching, DOM manipulation, and dynamic component rendering without the overhead of React or Vue.
*   **Chart.js:** Renders the dashboard telemetry via `<canvas>` elements.

---

## 2. Project Folder Structure

```text
PBL-II/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI entry point; CORS setup; Frontend static mounting
│   │   ├── config.py           # Application settings and environment variables
│   │   ├── database.py         # SQLAlchemy engine and session dependency generator
│   │   ├── models.py           # Relational SQL table definitions (User, JournalEntry, ChatSession)
│   │   ├── schemas.py          # Pydantic validation models (Create/Response schemas)
│   │   ├── crud.py             # Reusable database queries (Create, Read, Update, Delete)
│   │   ├── analytics.py        # Domain business logic (Calculates Streaks, Burnout, Stability)
│   │   ├── llm.py              # Outbound requests to the local llama-server
│   │   │
│   │   └── routers/            # Modular API endpoint definitions
│   │       ├── users.py        # /users routes
│   │       ├── chat.py         # /chat routes
│   │       ├── journal.py      # /journal and /entries routes
│   │       └── dashboard.py    # /dashboard routes
│   │
│   ├── mentra.db               # SQLite Database File
│   └── requirements.txt        # Python dependencies
│
└── frontend/                   # Statically mounted internally by FastAPI
    ├── index.html              # Landing page
    ├── users.html              # Multi-tenant profile creation and selection
    ├── dashboard.html          # Data visualization of journal telemetry
    ├── journal.html            # Core entry logger and historical viewer
    ├── chat.html               # Realtime AI Therapist interface
    │
    └── assets/
        ├── css/styles.css      # Global design system
        └── js/app.js           # Core client-side API logic and state management
```

---

## 3. API Endpoints

The backend is modularized using FastAPI's `APIRouter` to compartmentalize concerns.

### User Management (`/users`)
*   **`POST /users/`**
    *   **Payload:** `{"username": "string"}`
    *   **Behavior:** Creates a new user profile linked to future table rows.
*   **`GET /users/`**
    *   **Behavior:** Returns an array of all available user profiles.
*   **`GET /users/{user_id}`**
    *   **Behavior:** Fetches a specific user's metadata.

### Journaling (`/journal` & `/entries`)
*   **`POST /journal`**
    *   **Payload:** Includes `user_id`, text, and 1-10 psychological scales (mood, anxiety, stress, sleep, etc).
    *   **Behavior:** Saves a new daily reflection telemetry row to the database.
*   **`GET /entries?user_id={id}`**
    *   **Behavior:** Returns the complete historical array of journal entries for the specified user ID.
*   **`GET /entries/last7?user_id={id}`**
    *   **Behavior:** Queries the database using a 7-day cutoff `timedelta` to supply isolated visualization data for the dashboard charts.

### Dashboard Analytics (`/dashboard`)
*   **`GET /dashboard/overview?user_id={id}`**
    *   **Behavior:** Fetches the user's data and passes it through `analytics.py` to calculate moving averages, psychological streak durations, Emotional Stability variance, Burnout Risk, and Isolation Risk. 

### Chat Interface (`/chat`)
*   **`POST /chat`**
    *   **Payload:** `{"user_id": int, "message": "string"}`
    *   **Behavior:** Forwards the user's message to the local `llama-server` wrapped in a therapeutic system prompt, waits for generation, saves both the user payload and the AI delta to the database, and returns the AI's reply to the frontend DOM.

---

## 4. Frontend Connection & Execution Flow

The frontend connects to the backend in a highly deliberate loop heavily relying on `localStorage` state isolation:

1.  **FastAPI Mounting:** Instead of opening the UI pages via isolated `file:///` URLs (which causes modern browsers to restrict local memory), the `frontend` folder is mounted directly to the FastAPI backend inside `main.py`. Exploring to `http://localhost:8000/` serves the frontend templates natively.
2.  **State Verification (`app.js`):** Every HTML page loads `app.js`. When the script fires, it evaluates `requireUser()`. If the browser's persistent `localStorage` does not possess a valid `mentra_user_id`, the user is immediately redirected to `users.html` to prevent 404 validation crashes.
3.  **Data Fetching:** Once a user ID exists, the Javascript queries endpoints dynamically. For example, `initDashboard()` executes an asynchronous HTTP `fetch` to `http://localhost:8000/dashboard/overview?user_id=X`.
4.  **UI Hydration:** Upon `res.ok` (HTTP 200), the JSON arrays are unpacked. Standalone integers are shoved into `div.textContent` to populate the stats grid, while chronological JSON arrays are mutated into date strings and forwarded to the instantiation constructors of `Chart.js` canvas overlays. 

This strict separation ensures the Javascript is completely agnostic to backend infrastructure changes as long as the endpoint contracts remain the same.
