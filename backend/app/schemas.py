from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

# --- User Schemas ---

class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# --- Journal Schemas ---

class JournalEntryBase(BaseModel):
    mood: int = Field(..., ge=1, le=10, description="Mood score (1-10)")
    anxiety: int = Field(..., ge=1, le=10, description="Anxiety score (1-10)")
    stress: int = Field(..., ge=1, le=10, description="Stress score (1-10)")
    energy: int = Field(..., ge=1, le=10, description="Energy score (1-10)")
    productivity: int = Field(..., ge=1, le=10, description="Productivity score (1-10)")
    sleep_hours: float = Field(..., ge=0, le=24, description="Hours of sleep")
    sleep_quality: int = Field(..., ge=1, le=10, description="Sleep quality (1-10)")
    social_connection: int = Field(..., ge=1, le=10, description="Social connection score (1-10)")
    journal_text: Optional[str] = None

class JournalEntryCreate(JournalEntryBase):
    user_id: int

class JournalEntryResponse(JournalEntryBase):
    id: int
    user_id: int
    date: datetime

    class Config:
        from_attributes = True


# --- Chat Schemas ---

class ChatRequest(BaseModel):
    user_id: int
    message: str

class ChatResponse(BaseModel):
    reply: str


# --- Dashboard Schemas ---

class DashboardOverviewResponse(BaseModel):
    avg_mood_7d: float
    avg_anxiety: float
    avg_stress: float
    avg_sleep: float
    most_frequent_mood_range: str
    journal_streak: int
    emotional_stability_index: float
    burnout_risk: str
    isolation_risk: str
