from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from datetime import date, datetime, timedelta

from garminconnect import Garmin
from rich.progress import Progress, SpinnerColumn, TextColumn

from .config import SESSION_DIR, get_garmin_credentials
from .database import Database
from .models import Activity, HealthMetrics

logger = logging.getLogger(__name__)

_client_instance = None


def _prompt_mfa() -> str:
    """Prompt the user for a Garmin MFA code in the terminal."""
    import typer

    return typer.prompt("Enter Garmin MFA/2FA code")


def _get_client() -> Garmin:
    global _client_instance
    if _client_instance is None:
        email, password = get_garmin_credentials()
        if not email or not password:
            raise RuntimeError("Garmin credentials not found. Run 'coach login' first.")
        client = Garmin(email=email, password=password, prompt_mfa=_prompt_mfa)
        token_path = str(SESSION_DIR)
        try:
            client.login(tokenstore=token_path)
        except Exception:
            client.login()
            client.garth.dump(token_path)
        _client_instance = client
    return _client_instance


def _parse_activity(raw: dict) -> Activity:
    start = None
    if raw.get("startTimeLocal"):
        try:
            start = datetime.fromisoformat(raw["startTimeLocal"])
        except (ValueError, TypeError):
            pass

    avg_pace = None
    avg_speed = raw.get("averageSpeed")
    if avg_speed and avg_speed > 0:
        avg_speed_kmh = avg_speed * 3.6
        avg_pace = 60.0 / avg_speed_kmh if avg_speed_kmh > 0 else None
    else:
        avg_speed_kmh = None

    return Activity(
        activity_id=raw["activityId"],
        sport_type=raw.get("activityType", {}).get("typeKey", ""),
        activity_type=raw.get("activityType", {}).get("typeKey", ""),
        start_time=start,
        duration_seconds=raw.get("duration", 0) or 0,
        distance_meters=raw.get("distance", 0) or 0,
        avg_hr=raw.get("averageHR"),
        max_hr=raw.get("maxHR"),
        calories=raw.get("calories"),
        avg_pace_min_per_km=avg_pace,
        avg_speed_kmh=avg_speed_kmh,
        avg_power=raw.get("avgPower"),
        normalized_power=raw.get("normPower"),
        tss=raw.get("trainingStressScore"),
        training_effect_aerobic=raw.get("aerobicTrainingEffect"),
        training_effect_anaerobic=raw.get("anaerobicTrainingEffect"),
        elevation_gain=raw.get("elevationGain"),
        avg_cadence=raw.get("averageRunningCadenceInStepsPerMinute")
        or raw.get("averageBikingCadenceInRevPerMinute"),
        activity_name=raw.get("activityName", ""),
        description=raw.get("description", "") or "",
        raw_json=json.dumps(raw, default=str),
    )


def _safe_get(func, *args, default=None, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.debug("API call %s failed: %s", func.__name__, e)
        return default


def _as_dict(val, index: int = 0) -> dict:
    """Garmin API sometimes returns a list instead of a dict. Normalize it."""
    if isinstance(val, dict):
        return val
    if isinstance(val, list) and len(val) > index and isinstance(val[index], dict):
        return val[index]
    return {}


def _fetch_raw_activities(lookback_days: int = 90) -> list[dict]:
    """Fetch raw activity data from Garmin API."""
    client = _get_client()
    start_date = (date.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = date.today().strftime("%Y-%m-%d")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        progress.add_task("Fetching activities from Garmin Connect...", total=None)
        return client.get_activities_by_date(start_date, end_date)


def _process_raw_activities(raw_activities: list[dict], limit: int | None = None) -> list[Activity]:
    """Convert raw activity data to Activity objects."""
    activities = []
    for raw in raw_activities[:limit]:
        try:
            activity = _parse_activity(raw)

            client = _get_client()
            hr_zones = _safe_get(
                client.get_activity_hr_in_timezones, str(activity.activity_id)
            )
            if hr_zones:
                activity.hr_zones = hr_zones

            activities.append(activity)
        except Exception as e:
            logger.warning("Failed to process activity %s: %s", raw.get("activityId"), e)

    return activities


def _fetch_health_metrics_for_day(client: Garmin, ds: str) -> HealthMetrics:
    """Fetch all health metrics for a single day from Garmin API concurrently."""
    current = datetime.strptime(ds, "%Y-%m-%d").date()
    metrics = HealthMetrics(metric_date=current)

    # Define all API calls as functions for concurrent execution
    def get_stats():
        return _as_dict(_safe_get(client.get_stats, ds, default={}))

    def get_sleep():
        return _as_dict(_safe_get(client.get_sleep_data, ds, default={}))

    def get_hrv():
        return _as_dict(_safe_get(client.get_hrv_data, ds, default={}))

    def get_body_battery():
        return _safe_get(client.get_body_battery, ds, default=[])

    def get_stress():
        return _as_dict(_safe_get(client.get_stress_data, ds, default={}))

    def get_readiness():
        return _as_dict(_safe_get(client.get_training_readiness, ds, default={}))

    def get_max_metrics():
        return _as_dict(_safe_get(client.get_max_metrics, ds, default={}))

    def get_body_composition():
        return _as_dict(_safe_get(client.get_body_composition, ds, default={}))

    # Execute all API calls concurrently using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(get_stats): 'stats',
            executor.submit(get_sleep): 'sleep',
            executor.submit(get_hrv): 'hrv',
            executor.submit(get_body_battery): 'bb',
            executor.submit(get_stress): 'stress',
            executor.submit(get_readiness): 'readiness',
            executor.submit(get_max_metrics): 'max_met',
            executor.submit(get_body_composition): 'body',
        }

        results = {}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                logger.debug("API call %s failed for %s: %s", key, ds, e)
                results[key] = None

    # Process results
    stats = results.get('stats')
    if stats:
        metrics.resting_hr = stats.get("restingHeartRate")

    sleep = results.get('sleep')
    if sleep:
        daily = _as_dict(sleep.get("dailySleepDTO", {}))
        metrics.sleep_score = _as_dict(
            _as_dict(daily.get("sleepScores", {})).get("overall", {})
        ).get("value")
        metrics.sleep_duration_seconds = daily.get("sleepTimeSeconds")
        metrics.deep_sleep_seconds = daily.get("deepSleepSeconds")
        metrics.rem_sleep_seconds = daily.get("remSleepSeconds")

    hrv = results.get('hrv')
    if hrv:
        summary = _as_dict(hrv.get("hrvSummary", {}))
        metrics.hrv_weekly_avg = summary.get("weeklyAvg")
        metrics.hrv_last_night = summary.get("lastNight")
        metrics.hrv_status = summary.get("status")

    bb = results.get('bb')
    if bb is not None:
        bb_entry = _as_dict(bb)
        if bb_entry:
            metrics.body_battery_high = bb_entry.get("charged")
            metrics.body_battery_low = bb_entry.get("drained")

    stress = results.get('stress')
    if stress:
        metrics.stress_avg = stress.get("overallStressLevel")

    readiness = results.get('readiness')
    if readiness:
        metrics.training_readiness = readiness.get(
            "score"
        ) or readiness.get("trainingReadinessScore")

    max_met = results.get('max_met')
    if max_met:
        generic = _as_dict(max_met.get("generic", {}))
        cycling = _as_dict(max_met.get("cycling", {}))
        if generic:
            metrics.vo2_max_running = generic.get("vo2MaxPreciseValue")
        if cycling:
            metrics.vo2_max_cycling = cycling.get("vo2MaxPreciseValue")

    body = results.get('body')
    if body:
        metrics.weight_kg = body.get("weight")
        if metrics.weight_kg and metrics.weight_kg > 1000:
            metrics.weight_kg = metrics.weight_kg / 1000.0
        metrics.body_fat_pct = body.get("bodyFat")

    return metrics


def _fetch_health_metrics_list(lookback_days: int = 14, max_workers: int = 4) -> list[HealthMetrics]:
    """Fetch health metrics from Garmin API concurrently."""
    client = _get_client()
    metrics_list = []

    end = date.today()
    start = end - timedelta(days=lookback_days)
    
    # Generate all date strings
    date_strings = [
        (start + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        for day_offset in range(lookback_days)
    ]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        task = progress.add_task("Fetching health metrics...", total=lookback_days)
        
        # Use ThreadPoolExecutor for concurrent API calls
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_date = {
                executor.submit(_fetch_health_metrics_for_day, client, ds): ds 
                for ds in date_strings
            }
            
            # Process completed tasks as they finish
            for future in as_completed(future_to_date):
                ds = future_to_date[future]
                try:
                    metrics = future.result()
                    metrics_list.append(metrics)
                except Exception as e:
                    logger.warning("Failed health metrics for %s: %s", ds, e)
                
                progress.advance(task)

    return metrics_list


def sync_activities(db: Database, lookback_days: int = 90) -> int:
    raw_activities = _fetch_raw_activities(lookback_days)
    activities = _process_raw_activities(raw_activities)

    count = 0
    for activity in activities:
        try:
            db.upsert_activity(activity)
            count += 1
        except Exception as e:
            logger.warning("Failed to upsert activity %s: %s", activity.activity_id, e)

    db.log_sync("activities", count)
    return count


def sync_health(db: Database, lookback_days: int = 14, max_workers: int = 4) -> int:
    metrics_list = _fetch_health_metrics_list(lookback_days, max_workers)

    count = 0
    for metrics in metrics_list:
        try:
            db.upsert_health(metrics)
            count += 1
        except Exception as e:
            logger.warning("Failed to upsert health metrics for %s: %s", metrics.metric_date, e)

    db.log_sync("health", count)
    return count


def get_recent_activities(lookback_days: int = 90, limit: int = 14) -> list[Activity]:
    """Fetch recent activities directly from Garmin API without storing in DB."""
    raw_activities = _fetch_raw_activities(lookback_days)
    return _process_raw_activities(raw_activities, limit=limit)


def get_health_metrics(lookback_days: int = 14, max_workers: int = 4) -> list[HealthMetrics]:
    """Fetch health metrics directly from Garmin API without storing in DB.
    
    Uses concurrent fetching to speed up the process.
    """
    metrics_list = _fetch_health_metrics_list(lookback_days, max_workers)
    return sorted(metrics_list, key=lambda m: m.metric_date, reverse=True)


def register_tools(mcp):
    @mcp.tool()
    def sync_garmin_data() -> str:
        """Sync latest activities and health data from Garmin Connect."""
        from datetime import datetime, timedelta
        db = Database()
        
        now = datetime.now()
        last_act_sync = db.get_last_sync_time("activities")
        last_health_sync = db.get_last_sync_time("health")
        
        act_count = 0
        if not last_act_sync or (now - last_act_sync) > timedelta(hours=1):
            act_count = sync_activities(db, lookback_days=90)
        
        health_count = 0
        if not last_health_sync or (now - last_health_sync) > timedelta(hours=1):
            health_count = sync_health(db, lookback_days=90)
        
        db.close()
        if act_count == 0 and health_count == 0:
            return "Data is already up to date (last synced less than 1 hour ago)."
        return f"Synced {act_count} activities and {health_count} health records from Garmin Connect."
    
    return mcp
