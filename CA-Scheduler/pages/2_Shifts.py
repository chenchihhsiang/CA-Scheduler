import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime as _dt, time, timedelta

import pandas as pd
import streamlit as st

from database import get_db, init_db
from models import Employee, Shift
from rules import calc_hours, validate_shift

st.set_page_config(page_title="班次排程", page_icon="📆", layout="wide")

init_db()

# ── Availability conflict helper ──────────────────────────────────────────────

_DAY_KEYS  = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_DAY_LABELS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


def avail_conflict(emp: Employee, shift_date: date, start: time, end: time):
    """
    Return the list of 30-min slots that the shift covers but are NOT in the
    employee's availability for that weekday.
    Returns [] if availability is unconfigured or there is no conflict.
    """
    if not emp.availability or emp.availability in ("{}", "null"):
        return []
    try:
        avail = json.loads(emp.availability)
    except (json.JSONDecodeError, TypeError):
        return []
    if not any(avail.values()):          # all days empty = feature not used
        return []

    day_key = _DAY_KEYS[shift_date.weekday()]
    available = set(avail.get(day_key, []))

    # Generate 30-min slots covered by the shift [start, end)
    base = date.today()
    cur  = _dt.combine(base, start)
    stop = _dt.combine(base, end)
    if stop <= cur:
        stop += timedelta(days=1)

    missing = []
    while cur < stop:
        slot = cur.strftime("%H:%M")
        if slot not in available:
            missing.append(slot)
        cur += timedelta(minutes=30)
    return missing


def avail_warn_msgs(emp: Employee, shift_date: date, start: time, end: time):
    """Return human-readable warning strings for an availability conflict."""
    missing = avail_conflict(emp, shift_date, start, end)
    if not missing:
        return []
    day_label = _DAY_LABELS[shift_date.weekday()]
    # Collapse consecutive slots into ranges for readability
    ranges, grp = [], [missing[0]]
    for slot in missing[1:]:
        h0, m0 = map(int, grp[-1].split(":"))
        h1, m1 = map(int, slot.split(":"))
        if (h1 * 60 + m1) - (h0 * 60 + m0) == 30:
            grp.append(slot)
        else:
            ranges.append(f"{grp[0]}–{grp[-1]}" if len(grp) > 1 else grp[0])
            grp = [slot]
    ranges.append(f"{grp[0]}–{grp[-1]}" if len(grp) > 1 else grp[0])
    slots_str = "、".join(ranges)
    return [
        f"🔔 【Availability 提醒】員工「{emp.name}」在 {day_label} "
        f"的可排班時間不含以下時段：{slots_str}。"
        "請再次與員工確認此班次是否可行。"
    ]


def shift_conflict_msgs(db_session, employee_id: int, shift_date: date,
                        start: time, end: time, exclude_id: int = None):
    """
    Return warning strings when the employee already has a time-overlapping
    shift on the same date.  Pass exclude_id to ignore the shift being edited.
    """
    q = db_session.query(Shift).filter(
        Shift.employee_id == employee_id,
        Shift.date == shift_date,
    )
    if exclude_id is not None:
        q = q.filter(Shift.id != exclude_id)

    base = date.today()
    s1 = _dt.combine(base, start)
    e1 = _dt.combine(base, end)
    if e1 <= s1:
        e1 += timedelta(days=1)

    msgs = []
    for sh in q.all():
        s2 = _dt.combine(base, sh.start_time)
        e2 = _dt.combine(base, sh.end_time)
        if e2 <= s2:
            e2 += timedelta(days=1)
        if s1 < e2 and s2 < e1:           # overlap condition
            msgs.append(
                f"⚠️ 【班次衝突】該員工在 {shift_date} 已有重疊班次 "
                f"#{sh.id}（{sh.start_time.strftime('%H:%M')}–"
                f"{sh.end_time.strftime('%H:%M')}），請確認是否重複排班。"
            )
    return msgs

st.title("📆 班次排程")

st.markdown("---")

# ── Load reference data ───────────────────────────────────────────────────────
db = get_db()
try:
    employees = db.query(Employee).order_by(Employee.name).all()
finally:
    db.close()

if not employees:
    st.warning("⚠️ 請先前往【員工管理】頁面新增員工，才能建立班次。")
    st.stop()

emp_map: dict[int, Employee] = {e.id: e for e in employees}
emp_name_to_id: dict[str, int] = {e.name: e.id for e in employees}
emp_names: list[str] = [e.name for e in employees]


# ── Week navigation ───────────────────────────────────────────────────────────
if "shift_week_offset" not in st.session_state:
    st.session_state.shift_week_offset = 0

nav1, nav2, nav3 = st.columns([1, 2, 1])
with nav1:
    if st.button("← 上週"):
        st.session_state.shift_week_offset -= 1
        st.rerun()
with nav3:
    if st.button("下週 →"):
        st.session_state.shift_week_offset += 1
        st.rerun()
with nav2:
    if st.button("🏠 回本週"):
        st.session_state.shift_week_offset = 0
        st.rerun()

today = date.today()
base_monday = today - timedelta(days=today.weekday())
week_start = base_monday + timedelta(weeks=st.session_state.shift_week_offset)
week_end = week_start + timedelta(days=6)

st.subheader(f"週期：{week_start.strftime('%Y/%m/%d')}（週一）～ {week_end.strftime('%Y/%m/%d')}（週日）")


# ── Weekly calendar grid ──────────────────────────────────────────────────────
st.markdown("### 📅 本週班表")

days = [week_start + timedelta(days=i) for i in range(7)]
day_labels = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
col_headers = [f"{day_labels[i]}\n{days[i].strftime('%m/%d')}" for i in range(7)]

db = get_db()
try:
    shifts_this_week = (
        db.query(Shift)
        .filter(Shift.date >= week_start, Shift.date <= week_end)
        .order_by(Shift.date, Shift.start_time)
        .all()
    )
finally:
    db.close()

# Build calendar matrix: index = employee name, columns = day headers
cal: dict[str, dict[str, str]] = {name: {h: "" for h in col_headers} for name in emp_names}

for shift in shifts_this_week:
    emp = emp_map.get(shift.employee_id)
    if emp is None:
        continue
    for i, d in enumerate(days):
        if d == shift.date:
            col_key = col_headers[i]
            hours = calc_hours(shift.start_time, shift.end_time, shift.break_minutes)
            cell = (
                f"{shift.start_time.strftime('%H:%M')}–"
                f"{shift.end_time.strftime('%H:%M')} ({hours:.1f}h)"
            )
            # Mark out-of-availability shifts with a warning icon
            if avail_conflict(emp, shift.date, shift.start_time, shift.end_time):
                cell = "🔔 " + cell
            existing = cal[emp.name][col_key]
            cal[emp.name][col_key] = (existing + "\n" + cell) if existing else cell
            break

cal_df = pd.DataFrame(cal).T  # employees as rows
cal_df.index.name = "員工"
cal_df.columns = col_headers
cal_df = cal_df.replace("", "—")
st.dataframe(cal_df, use_container_width=True)

# ── Weekly hours summary ──────────────────────────────────────────────────────
st.markdown("### 📊 本週工時總覽")

# Compute per-employee scheduled hours from this week's shifts
weekly_hours: dict = {}
for shift in shifts_this_week:
    h = calc_hours(shift.start_time, shift.end_time, shift.break_minutes)
    weekly_hours[shift.employee_id] = weekly_hours.get(shift.employee_id, 0.0) + h

# Show metric cards in rows of 4
_COLS_PER_ROW = 4
for row_start in range(0, len(employees), _COLS_PER_ROW):
    row_emps = employees[row_start : row_start + _COLS_PER_ROW]
    cols = st.columns(_COLS_PER_ROW)
    for j, emp in enumerate(row_emps):
        scheduled = weekly_hours.get(emp.id, 0.0)
        target = float(emp.target_hours) if emp.target_hours else 40.0
        remaining = target - scheduled
        progress = min(scheduled / target, 1.0) if target > 0 else 0.0

        delta_str = (
            f"+{remaining:.1f} h 可排"
            if remaining >= 0
            else f"{remaining:.1f} h 已超出"
        )

        with cols[j]:
            st.metric(
                label=f"👤 {emp.name}",
                value=f"{scheduled:.1f} / {target:.1f} h",
                delta=delta_str,
                delta_color="normal",
            )
            st.progress(progress, text=f"已排 {scheduled:.1f} h，目標 {target:.1f} h")

st.markdown("---")

# ── Export weekly schedule ────────────────────────────────────────────────────
if shifts_this_week:
    _xrows = []
    for _xs in shifts_this_week:
        _xname = emp_map[_xs.employee_id].name if _xs.employee_id in emp_map else "?"
        _xidx  = (_xs.date - week_start).days
        _xh    = calc_hours(_xs.start_time, _xs.end_time, _xs.break_minutes)
        _xrows.append({
            "員工": _xname,
            "日期": str(_xs.date),
            "星期": _DAY_LABELS[_xidx] if 0 <= _xidx <= 6 else "",
            "上班": _xs.start_time.strftime("%H:%M"),
            "下班": _xs.end_time.strftime("%H:%M"),
            "休息(分)": _xs.break_minutes,
            "工時": f"{_xh:.2f}",
            "備註": _xs.notes or "",
        })
    _csv = pd.DataFrame(_xrows).to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="📥 匯出本週班表 CSV",
        data=_csv,
        file_name=f"schedule_{week_start.strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )

# ── Copy last week ────────────────────────────────────────────────────────────
with st.expander("📂 複製上週班表到本週", expanded=False):
    _prev_start = week_start - timedelta(weeks=1)
    _prev_end   = _prev_start + timedelta(days=6)

    _cdb = get_db()
    try:
        _prev_shifts = (
            _cdb.query(Shift)
            .filter(Shift.date >= _prev_start, Shift.date <= _prev_end)
            .order_by(Shift.date, Shift.start_time)
            .all()
        )
    finally:
        _cdb.close()

    if not _prev_shifts:
        st.info(
            f"上週（{_prev_start.strftime('%m/%d')}～"
            f"{_prev_end.strftime('%m/%d')}）無班次資料。"
        )
    else:
        _copy_preview = []
        for _cs in _prev_shifts:
            _cname = emp_map[_cs.employee_id].name if _cs.employee_id in emp_map else "（已刪除）"
            _nd    = _cs.date + timedelta(weeks=1)
            _copy_preview.append({
                "員工": _cname,
                "原日期": f"{_DAY_LABELS[_cs.date.weekday()]} {_cs.date.strftime('%m/%d')}",
                "→ 本週日期": f"{_DAY_LABELS[_nd.weekday()]} {_nd.strftime('%m/%d')}",
                "上班": _cs.start_time.strftime("%H:%M"),
                "下班": _cs.end_time.strftime("%H:%M"),
                "工時": f"{calc_hours(_cs.start_time, _cs.end_time, _cs.break_minutes):.1f} h",
            })
        st.dataframe(pd.DataFrame(_copy_preview), use_container_width=True, hide_index=True)

        _cdb2 = get_db()
        try:
            _cur_cnt = _cdb2.query(Shift).filter(
                Shift.date >= week_start, Shift.date <= week_end
            ).count()
        finally:
            _cdb2.close()

        if _cur_cnt:
            st.warning(
                f"⚠️ 本週已有 {_cur_cnt} 筆班次，"
                "同員工＋同日期＋同上班時間的重複班次將自動略過。"
            )

        if st.button("✅ 確認複製上週班表", type="primary", key="copy_last_week"):
            _cdb3 = get_db()
            try:
                _copied = _skipped = 0
                for _cs in _prev_shifts:
                    if _cs.employee_id not in emp_map:
                        _skipped += 1
                        continue
                    _nd = _cs.date + timedelta(weeks=1)
                    if _cdb3.query(Shift).filter(
                        Shift.employee_id == _cs.employee_id,
                        Shift.date        == _nd,
                        Shift.start_time  == _cs.start_time,
                    ).first():
                        _skipped += 1
                        continue
                    _cdb3.add(Shift(
                        employee_id=_cs.employee_id,
                        date=_nd,
                        start_time=_cs.start_time,
                        end_time=_cs.end_time,
                        break_minutes=_cs.break_minutes,
                        notes=_cs.notes,
                    ))
                    _copied += 1
                _cdb3.commit()
                st.success(f"✅ 複製完成！新增 {_copied} 筆，略過 {_skipped} 筆。")
            finally:
                _cdb3.close()
            st.rerun()

# ── Batch add shifts ──────────────────────────────────────────────────────────
with st.expander("📄 批次新增班次（同員工整週）", expanded=False):
    with st.form("batch_add_form"):
        ba1, ba2 = st.columns(2)
        batch_emp   = ba1.selectbox("員工 *", emp_names, key="batch_emp_sel")
        batch_break = ba2.number_input(
            "休息時間（分鐘）", value=30, min_value=0, max_value=180, step=5, key="batch_break"
        )
        bt1, bt2 = st.columns(2)
        batch_start = bt1.time_input("上班時間 *", value=time(11, 0), key="batch_start")
        batch_end   = bt2.time_input("下班時間 *", value=time(19, 0), key="batch_end")
        batch_notes = st.text_input("備註（套用至所有選取天）", key="batch_notes")
        st.markdown("選擇要排班的天：")
        _bdc = st.columns(7)
        _bd_flags = [
            _bdc[i].checkbox(_DAY_LABELS[i], value=False, key=f"bd_{i}")
            for i in range(7)
        ]
        batch_submitted = st.form_submit_button("📄 批次新增班次", type="primary")

    if batch_submitted:
        _sel_days = [days[i] for i, chk in enumerate(_bd_flags) if chk]
        _bh = calc_hours(batch_start, batch_end, batch_break)
        if not _sel_days:
            st.error("❌ 請至少勾選一天。")
        elif _bh <= 0:
            st.error("❌ 工時為零，請確認時間設定。")
        else:
            _beid  = emp_name_to_id[batch_emp]
            _beobj = emp_map[_beid]
            _bw    = []
            _bdb   = get_db()
            try:
                for _bd in _sel_days:
                    _label = f"[{_DAY_LABELS[_bd.weekday()]} {_bd.strftime('%m/%d')}]"
                    _bw += [
                        f"{_label} {_m}"
                        for _m in (
                            shift_conflict_msgs(_bdb, _beid, _bd, batch_start, batch_end)
                            + avail_warn_msgs(_beobj, _bd, batch_start, batch_end)
                        )
                    ]
                    _bdb.add(Shift(
                        employee_id=_beid,
                        date=_bd,
                        start_time=batch_start,
                        end_time=batch_end,
                        break_minutes=batch_break,
                        notes=batch_notes,
                    ))
                _bdb.commit()
                st.success(f"✅ 批次新增 {len(_sel_days)} 筆班次，每天 {_bh:.1f} 小時。")
            finally:
                _bdb.close()
            for _bw_msg in _bw:
                st.warning(_bw_msg)
            st.rerun()

# ── Add single shift ──────────────────────────────────────────────────────────
with st.expander("➕ 新增班次（單日）", expanded=False):
    with st.form("add_shift_form", clear_on_submit=False):
        sa1, sa2, sa3 = st.columns(3)
        with sa1:
            add_emp = st.selectbox("員工 *", emp_names, key="add_emp_sel")
        with sa2:
            add_date = st.date_input("日期 *", value=today, key="add_date")
        with sa3:
            add_break = st.number_input(
                "休息時間（分鐘）", min_value=0, max_value=180, value=30, step=5, key="add_break"
            )
        sb1, sb2 = st.columns(2)
        with sb1:
            add_start = st.time_input("上班時間 *", value=time(9, 0), key="add_start")
        with sb2:
            add_end = st.time_input("下班時間 *", value=time(17, 0), key="add_end")
        add_notes = st.text_input("備註", key="add_notes")
        add_submitted = st.form_submit_button("新增班次", type="primary")

    if add_submitted:
        hours = calc_hours(add_start, add_end, add_break)
        if hours <= 0:
            st.error("❌ 班次工時計算結果為零或負數，請重新確認上下班時間。")
        else:
            db = get_db()
            try:
                warns = validate_shift(add_start, add_end, add_break)
                warns += shift_conflict_msgs(db, emp_name_to_id[add_emp], add_date, add_start, add_end)
                warns += avail_warn_msgs(
                    emp_map[emp_name_to_id[add_emp]], add_date, add_start, add_end
                )
                db.add(Shift(
                    employee_id=emp_name_to_id[add_emp],
                    date=add_date,
                    start_time=add_start,
                    end_time=add_end,
                    break_minutes=add_break,
                    notes=add_notes,
                ))
                db.commit()
                st.success(f"✅ 班次已新增！工時：{hours:.2f} 小時")
            finally:
                db.close()
            for w in warns:
                st.warning(w)
            st.rerun()

st.markdown("---")


# ── Edit / Delete shift ────────────────────────────────────────────────────────
st.subheader("✏️ 編輯 / 🗑️ 刪除班次")

db = get_db()
try:
    all_week_shifts = (
        db.query(Shift)
        .filter(Shift.date >= week_start, Shift.date <= week_end)
        .order_by(Shift.date, Shift.start_time)
        .all()
    )
finally:
    db.close()

if not all_week_shifts:
    st.info("本週尚無班次資料。請使用上方表單新增班次。")
    st.stop()

shift_options: dict[str, int] = {}
for s in all_week_shifts:
    emp_label = emp_map[s.employee_id].name if s.employee_id in emp_map else "未知員工"
    label = (
        f"[#{s.id}]  {emp_label}  │  {s.date}  │  "
        f"{s.start_time.strftime('%H:%M')} – {s.end_time.strftime('%H:%M')}"
    )
    shift_options[label] = s.id

sel_shift_label = st.selectbox("選擇班次", list(shift_options.keys()))
sel_shift_id = shift_options[sel_shift_label]

db = get_db()
try:
    sel = db.query(Shift).filter(Shift.id == sel_shift_id).first()
    ss = {
        "employee_id": sel.employee_id,
        "date": sel.date,
        "start_time": sel.start_time,
        "end_time": sel.end_time,
        "break_minutes": sel.break_minutes,
        "notes": sel.notes or "",
    }
finally:
    db.close()

current_emp_name = emp_map[ss["employee_id"]].name if ss["employee_id"] in emp_map else emp_names[0]
current_emp_idx = emp_names.index(current_emp_name) if current_emp_name in emp_names else 0

col_ed, col_dl = st.columns([3, 2])

with col_ed:
    with st.form("edit_shift_form"):
        st.markdown("**✏️ 編輯班次**")
        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            ed_emp = st.selectbox("員工", emp_names, index=current_emp_idx)
        with ec2:
            ed_date = st.date_input("日期", value=ss["date"])
        with ec3:
            ed_break = st.number_input(
                "休息（分鐘）", min_value=0, max_value=180, value=ss["break_minutes"], step=5
            )
        et1, et2 = st.columns(2)
        with et1:
            ed_start = st.time_input("上班時間", value=ss["start_time"])
        with et2:
            ed_end = st.time_input("下班時間", value=ss["end_time"])
        ed_notes = st.text_input("備註", value=ss["notes"])
        edit_submitted = st.form_submit_button("儲存變更", type="primary")

    if edit_submitted:
        hours = calc_hours(ed_start, ed_end, ed_break)
        if hours <= 0:
            st.error("❌ 工時計算結果為零，請確認時間設定。")
        else:
            db = get_db()
            try:
                warns = validate_shift(ed_start, ed_end, ed_break)
                warns += shift_conflict_msgs(
                    db, emp_name_to_id[ed_emp], ed_date, ed_start, ed_end,
                    exclude_id=sel_shift_id
                )
                warns += avail_warn_msgs(
                    emp_map[emp_name_to_id[ed_emp]], ed_date, ed_start, ed_end
                )
                shift_obj = db.query(Shift).filter(Shift.id == sel_shift_id).first()
                shift_obj.employee_id = emp_name_to_id[ed_emp]
                shift_obj.date = ed_date
                shift_obj.start_time = ed_start
                shift_obj.end_time = ed_end
                shift_obj.break_minutes = ed_break
                shift_obj.notes = ed_notes
                db.commit()
                st.success(f"✅ 班次已更新！工時：{hours:.2f} 小時")
            finally:
                db.close()
            for w in warns:
                st.warning(w)
            st.rerun()

with col_dl:
    st.markdown("**🗑️ 刪除班次**")
    st.warning(f"即將刪除班次 **#{sel_shift_id}**，此操作無法復原。")
    confirm_del = st.checkbox("確認刪除此班次", key="confirm_del_shift")
    if st.button("確認刪除班次", type="primary", disabled=not confirm_del):
        db = get_db()
        try:
            db.query(Shift).filter(Shift.id == sel_shift_id).delete()
            db.commit()
            st.success("✅ 班次已刪除！")
        finally:
            db.close()
        st.rerun()
