from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from .config import CONTEXT_FILE, load_config
from .models import Activity, HealthMetrics, WeeklySummary
from .utils import build_weekly_summaries


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h{m:02d}m"
    return f"{m}m"


def _fmt_pace(min_per_km: float | None) -> str:
    if not min_per_km or min_per_km <= 0:
        return "N/A"
    mins = int(min_per_km)
    secs = int((min_per_km - mins) * 60)
    return f"{mins}:{secs:02d}/km"


def _fmt_distance(meters: float) -> str:
    km = meters / 1000
    if km >= 10:
        return f"{km:.1f}km"
    return f"{km:.2f}km"


def _section(title: str, content: str) -> str:
    return f"## {title}\n\n{content}\n"


def build_athlete_profile(config_athlete, health: list[HealthMetrics]) -> str:
    lines = []
    if config_athlete.race_name:
        lines.append(f"- **Target race**: {config_athlete.race_name}")
    if config_athlete.race_date:
        try:
            rd = date.fromisoformat(config_athlete.race_date)
            days_out = (rd - date.today()).days
            lines.append(f"- **Race date**: {config_athlete.race_date} ({days_out} days away)")
        except ValueError:
            lines.append(f"- **Race date**: {config_athlete.race_date}")
    if config_athlete.experience:
        lines.append(f"- **Experience level**: {config_athlete.experience}")
    if config_athlete.max_weekly_hours:
        lines.append(f"- **Max weekly training hours**: {config_athlete.max_weekly_hours}")
    if config_athlete.goals:
        lines.append(f"- **Goals**: {config_athlete.goals}")
    if config_athlete.injury_history:
        lines.append(f"- **Injury history**: {', '.join(config_athlete.injury_history)}")

    recent = [h for h in health[:7] if h.vo2_max_running or h.vo2_max_cycling or h.weight_kg]
    if recent:
        latest = recent[0]
        if latest.vo2_max_running:
            lines.append(f"- **VO2 max (running)**: {latest.vo2_max_running:.1f}")
        if latest.vo2_max_cycling:
            lines.append(f"- **VO2 max (cycling)**: {latest.vo2_max_cycling:.1f}")
        if latest.weight_kg:
            lines.append(f"- **Weight**: {latest.weight_kg:.1f} kg")
        rhr_values = [h.resting_hr for h in recent if h.resting_hr]
        if rhr_values:
            lines.append(f"- **Resting HR (7d avg)**: {sum(rhr_values) / len(rhr_values):.0f} bpm")

    return "\n".join(lines) if lines else "No athlete profile configured."


def build_weekly_summary_table(weeks: list[WeeklySummary]) -> str:
    if not weeks:
        return "No training data available yet."

    lines = [
        "| Week | Swim | Bike | Run | Strength | Total Hours | TSS |",
        "|------|------|------|-----|----------|-------------|-----|",
    ]
    for w in weeks:
        swim = f"{w.swim_hours:.1f}h / {w.swim_km:.1f}km ({w.swim_sessions}x)" if w.swim_sessions else "-"
        bike = f"{w.bike_hours:.1f}h / {w.bike_km:.0f}km ({w.bike_sessions}x)" if w.bike_sessions else "-"
        run = f"{w.run_hours:.1f}h / {w.run_km:.1f}km ({w.run_sessions}x)" if w.run_sessions else "-"
        strength = f"{w.strength_sessions}x" if w.strength_sessions else "-"
        tss = f"{w.total_tss:.0f}" if w.total_tss else "-"
        lines.append(
            f"| {w.week_start} | {swim} | {bike} | {run} | {strength} | {w.total_hours:.1f} | {tss} |"
        )

    return "\n".join(lines)


def build_training_load(weeks: list[WeeklySummary]) -> str:
    if len(weeks) < 2:
        return "Not enough data for training load analysis."

    lines = []

    recent_hours = [w.total_hours for w in weeks[:1]]
    acute = sum(recent_hours) / max(len(recent_hours), 1)

    chronic_hours = [w.total_hours for w in weeks[:6]]
    chronic = sum(chronic_hours) / max(len(chronic_hours), 1)

    if chronic > 0:
        ratio = acute / chronic
        lines.append(f"- **Acute load (this week)**: {acute:.1f} hours")
        lines.append(f"- **Chronic load (6-week avg)**: {chronic:.1f} hours/week")
        lines.append(f"- **Acute:Chronic ratio**: {ratio:.2f}")
        if ratio > 1.3:
            lines.append("- **Warning**: Ratio >1.3 — elevated injury/overtraining risk")
        elif ratio < 0.8:
            lines.append("- **Note**: Ratio <0.8 — detraining risk if sustained")
        else:
            lines.append("- **Status**: Ratio in safe zone (0.8–1.3)")
    else:
        lines.append(f"- **This week**: {acute:.1f} hours")
        lines.append("- Not enough historical data for load ratio")

    hour_trend = [w.total_hours for w in reversed(weeks)]
    if len(hour_trend) >= 3:
        trend_str = " → ".join(f"{h:.1f}" for h in hour_trend[-6:])
        lines.append(f"- **Weekly hours trend**: {trend_str}")

    return "\n".join(lines)


def build_recent_activities(activities: list[Activity]) -> str:
    if not activities:
        return "No recent activities."

    lines = []
    for a in activities[:14]:
        date_str = a.start_time.strftime("%Y-%m-%d %H:%M") if a.start_time else "?"
        sport = a.sport_type or a.activity_type or "unknown"
        dur = _fmt_duration(a.duration_seconds)
        dist = _fmt_distance(a.distance_meters) if a.distance_meters else ""

        detail_parts = []
        if a.avg_hr:
            detail_parts.append(f"avg HR {a.avg_hr:.0f}")
        if a.max_hr:
            detail_parts.append(f"max HR {a.max_hr:.0f}")
        if a.avg_pace_min_per_km and "run" in sport.lower():
            detail_parts.append(f"pace {_fmt_pace(a.avg_pace_min_per_km)}")
        if a.avg_speed_kmh and "cycl" in sport.lower():
            detail_parts.append(f"avg {a.avg_speed_kmh:.1f} km/h")
        if a.avg_power:
            detail_parts.append(f"power {a.avg_power:.0f}W")
        if a.normalized_power:
            detail_parts.append(f"NP {a.normalized_power:.0f}W")
        if a.tss:
            detail_parts.append(f"TSS {a.tss:.0f}")
        if a.training_effect_aerobic:
            detail_parts.append(f"TE(aero) {a.training_effect_aerobic:.1f}")
        if a.elevation_gain:
            detail_parts.append(f"elev +{a.elevation_gain:.0f}m")

        details = " | ".join(detail_parts)
        name = f" — *{a.activity_name}*" if a.activity_name else ""
        line = f"- **{date_str}** {sport} {dur} {dist}{name}"
        if details:
            line += f"\n  {details}"
        lines.append(line)

    return "\n".join(lines)


def build_health_trends(health: list[HealthMetrics]) -> str:
    if not health:
        return "No health data available."

    lines = []
    week = health[:7]

    # HRV
    hrv_values = [h.hrv_last_night for h in week if h.hrv_last_night]
    if hrv_values:
        avg_hrv = sum(hrv_values) / len(hrv_values)
        latest_status = next((h.hrv_status for h in week if h.hrv_status), None)
        status_str = f" (status: {latest_status})" if latest_status else ""
        lines.append(f"- **HRV (7d avg)**: {avg_hrv:.0f} ms{status_str}")

    # Sleep
    sleep_scores = [h.sleep_score for h in week if h.sleep_score]
    if sleep_scores:
        avg_sleep = sum(sleep_scores) / len(sleep_scores)
        lines.append(f"- **Sleep score (7d avg)**: {avg_sleep:.0f}/100")
    sleep_durations = [h.sleep_duration_seconds for h in week if h.sleep_duration_seconds]
    if sleep_durations:
        avg_dur = sum(sleep_durations) / len(sleep_durations) / 3600
        lines.append(f"- **Sleep duration (7d avg)**: {avg_dur:.1f} hours")

    # Body battery
    bb_high = [h.body_battery_high for h in week if h.body_battery_high is not None]
    bb_low = [h.body_battery_low for h in week if h.body_battery_low is not None]
    if bb_high:
        lines.append(f"- **Body battery high (7d avg)**: {sum(bb_high) / len(bb_high):.0f}")
    if bb_low:
        lines.append(f"- **Body battery low (7d avg)**: {sum(bb_low) / len(bb_low):.0f}")

    # Stress
    stress_vals = [h.stress_avg for h in week if h.stress_avg is not None]
    if stress_vals:
        lines.append(f"- **Stress (7d avg)**: {sum(stress_vals) / len(stress_vals):.0f}")

    # Training readiness
    tr_vals = [h.training_readiness for h in week if h.training_readiness is not None]
    if tr_vals:
        lines.append(f"- **Training readiness (7d avg)**: {sum(tr_vals) / len(tr_vals):.0f}")

    # Fatigue flags
    flags = _detect_fatigue_flags(health)
    if flags:
        lines.append("\n### Fatigue Flags")
        for flag in flags:
            lines.append(f"- ⚠ {flag}")

    return "\n".join(lines) if lines else "No health trends available."


def _detect_fatigue_flags(health: list[HealthMetrics]) -> list[str]:
    flags = []
    week = health[:7]

    sleep_scores = [h.sleep_score for h in week if h.sleep_score]
    if sleep_scores and sum(s < 60 for s in sleep_scores) >= 3:
        flags.append("Poor sleep (score < 60) on 3+ days this week")

    stress_vals = [h.stress_avg for h in week if h.stress_avg is not None]
    if stress_vals and sum(stress_vals) / len(stress_vals) > 50:
        flags.append("Elevated average stress level this week")

    bb_high = [h.body_battery_high for h in week if h.body_battery_high is not None]
    if bb_high and sum(bb_high) / len(bb_high) < 50:
        flags.append("Low body battery — inadequate recovery")

    tr_vals = [h.training_readiness for h in week if h.training_readiness is not None]
    if tr_vals and sum(tr_vals) / len(tr_vals) < 40:
        flags.append("Low training readiness — consider reducing load")

    if len(health) >= 14:
        hrv_this = [h.hrv_last_night for h in health[:7] if h.hrv_last_night]
        hrv_last = [h.hrv_last_night for h in health[7:14] if h.hrv_last_night]
        if hrv_this and hrv_last:
            avg_this = sum(hrv_this) / len(hrv_this)
            avg_last = sum(hrv_last) / len(hrv_last)
            if avg_last > 0 and (avg_this - avg_last) / avg_last < -0.15:
                flags.append("HRV declining >15% vs previous week — possible overreaching")

    return flags






def build_context(output_path: Path | None = None, use_db: bool = True) -> Path:
    """Build training context from either Garmin API or local database.
    
    Args:
        output_path: Optional path for output file (default: training_context.md)
        use_db: If True, use local database. If False, fetch directly from Garmin API.
    """
    cfg = load_config()
    
    if use_db:
        from .database import Database
        db = Database()
        health = db.get_health_metrics(since_days=90)
        activities = db.get_recent_activities(limit=14)
        weeks = db.get_weekly_summaries(weeks=8)
        db.close()
        data_source = "Last sync data"
    else:
        from .garmin_client import get_recent_activities, get_health_metrics
        health = get_health_metrics(lookback_days=90)
        activities = get_recent_activities(lookback_days=90, limit=14)
        weeks = build_weekly_summaries(activities)
        data_source = "Live data from Garmin Connect"

    today = date.today().isoformat()
    sections = [
        f"# Training Context — {today}\n",
        f"*Auto-generated by personal-ai-coach. {data_source}.*\n",
        _section("Athlete Profile", build_athlete_profile(cfg.athlete, health)),
        _section("Weekly Training Summary (last 8 weeks)", build_weekly_summary_table(weeks)),
        _section("Training Load Analysis", build_training_load(weeks)),
        _section("Recent Activities (last 14)", build_recent_activities(activities)),
        _section("Health & Recovery Trends", build_health_trends(health)),
    ]

    # Append reference to detailed athlete docs if they exist
    athlete_docs = Path("athlete_docs")
    if athlete_docs.is_dir():
        docs = sorted(athlete_docs.glob("*.md"))
        if docs:
            ref_lines = [
                "For full athlete profile, race targets, fueling science, "
                "and coaching guidelines see:",
            ]
            for doc in docs:
                ref_lines.append(f"- `{doc}`")
            sections.append(_section("Detailed Athlete Documentation", "\n".join(ref_lines)))

    content = "\n".join(sections)
    out = output_path or CONTEXT_FILE
    out.write_text(content, encoding="utf-8")
    return out
