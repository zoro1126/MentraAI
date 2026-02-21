from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from .. import schemas, crud
from ..database import get_db

router = APIRouter(
    tags=["Journal"],
    responses={404: {"description": "Not found"}},
)


@router.post("/journal", response_model=schemas.JournalEntryResponse, status_code=201)
async def create_journal_entry(entry: schemas.JournalEntryCreate, db: Session = Depends(get_db)):
    """
    Accept structured daily metrics and save the entry.
    """
    return crud.create_journal_entry(db=db, entry=entry)


@router.get("/entries", response_model=List[schemas.JournalEntryResponse])
async def read_all_entries(user_id: int, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Return all journal entries (with pagination bounds).
    """
    entries = crud.get_journal_entries(db, user_id=user_id, skip=skip, limit=limit)
    return entries


@router.get("/entries/last7", response_model=List[schemas.JournalEntryResponse])
async def read_recent_entries(user_id: int, db: Session = Depends(get_db)):
    """
    Return last 7 days of entries.
    """
    entries = crud.get_recent_journal_entries(db, user_id=user_id, days=7)
    return entries
