from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import DB_PATH
from .models import Activity, HealthMetrics, WeeklySummary
from .utils import classify_sport, build_weekly_summaries

_SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id INTEGER PRIMARY KEY,
    sport_type TEXT NOT NULL DEFAULT '',
    activity_type TEXT NOT NULL DEFAULT '',
    start_time TEXT,
    duration_seconds REAL DEFAULT 0,
    distance_meters REAL DEFAULT 0,
    avg_hr REAL,
    max_hr REAL,
    hr_zones TEXT,
    calories REAL,
    avg_pace_min_per_km REAL,
    avg_speed_kmh REAL,
    avg_power REAL,
    normalized_power REAL,
    tss REAL,
    training_effect_aerobic REAL,
    training_effect_anaerobic REAL,
    elevation_gain REAL,
    avg_cadence REAL,
    activity_name TEXT DEFAULT '',
    description TEXT DEFAULT '',
    raw_json TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS health_metrics (
    metric_date TEXT PRIMARY KEY,
    resting_hr INTEGER,
    hrv_weekly_avg REAL,
    hrv_last_night REAL,
    hrv_status TEXT,
    sleep_score INTEGER,
    sleep_duration_seconds INTEGER,
    deep_sleep_seconds INTEGER,
    rem_sleep_seconds INTEGER,
    body_battery_high INTEGER,
    body_battery_low INTEGER,
    stress_avg INTEGER,
    training_readiness INTEGER,
    vo2_max_running REAL,
    vo2_max_cycling REAL,
    weight_kg REAL,
    body_fat_pct REAL
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_type TEXT NOT NULL,
    synced_at TEXT NOT NULL,
    records_count INTEGER DEFAULT 0
);
"""


class Database:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Activities ──

    def upsert_activity(self, a: Activity) -> None:
        self.conn.execute(
            """
            INSERT INTO activities (
                activity_id, sport_type, activity_type, start_time,
                duration_seconds, distance_meters, avg_hr, max_hr, hr_zones,
                calories, avg_pace_min_per_km, avg_speed_kmh,
                avg_power, normalized_power, tss,
                training_effect_aerobic, training_effect_anaerobic,
                elevation_gain, avg_cadence, activity_name, description, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
                sport_type=excluded.sport_type,
                activity_type=excluded.activity_type,
                start_time=excluded.start_time,
                duration_seconds=excluded.duration_seconds,
                distance_meters=excluded.distance_meters,
                avg_hr=excluded.avg_hr,
                max_hr=excluded.max_hr,
                hr_zones=excluded.hr_zones,
                calories=excluded.calories,
                avg_pace_min_per_km=excluded.avg_pace_min_per_km,
                avg_speed_kmh=excluded.avg_speed_kmh,
                avg_power=excluded.avg_power,
                normalized_power=excluded.normalized_power,
                tss=excluded.tss,
                training_effect_aerobic=excluded.training_effect_aerobic,
                training_effect_anaerobic=excluded.training_effect_anaerobic,
                elevation_gain=excluded.elevation_gain,
                avg_cadence=excluded.avg_cadence,
                activity_name=excluded.activity_name,
                description=excluded.description,
                raw_json=excluded.raw_json
            """,
            (
                a.activity_id,
                a.sport_type,
                a.activity_type,
                a.start_time.isoformat() if a.start_time else None,
                a.duration_seconds,
                a.distance_meters,
                a.avg_hr,
                a.max_hr,
                json.dumps(a.hr_zones) if a.hr_zones else None,
                a.calories,
                a.avg_pace_min_per_km,
                a.avg_speed_kmh,
                a.avg_power,
                a.normalized_power,
                a.tss,
                a.training_effect_aerobic,
                a.training_effect_anaerobic,
                a.elevation_gain,
                a.avg_cadence,
                a.activity_name,
                a.description,
                a.raw_json,
            ),
        )
        self.conn.commit()

    def get_activities(self, since_days: int = 90) -> list[Activity]:
        cutoff = (datetime.now() - timedelta(days=since_days)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM activities WHERE start_time >= ? ORDER BY start_time DESC",
            (cutoff,),
        ).fetchall()
        return [self._row_to_activity(r) for r in rows]

    def get_recent_activities(self, limit: int = 14) -> list[Activity]:
        rows = self.conn.execute(
            "SELECT * FROM activities ORDER BY start_time DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_activity(r) for r in rows]

    def get_last_sync_time(self, sync_type: str) -> datetime | None:
        row = self.conn.execute(
            "SELECT synced_at FROM sync_log WHERE sync_type = ? ORDER BY synced_at DESC LIMIT 1",
            (sync_type,),
        ).fetchone()
        if row:
            return datetime.fromisoformat(row["synced_at"])
        return None

    def log_sync(self, sync_type: str, count: int) -> None:
        self.conn.execute(
            "INSERT INTO sync_log (sync_type, synced_at, records_count) VALUES (?, ?, ?)",
            (sync_type, datetime.now().isoformat(), count),
        )
        self.conn.commit()

    def activity_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM activities").fetchone()
        return row["cnt"]

    # ── Health Metrics ──

    def upsert_health(self, h: HealthMetrics) -> None:
        self.conn.execute(
            """
            INSERT INTO health_metrics (
                metric_date, resting_hr, hrv_weekly_avg, hrv_last_night, hrv_status,
                sleep_score, sleep_duration_seconds, deep_sleep_seconds, rem_sleep_seconds,
                body_battery_high, body_battery_low, stress_avg, training_readiness,
                vo2_max_running, vo2_max_cycling, weight_kg, body_fat_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(metric_date) DO UPDATE SET
                resting_hr=excluded.resting_hr,
                hrv_weekly_avg=excluded.hrv_weekly_avg,
                hrv_last_night=excluded.hrv_last_night,
                hrv_status=excluded.hrv_status,
                sleep_score=excluded.sleep_score,
                sleep_duration_seconds=excluded.sleep_duration_seconds,
                deep_sleep_seconds=excluded.deep_sleep_seconds,
                rem_sleep_seconds=excluded.rem_sleep_seconds,
                body_battery_high=excluded.body_battery_high,
                body_battery_low=excluded.body_battery_low,
                stress_avg=excluded.stress_avg,
                training_readiness=excluded.training_readiness,
                vo2_max_running=excluded.vo2_max_running,
                vo2_max_cycling=excluded.vo2_max_cycling,
                weight_kg=excluded.weight_kg,
                body_fat_pct=excluded.body_fat_pct
            """,
            (
                h.metric_date.isoformat(),
                h.resting_hr,
                h.hrv_weekly_avg,
                h.hrv_last_night,
                h.hrv_status,
                h.sleep_score,
                h.sleep_duration_seconds,
                h.deep_sleep_seconds,
                h.rem_sleep_seconds,
                h.body_battery_high,
                h.body_battery_low,
                h.stress_avg,
                h.training_readiness,
                h.vo2_max_running,
                h.vo2_max_cycling,
                h.weight_kg,
                h.body_fat_pct,
            ),
        )
        self.conn.commit()

    def get_health_metrics(self, since_days: int = 90) -> list[HealthMetrics]:
        cutoff = (date.today() - timedelta(days=since_days)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM health_metrics WHERE metric_date >= ? ORDER BY metric_date DESC",
            (cutoff,),
        ).fetchall()
        return [self._row_to_health(r) for r in rows]

    def health_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM health_metrics"
        ).fetchone()
        return row["cnt"]

    # ── Weekly Summaries ──

    def get_weekly_summaries(self, weeks: int = 8) -> list[WeeklySummary]:
        cutoff = (datetime.now() - timedelta(weeks=weeks)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM activities WHERE start_time >= ? ORDER BY start_time ASC",
            (cutoff,),
        ).fetchall()

        activities = [self._row_to_activity(r) for r in rows]
        return build_weekly_summaries(activities)

    # ── Helpers ──

    @staticmethod
    def _row_to_activity(row: sqlite3.Row) -> Activity:
        d = dict(row)
        if d.get("start_time"):
            d["start_time"] = datetime.fromisoformat(d["start_time"])
        if d.get("hr_zones") and isinstance(d["hr_zones"], str):
            try:
                d["hr_zones"] = json.loads(d["hr_zones"])
            except json.JSONDecodeError:
                d["hr_zones"] = None
        return Activity(**d)

    @staticmethod
    def _row_to_health(row: sqlite3.Row) -> HealthMetrics:
        d = dict(row)
        if d.get("metric_date"):
            d["metric_date"] = date.fromisoformat(d["metric_date"])
        return HealthMetrics(**d)

