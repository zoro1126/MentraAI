from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    journal_entries = relationship("JournalEntry", back_populates="user")
    chat_sessions = relationship("ChatSession", back_populates="user")

class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
    
    # Core Metrics (1-10 scale)
    mood = Column(Integer, nullable=False)
    anxiety = Column(Integer, nullable=False)
    stress = Column(Integer, nullable=False)
    energy = Column(Integer, nullable=False)
    productivity = Column(Integer, nullable=False)
    
    # Sleep
    sleep_hours = Column(Float, nullable=False)
    sleep_quality = Column(Integer, nullable=False)
    
    # Social
    social_connection = Column(Integer, nullable=False)
    
    # Text entry
    journal_text = Column(Text, nullable=True)

    user = relationship("User", back_populates="journal_entries")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    user_message = Column(Text, nullable=False)
    ai_response = Column(Text, nullable=False)
    
    user = relationship("User", back_populates="chat_sessions")
