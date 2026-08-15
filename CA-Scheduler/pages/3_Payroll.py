"""
pages/3_Payroll.py – Weekly payroll preview with CA labor law compliance report.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from database import get_db, init_db
from payroll import compute_all_payroll

st.set_page_config(page_title="薪資預覽", page_icon="💰", layout="wide")

init_db()

st.title("💰 薪資預覽")
st.markdown("---")

# ── Week navigation ───────────────────────────────────────────────────────────
if "pay_week_offset" not in st.session_state:
    st.session_state.pay_week_offset = 0

nav1, nav2, nav3 = st.columns([1, 2, 1])
with nav1:
    if st.button("← 上週"):
        st.session_state.pay_week_offset -= 1
        st.rerun()
with nav3:
    if st.button("下週 →"):
        st.session_state.pay_week_offset += 1
        st.rerun()
with nav2:
    if st.button("🏠 回本週"):
        st.session_state.pay_week_offset = 0
        st.rerun()

today = date.today()
base_monday = today - timedelta(days=today.weekday())
week_start = base_monday + timedelta(weeks=st.session_state.pay_week_offset)
week_end = week_start + timedelta(days=6)

st.subheader(
    f"薪資週期：{week_start.strftime('%Y/%m/%d')}（週一）～ {week_end.strftime('%Y/%m/%d')}（週日）"
)

# ── Compute payroll ───────────────────────────────────────────────────────────
db = get_db()
try:
    results = compute_all_payroll(db, week_start)
finally:
    db.close()

if not results:
    st.info("本週無排班資料。請前往【班次排程】頁面新增班次後再查看薪資預覽。")
    st.stop()

# Pre-compute totals needed by both sections
total_labor    = sum(r["total_pay"]         for r in results)
total_regular_h= sum(r["weekly_regular"]    for r in results)
total_ot_h     = sum(r["weekly_overtime"]   for r in results)
total_dt_h     = sum(r["weekly_double_time"]for r in results)

# ── Daily cost breakdown ──────────────────────────────────────────────────────
st.markdown("### 📅 每日勞動成本明細")

_daily_cost: dict = defaultdict(dict)
for r in results:
    _rate = r["employee"].hourly_rate
    _name = r["employee"].name
    for d in r["daily_breakdown"]:
        _daily_cost[d["date"]][_name] = (
            d["regular"] * _rate
            + d["overtime"] * _rate * 1.5
            + d["double_time"] * _rate * 2.0
        )

week_dates  = [week_start + timedelta(days=i) for i in range(7)]
_day_labels = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
_emp_names  = [r["employee"].name for r in results]

daily_cost_rows = []
for i, d in enumerate(week_dates):
    row = {"日期": f"{_day_labels[i]}  {d.strftime('%m/%d')}"}
    day_total = 0.0
    for name in _emp_names:
        cost = _daily_cost.get(d, {}).get(name, 0.0)
        row[name] = f"${cost:.2f}" if cost > 0 else "—"
        day_total += cost
    row["📊 當日合計"] = f"${day_total:.2f}" if day_total > 0 else "—"
    daily_cost_rows.append(row)

total_row = {"日期": "💵 週合計"}
for r in results:
    total_row[r["employee"].name] = f"${r['total_pay']:.2f}"
total_row["📊 當日合計"] = f"${total_labor:,.2f}"
daily_cost_rows.append(total_row)

st.dataframe(pd.DataFrame(daily_cost_rows), width="stretch", hide_index=True)

st.markdown("---")

# ── Summary table ─────────────────────────────────────────────────────────────
st.markdown("### 📊 薪資摘要")

summary_rows = []
for r in results:
    summary_rows.append(
        {
            "員工": r["employee"].name,
            "職位": r["employee"].position or "—",
            "時薪": f"${r['employee'].hourly_rate:.2f}",
            "正常時數": f"{r['weekly_regular']:.2f} h",
            "加班時數 (×1.5)": f"{r['weekly_overtime']:.2f} h",
            "雙倍時數 (×2.0)": f"{r['weekly_double_time']:.2f} h",
            "正常薪資": f"${r['regular_pay']:.2f}",
            "加班薪資": f"${r['overtime_pay']:.2f}",
            "雙倍薪資": f"${r['double_time_pay']:.2f}",
            "本週合計": f"${r['total_pay']:.2f}",
        }
    )

st.dataframe(
    pd.DataFrame(summary_rows),
    width="stretch",
    hide_index=True,
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("💵 本週預估總勞動成本", f"${total_labor:,.2f}")
m2.metric("🕐 正常總時數", f"{total_regular_h:.2f} h")
m3.metric("⏰ 加班總時數", f"{total_ot_h:.2f} h")
m4.metric("⚡ 雙倍計薪總時數", f"{total_dt_h:.2f} h")

# ── Export payroll CSV ──────────────────────────────────────────────────
_pay_rows = []
for _r in results:
    for _d in _r["daily_breakdown"]:
        _dc = (
            _d["regular"]     * _r["employee"].hourly_rate
            + _d["overtime"]  * _r["employee"].hourly_rate * 1.5
            + _d["double_time"] * _r["employee"].hourly_rate * 2.0
        )
        _pay_rows.append({
            "員工": _r["employee"].name,
            "職位": _r["employee"].position or "",
            "日期": str(_d["date"]),
            "上班": _d["start"].strftime("%H:%M"),
            "下班": _d["end"].strftime("%H:%M"),
            "休息(分)": _d["break_min"],
            "工時": round(_d["hours"], 2),
            "正常時數": round(_d["regular"], 2),
            "加班時數": round(_d["overtime"], 2),
            "雙倍時數": round(_d["double_time"], 2),
            "第七日": "是" if _d["is_7th_day"] else "",
            "時薪": _r["employee"].hourly_rate,
            "當日薪資": round(_dc, 2),
        })
_pay_csv = pd.DataFrame(_pay_rows).to_csv(index=False).encode("utf-8-sig")
st.download_button(
    label="📥 匯出本週薪資明細 CSV",
    data=_pay_csv,
    file_name=f"payroll_{week_start.strftime('%Y%m%d')}.csv",
    mime="text/csv",
)

st.markdown("---")

# ── Per-employee detail ───────────────────────────────────────────────────────
st.markdown("### 👤 個別員工明細")

for r in results:
    total_warnings = len(r["warnings"])
    warn_badge = f"  ⚠️ {total_warnings} 項警示" if total_warnings else ""

    with st.expander(
        f"**{r['employee'].name}**  —  合計 **${r['total_pay']:.2f}**{warn_badge}",
        expanded=False,
    ):
        # ── Daily breakdown table ─────────────────────────────────────────
        daily_rows = []
        for d in r["daily_breakdown"]:
            day_total_pay = (
                d["regular"] * r["employee"].hourly_rate
                + d["overtime"] * r["employee"].hourly_rate * 1.5
                + d["double_time"] * r["employee"].hourly_rate * 2.0
            )
            daily_rows.append(
                {
                    "日期": str(d["date"]),
                    "上班": d["start"].strftime("%H:%M"),
                    "下班": d["end"].strftime("%H:%M"),
                    "休息(分)": d["break_min"],
                    "工時": f"{d['hours']:.2f} h",
                    "正常時數": f"{d['regular']:.2f} h",
                    "加班(×1.5)": f"{d['overtime']:.2f} h",
                    "雙倍(×2.0)": f"{d['double_time']:.2f} h",
                    "第七日": "⚠️ 是" if d["is_7th_day"] else "",
                    "當日薪資": f"${day_total_pay:.2f}",
                }
            )

        st.dataframe(
            pd.DataFrame(daily_rows),
            width="stretch",
            hide_index=True,
        )

        # ── Weekly totals ─────────────────────────────────────────────────
        rate = r["employee"].hourly_rate
        cols = st.columns(4)
        cols[0].metric("正常時數合計", f"{r['weekly_regular']:.2f} h", f"${r['regular_pay']:.2f}")
        cols[1].metric("加班時數合計 (×1.5)", f"{r['weekly_overtime']:.2f} h", f"${r['overtime_pay']:.2f}")
        cols[2].metric("雙倍時數合計 (×2.0)", f"{r['weekly_double_time']:.2f} h", f"${r['double_time_pay']:.2f}")
        cols[3].metric("本週薪資合計", f"${r['total_pay']:.2f}")

        # ── Compliance warnings ───────────────────────────────────────────
        if r["warnings"]:
            st.markdown("#### ⚠️ 加州勞動法合規提醒")
            seen: set = set()
            for w in r["warnings"]:
                if w not in seen:
                    if w.startswith("ℹ️"):
                        st.info(w)
                    else:
                        st.warning(w)
                    seen.add(w)
        else:
            st.success("✅ 本週班次均符合加州勞動法規，無合規警示。")
