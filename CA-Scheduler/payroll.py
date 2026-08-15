"""
payroll.py – Payroll computation for one employee or all employees in a week.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from models import Employee, Shift
from rules import (
    apply_weekly_overtime,
    calc_hours,
    classify_daily_hours,
    detect_seventh_consecutive_days,
    validate_shift,
)


def week_bounds(ref: date):
    """Return (monday, sunday) for the ISO workweek that contains *ref*."""
    monday = ref - timedelta(days=ref.weekday())
    return monday, monday + timedelta(days=6)


def compute_payroll(employee: Employee, shifts: List[Shift]) -> Dict[str, Any]:
    """
    Compute full payroll detail for *employee* over the given *shifts*.

    Returns a dict with:
      employee          – Employee ORM object
      daily_breakdown   – list of per-shift dicts
      weekly_regular    – total regular hours (after weekly OT adjustment)
      weekly_overtime   – total overtime hours
      weekly_double_time– total double-time hours
      regular_pay / overtime_pay / double_time_pay / total_pay
      warnings          – list of CA labor-law warning strings
    """
    sorted_shifts = sorted(shifts, key=lambda s: s.date)
    seventh_days = detect_seventh_consecutive_days([s.date for s in sorted_shifts])

    daily_rows: List[Dict] = []
    all_warnings: List[str] = []

    for shift in sorted_shifts:
        hours = calc_hours(shift.start_time, shift.end_time, shift.break_minutes)
        is_7th = shift.date in seventh_days
        classified = classify_daily_hours(hours, is_seventh_day=is_7th)

        warns = validate_shift(shift.start_time, shift.end_time, shift.break_minutes)
        if is_7th:
            warns.insert(
                0,
                f"⚠️ 【第七連續工作日】{shift.date} — "
                "前 8 小時依 1.5 倍計薪，超過 8 小時依 2 倍計薪。",
            )
        all_warnings.extend(warns)

        daily_rows.append(
            {
                "date": shift.date,
                "start": shift.start_time,
                "end": shift.end_time,
                "break_min": shift.break_minutes,
                "hours": hours,
                "is_7th_day": is_7th,
                **classified,
            }
        )

    weekly = apply_weekly_overtime(daily_rows)
    rate = employee.hourly_rate

    regular_pay = weekly["regular"] * rate
    overtime_pay = weekly["overtime"] * rate * 1.5
    double_time_pay = weekly["double_time"] * rate * 2.0

    return {
        "employee": employee,
        "daily_breakdown": daily_rows,
        "weekly_regular": weekly["regular"],
        "weekly_overtime": weekly["overtime"],
        "weekly_double_time": weekly["double_time"],
        "regular_pay": regular_pay,
        "overtime_pay": overtime_pay,
        "double_time_pay": double_time_pay,
        "total_pay": regular_pay + overtime_pay + double_time_pay,
        "warnings": all_warnings,
    }


def compute_all_payroll(db_session, week_start: date) -> List[Dict[str, Any]]:
    """
    Compute payroll for every employee who has at least one shift
    in the week starting on *week_start* (Monday).
    """
    week_end = week_start + timedelta(days=6)
    employees: List[Employee] = db_session.query(Employee).all()
    results = []

    for emp in employees:
        shifts: List[Shift] = (
            db_session.query(Shift)
            .filter(
                Shift.employee_id == emp.id,
                Shift.date >= week_start,
                Shift.date <= week_end,
            )
            .all()
        )
        if shifts:
            results.append(compute_payroll(emp, shifts))

    return results
