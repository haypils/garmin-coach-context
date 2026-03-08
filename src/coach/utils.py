from __future__ import annotations

from datetime import date, timedelta
from typing import List

from .models import Activity, WeeklySummary


def classify_sport(sport_type: str) -> str:
    """Classify a raw Garmin sport/activity type into a simple category."""
    s = sport_type.lower()
    if "swim" in s or "pool" in s:
        return "swim"
    if "cycl" in s or "bike" in s or "bik" in s:
        return "bike"
    if "run" in s or "jog" in s or "trail" in s or "treadmill" in s:
        return "run"
    if "strength" in s or "weight" in s or "yoga" in s or "pilates" in s:
        return "strength"
    return "other"


def build_weekly_summaries(activities: List[Activity]) -> List[WeeklySummary]:
    """Build weekly summaries from a list of activities.

    The result is sorted newest-first.
    """
    if not activities:
        return []

    weeks: dict[date, WeeklySummary] = {}
    for a in activities:
        if not a.start_time:
            continue
        d = a.start_time.date()
        week_start = d - timedelta(days=d.weekday())
        if week_start not in weeks:
            weeks[week_start] = WeeklySummary(week_start=week_start)
        w = weeks[week_start]
        hours = a.duration_seconds / 3600
        km = a.distance_meters / 1000

        sport = classify_sport(a.sport_type or a.activity_type)
        if sport == "swim":
            w.swim_hours += hours
            w.swim_km += km
            w.swim_sessions += 1
        elif sport == "bike":
            w.bike_hours += hours
            w.bike_km += km
            w.bike_sessions += 1
        elif sport == "run":
            w.run_hours += hours
            w.run_km += km
            w.run_sessions += 1
        elif sport == "strength":
            w.strength_sessions += 1
        else:
            w.other_sessions += 1

        w.total_hours += hours
        if a.tss:
            w.total_tss += a.tss

    return sorted(weeks.values(), key=lambda w: w.week_start, reverse=True)
