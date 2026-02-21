from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas, crud, analytics
from ..database import get_db

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    responses={404: {"description": "Not found"}},
)


@router.get("/overview", response_model=schemas.DashboardOverviewResponse)
async def get_dashboard_overview(user_id: int, db: Session = Depends(get_db)):
    """
    Returns aggregated metrics and risk indices based on user's journal entries.
    """
    # Get last 7 days for averages explicitly
    recent_entries = crud.get_recent_journal_entries(db, user_id=user_id, days=7)
    
    # Get all entries (or a reasonable large limit) to calculate full streak
    all_entries = crud.get_journal_entries(db, user_id=user_id, skip=0, limit=1000)
    
    overview = analytics.generate_dashboard_metrics(
        recent_entries=recent_entries, 
        all_entries=all_entries
    )
    
    return overview
