"""
rules.py – California labor law calculation and validation helpers.

References:
  - CA Labor Code § 510  (daily/weekly overtime)
  - CA Labor Code § 512  (meal periods)
  - IWC Wage Orders      (rest periods)
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Dict, List


# ── Hour calculation ────────────────────────────────────────────────────────

def calc_hours(start: time, end: time, break_minutes: int = 0) -> float:
    """Return net worked hours for a shift (gross hours minus unpaid break)."""
    base = date.today()
    s = datetime.combine(base, start)
    e = datetime.combine(base, end)
    if e <= s:                          # overnight shift
        e += timedelta(days=1)
    net_minutes = (e - s).total_seconds() / 60.0 - max(0, break_minutes)
    return max(0.0, net_minutes / 60.0)


# ── Single-shift compliance checks ─────────────────────────────────────────

def validate_shift(start: time, end: time, break_minutes: int) -> List[str]:
    """
    Return a list of California labor-law warning strings for a single shift.

    Rules checked:
      • First meal period  : required when work exceeds 5 hours (≥30 min break)
      • Second meal period : required when work exceeds 10 hours
      • Rest breaks        : one paid 10-min break per 4 hours worked
    """
    warnings: List[str] = []
    hours = calc_hours(start, end, break_minutes)

    # Meal period 1
    if hours > 5 and break_minutes < 30:
        warnings.append(
            f"⚠️ 【餐飲休息·第一次】工作 {hours:.2f} 小時，"
            "依加州勞動法須提供至少 30 分鐘不間斷的餐飲休息。"
        )
    # Meal period 2
    if hours > 10 and break_minutes < 60:
        warnings.append(
            f"⚠️ 【餐飲休息·第二次】工作 {hours:.2f} 小時，"
            "依加州勞動法須再提供一次至少 30 分鐘的餐飲休息。"
        )
    # Rest breaks (informational)
    rest_count = int(hours // 4)
    if rest_count:
        warnings.append(
            f"ℹ️ 【帶薪休息】工作 {hours:.2f} 小時，"
            f"需安排 {rest_count} 次 10 分鐘帶薪休息（依法不得扣薪）。"
        )
    return warnings


# ── Daily hour classification ───────────────────────────────────────────────

def classify_daily_hours(
    hours: float,
    is_seventh_day: bool = False,
) -> Dict[str, float]:
    """
    Split daily worked hours into regular / overtime(1.5×) / double-time(2×).

    Normal workday (CA Labor Code § 510):
      0 – 8 h   → regular
      8 – 12 h  → overtime  (1.5×)
      > 12 h    → double-time (2×)

    7th consecutive workday:
      0 – 8 h   → overtime  (1.5×)
      > 8 h     → double-time (2×)
    """
    if is_seventh_day:
        return {
            "regular": 0.0,
            "overtime": min(hours, 8.0),
            "double_time": max(0.0, hours - 8.0),
        }
    return {
        "regular": min(hours, 8.0),
        "overtime": max(0.0, min(hours, 12.0) - 8.0),
        "double_time": max(0.0, hours - 12.0),
    }


# ── 7th consecutive workday detection ──────────────────────────────────────

def detect_seventh_consecutive_days(sorted_dates: List[date]) -> set:
    """
    Given a sorted list of work dates, return the set of dates that are
    the 7th (or more) in an unbroken consecutive-day streak.
    """
    if not sorted_dates:
        return set()

    seventh: set = set()
    streak = 1
    prev = sorted_dates[0]

    for d in sorted_dates[1:]:
        if (d - prev).days == 1:
            streak += 1
            if streak >= 7:
                seventh.add(d)
        else:
            streak = 1
        prev = d

    return seventh


# ── Weekly overtime rollup ──────────────────────────────────────────────────

def apply_weekly_overtime(daily: List[Dict[str, float]]) -> Dict[str, float]:
    """
    Apply the CA 40-hour weekly overtime rule.

    Hours classified as daily regular that push the weekly regular total
    beyond 40 are converted to weekly overtime (1.5×).
    Daily overtime and double-time already take precedence.
    """
    reg = sum(d["regular"] for d in daily)
    ot = sum(d["overtime"] for d in daily)
    dt = sum(d["double_time"] for d in daily)

    if reg > 40.0:
        overflow = reg - 40.0
        reg = 40.0
        ot += overflow

    return {"regular": reg, "overtime": ot, "double_time": dt}
