from sqlalchemy.orm import Session
from . import models, schemas
from datetime import datetime, timedelta

# --- User CRUD ---

def create_user(db: Session, user: schemas.UserCreate):
    db_user = models.User(username=user.username)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).offset(skip).limit(limit).all()


# --- Journal CRUD ---

def create_journal_entry(db: Session, entry: schemas.JournalEntryCreate):
    db_entry = models.JournalEntry(**entry.model_dump())
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry

def get_journal_entries(db: Session, user_id: int, skip: int = 0, limit: int = 100):
    return db.query(models.JournalEntry).filter(
        models.JournalEntry.user_id == user_id
    ).order_by(models.JournalEntry.date.desc()).offset(skip).limit(limit).all()

def get_recent_journal_entries(db: Session, user_id: int, days: int = 7):
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    return db.query(models.JournalEntry).filter(
        models.JournalEntry.user_id == user_id,
        models.JournalEntry.date >= cutoff_date
    ).order_by(models.JournalEntry.date.asc()).all()


# --- Chat CRUD ---

def create_chat_session(db: Session, user_id: int, user_message: str, ai_response: str):
    db_chat = models.ChatSession(
        user_id=user_id,
        user_message=user_message,
        ai_response=ai_response
    )
    db.add(db_chat)
    db.commit()
    db.refresh(db_chat)
    return db_chat

def get_chat_history(db: Session, user_id: int, skip: int = 0, limit: int = 50):
    return db.query(models.ChatSession).filter(
        models.ChatSession.user_id == user_id
    ).order_by(models.ChatSession.timestamp.desc()).offset(skip).limit(limit).all()
