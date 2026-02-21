import math
from typing import List, Dict, Any
from .models import JournalEntry
from datetime import datetime, timedelta

def calculate_emotional_stability(entries: List[JournalEntry]) -> float:
    """
    Standard deviation of mood over the provided entries.
    """
    if not entries or len(entries) < 2:
        return 0.0
    
    moods = [entry.mood for entry in entries]
    mean_mood = sum(moods) / len(moods)
    variance = sum((m - mean_mood) ** 2 for m in moods) / len(moods)
    return round(math.sqrt(variance), 2)


def calculate_burnout_risk(entries: List[JournalEntry]) -> str:
    """
    High if: avg stress > 7 AND avg energy < 4 AND avg sleep < 6
    """
    if not entries:
        return "Unknown"
        
    avg_stress = sum(e.stress for e in entries) / len(entries)
    avg_energy = sum(e.energy for e in entries) / len(entries)
    avg_sleep = sum(e.sleep_hours for e in entries) / len(entries)
    
    if avg_stress > 7 and avg_energy < 4 and avg_sleep < 6:
        return "High"
    elif avg_stress > 5 or avg_energy < 6 or avg_sleep < 7:
        return "Moderate"
    else:
        return "Low"


def calculate_isolation_risk(entries: List[JournalEntry]) -> str:
    """
    High if: avg anxiety > 7 AND avg social_connection < 4
    """
    if not entries:
        return "Unknown"
        
    avg_anxiety = sum(e.anxiety for e in entries) / len(entries)
    avg_social = sum(e.social_connection for e in entries) / len(entries)
    
    if avg_anxiety > 7 and avg_social < 4:
        return "High"
    elif avg_anxiety > 5 or avg_social < 6:
        return "Moderate"
    else:
        return "Low"


def calculate_journal_streak(entries: List[JournalEntry]) -> int:
    """
    Calculate consecutive daily entries counting back from today (or the most recent entry).
    Assumes entries are sorted by date ascending.
    """
    if not entries:
        return 0
        
    # Extract unique dates (ignoring time) and sort descending
    unique_dates = sorted(list(set(e.date.date() for e in entries)), reverse=True)
    
    if not unique_dates:
        return 0
        
    # Check if the most recent entry was today or yesterday to count as an active streak
    today = datetime.utcnow().date()
    if unique_dates[0] < today - timedelta(days=1):
        return 0
        
    streak = 1
    current_date = unique_dates[0]
    
    for dt in unique_dates[1:]:
        if current_date - dt == timedelta(days=1):
            streak += 1
            current_date = dt
        else:
            break
            
    return streak


def get_frequent_mood_range(entries: List[JournalEntry]) -> str:
    """
    1-3 = Low
    4-7 = Medium
    8-10 = High
    """
    if not entries:
        return "Unknown"
        
    avg_mood = sum(e.mood for e in entries) / len(entries)
    
    if avg_mood <= 3:
        return "Low"
    elif avg_mood <= 7:
        return "Medium"
    else:
        return "High"


def generate_dashboard_metrics(recent_entries: List[JournalEntry], all_entries: List[JournalEntry]) -> dict:
    """
    Generates all required metrics for the dashboard overview.
    Expects recent_entries to be the last 7 days for averages, 
    and all_entries for calculating the full streak.
    """
    if not recent_entries:
         return {
            "avg_mood_7d": 0.0,
            "avg_anxiety": 0.0,
            "avg_stress": 0.0,
            "avg_sleep": 0.0,
            "most_frequent_mood_range": "Unknown",
            "journal_streak": calculate_journal_streak(all_entries),
            "emotional_stability_index": 0.0,
            "burnout_risk": "Unknown",
            "isolation_risk": "Unknown"
        }
         
    num_entries = len(recent_entries)
    
    avg_mood = sum(e.mood for e in recent_entries) / num_entries
    avg_anxiety = sum(e.anxiety for e in recent_entries) / num_entries
    avg_stress = sum(e.stress for e in recent_entries) / num_entries
    avg_sleep = sum(e.sleep_hours for e in recent_entries) / num_entries

    return {
        "avg_mood_7d": round(avg_mood, 2),
        "avg_anxiety": round(avg_anxiety, 2),
        "avg_stress": round(avg_stress, 2),
        "avg_sleep": round(avg_sleep, 2),
        "most_frequent_mood_range": get_frequent_mood_range(recent_entries),
        "journal_streak": calculate_journal_streak(all_entries),
        "emotional_stability_index": calculate_emotional_stability(recent_entries),
        "burnout_risk": calculate_burnout_risk(recent_entries),
        "isolation_risk": calculate_isolation_risk(recent_entries)
    }
