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
    Return the list of 15-min slots that the shift covers but are NOT in the
    employee's availability for that weekday.
    Returns [] if availability is unconfigured or there is no conflict.
    """
    if not emp.availability or emp.availability in ("{}", "null"):
        return []
    try:
        avail = json.loads(emp.availability)
    except (json.JSONDecodeError, TypeError):
        return []

    day_key = _DAY_KEYS[shift_date.weekday()]
    available = set(avail.get(day_key, []))
    
    # If employee has availability configured but this day has no slots, mark as conflict
    if any(avail.values()) and not available:
        return ["entire_day_unavailable"]

    # Generate 15-min slots covered by the shift [start, end)
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
        cur += timedelta(minutes=15)
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
        if (h1 * 60 + m1) - (h0 * 60 + m0) == 15:
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


# ── Confirmation dialogs ─────────────────────────────────────────────────────

@st.dialog("⚠️ 新增班次確認")
def _add_confirm_dialog():
    pa = st.session_state["pending_add"]
    st.markdown("以下警告需確認後才能新增班次：")
    for w in pa["warns"]:
        st.warning(w)
    st.markdown("---")
    dc1, dc2 = st.columns(2)
    with dc1:
        if st.button("✅ 確認新增", type="primary", use_container_width=True):
            db = get_db()
            try:
                db.add(Shift(
                    employee_id=pa["employee_id"],
                    date=pa["date"],
                    start_time=pa["start_time"],
                    end_time=pa["end_time"],
                    break_minutes=pa["break_minutes"],
                    notes=pa["notes"],
                ))
                db.commit()
            finally:
                db.close()
            del st.session_state["pending_add"]
            st.session_state["_add_success"] = pa["hours"]
            st.rerun()
    with dc2:
        if st.button("✖ 取消", use_container_width=True):
            del st.session_state["pending_add"]
            st.rerun()


@st.dialog("⚠️ 儲存班次確認")
def _edit_confirm_dialog():
    pe = st.session_state["pending_edit"]
    st.markdown("以下警告需確認後才能儲存班次：")
    for w in pe["warns"]:
        st.warning(w)
    st.markdown("---")
    dc1, dc2 = st.columns(2)
    with dc1:
        if st.button("✅ 確認儲存", type="primary", use_container_width=True):
            db = get_db()
            try:
                shift_obj = db.query(Shift).filter(Shift.id == pe["shift_id"]).first()
                shift_obj.employee_id = pe["employee_id"]
                shift_obj.date = pe["date"]
                shift_obj.start_time = pe["start_time"]
                shift_obj.end_time = pe["end_time"]
                shift_obj.break_minutes = pe["break_minutes"]
                shift_obj.notes = pe["notes"]
                db.commit()
            finally:
                db.close()
            del st.session_state["pending_edit"]
            st.session_state["_edit_success"] = pe["hours"]
            st.rerun()
    with dc2:
        if st.button("✖ 取消", use_container_width=True):
            del st.session_state["pending_edit"]
            st.rerun()


def _save_shift_edit(shift_id: int, employee_id: int, shift_date, start, end, break_min: int, notes: str) -> None:
    db = get_db()
    try:
        obj = db.query(Shift).filter(Shift.id == shift_id).first()
        obj.employee_id  = employee_id
        obj.date         = shift_date
        obj.start_time   = start
        obj.end_time     = end
        obj.break_minutes = break_min
        obj.notes        = notes
        db.commit()
    finally:
        db.close()


@st.dialog("✏️ 編輯 / 🗑️ 刪除班次")
def _shift_click_dialog(shift_id: int) -> None:
    db = get_db()
    try:
        sel = db.query(Shift).filter(Shift.id == shift_id).first()
        if sel is None:
            st.error("找不到此班次。")
            if st.button("關閉"):
                del st.session_state["_editing_shift_id"]
                st.rerun()
            return
        ss_data = {
            "employee_id":    sel.employee_id,
            "date":           sel.date,
            "start_time":     sel.start_time,
            "end_time":       sel.end_time,
            "break_minutes":  sel.break_minutes,
            "notes":          sel.notes or "",
        }
    finally:
        db.close()

    cur_name = emp_map.get(ss_data["employee_id"], employees[0]).name
    cur_idx  = emp_names.index(cur_name) if cur_name in emp_names else 0
    warn_key = f"_dlg_warns_{shift_id}"

    tab_ed, tab_dl = st.tabs(["✏️ 編輯", "🗑️ 刪除"])

    with tab_ed:
        ec1, ec2, ec3 = st.columns(3)
        ed_emp   = ec1.selectbox("員工", emp_names, index=cur_idx, key=f"dlg_emp_{shift_id}")
        ed_date  = ec2.date_input("日期", value=ss_data["date"], key=f"dlg_date_{shift_id}")
        ed_break = ec3.number_input(
            "休息（分鐘）", min_value=0, max_value=180,
            value=ss_data["break_minutes"], step=5, key=f"dlg_break_{shift_id}",
        )
        et1, et2 = st.columns(2)
        ed_start = et1.time_input("上班時間", value=ss_data["start_time"], key=f"dlg_start_{shift_id}")
        ed_end   = et2.time_input("下班時間",  value=ss_data["end_time"],   key=f"dlg_end_{shift_id}")
        ed_notes = st.text_input("備註", value=ss_data["notes"], key=f"dlg_notes_{shift_id}")

        if st.button("💾 儲存變更", type="primary", key=f"dlg_save_{shift_id}"):
            hours = calc_hours(ed_start, ed_end, ed_break)
            if hours <= 0:
                st.error("❌ 工時計算結果為零，請確認時間設定。")
            else:
                db2 = get_db()
                try:
                    warns = (
                        validate_shift(ed_start, ed_end, ed_break)
                        + shift_conflict_msgs(db2, emp_name_to_id[ed_emp], ed_date,
                                             ed_start, ed_end, exclude_id=shift_id)
                        + avail_warn_msgs(emp_map[emp_name_to_id[ed_emp]],
                                          ed_date, ed_start, ed_end)
                    )
                finally:
                    db2.close()
                if warns:
                    st.session_state[warn_key] = {
                        "warns": warns, "hours": hours,
                        "employee_id": emp_name_to_id[ed_emp],
                        "date": ed_date, "start": ed_start,
                        "end": ed_end, "break": ed_break, "notes": ed_notes,
                    }
                else:
                    _save_shift_edit(shift_id, emp_name_to_id[ed_emp], ed_date,
                                     ed_start, ed_end, ed_break, ed_notes)
                    del st.session_state["_editing_shift_id"]
                    st.rerun()

        if warn_key in st.session_state:
            pw = st.session_state[warn_key]
            st.markdown("---")
            for w in pw["warns"]:
                st.warning(w)
            wc1, wc2 = st.columns(2)
            if wc1.button("✅ 確認儲存", type="primary", key=f"dlg_confirm_{shift_id}"):
                _save_shift_edit(shift_id, pw["employee_id"], pw["date"],
                                 pw["start"], pw["end"], pw["break"], pw["notes"])
                st.session_state.pop(warn_key, None)
                del st.session_state["_editing_shift_id"]
                st.rerun()
            if wc2.button("✖ 取消", key=f"dlg_cancel_save_{shift_id}"):
                st.session_state.pop(warn_key, None)
                st.rerun()

    with tab_dl:
        st.warning(f"即將刪除班次 **#{shift_id}**，此操作無法復原。")
        confirm_del = st.checkbox("確認刪除此班次", key=f"dlg_confirm_del_{shift_id}")
        if st.button("🗑️ 確認刪除班次", type="primary",
                     disabled=not confirm_del, key=f"dlg_del_{shift_id}"):
            db3 = get_db()
            try:
                db3.query(Shift).filter(Shift.id == shift_id).delete()
                db3.commit()
            finally:
                db3.close()
            del st.session_state["_editing_shift_id"]
            st.rerun()


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

# Build shift-cell mapping: (emp_id, day_idx) -> [Shift, ...]
shift_cell: dict = {}
for shift in shifts_this_week:
    for i, d in enumerate(days):
        if d == shift.date:
            shift_cell.setdefault((shift.employee_id, i), []).append(shift)
            break

# Render clickable calendar grid
_GCOLS = [1.4] + [1.3] * 7
_hdr = st.columns(_GCOLS)
_hdr[0].markdown("**員工**")
for _i in range(7):
    _hdr[_i + 1].markdown(f"**{day_labels[_i]}**  \n{days[_i].strftime('%m/%d')}")
st.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)

for _emp in employees:
    _row = st.columns(_GCOLS)
    _row[0].markdown(f"**{_emp.name}**")
    for _i in range(7):
        _cell_shifts = shift_cell.get((_emp.id, _i), [])
        if not _cell_shifts:
            _row[_i + 1].markdown("—")
        else:
            for _sh in _cell_shifts:
                _hrs = calc_hours(_sh.start_time, _sh.end_time, _sh.break_minutes)
                _lbl = f"{_sh.start_time.strftime('%H:%M')}–{_sh.end_time.strftime('%H:%M')}"
                if avail_conflict(_emp, _sh.date, _sh.start_time, _sh.end_time):
                    _lbl = "🔔 " + _lbl
                if _row[_i + 1].button(_lbl, key=f"shift_btn_{_sh.id}",
                                       help=f"{_hrs:.1f}h  ·  點擊編輯/刪除"):
                    st.session_state["_editing_shift_id"] = _sh.id
                    st.rerun()
    st.markdown("<hr style='margin:2px 0'>", unsafe_allow_html=True)

# Open edit/delete dialog when a shift cell was clicked
if "_editing_shift_id" in st.session_state:
    _shift_click_dialog(st.session_state["_editing_shift_id"])

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
            finally:
                db.close()
            if warns:
                st.session_state["pending_add"] = {
                    "employee_id": emp_name_to_id[add_emp],
                    "date": add_date,
                    "start_time": add_start,
                    "end_time": add_end,
                    "break_minutes": add_break,
                    "notes": add_notes,
                    "hours": hours,
                    "warns": warns,
                }
            else:
                db = get_db()
                try:
                    db.add(Shift(
                        employee_id=emp_name_to_id[add_emp],
                        date=add_date,
                        start_time=add_start,
                        end_time=add_end,
                        break_minutes=add_break,
                        notes=add_notes,
                    ))
                    db.commit()
                finally:
                    db.close()
                st.success(f"✅ 班次已新增！工時：{hours:.2f} 小時")
                st.rerun()

    if "pending_add" in st.session_state:
        _add_confirm_dialog()

    if "_add_success" in st.session_state:
        st.success(f"✅ 班次已新增！工時：{st.session_state.pop('_add_success'):.2f} 小時")

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
            finally:
                db.close()
            if warns:
                st.session_state["pending_edit"] = {
                    "shift_id": sel_shift_id,
                    "employee_id": emp_name_to_id[ed_emp],
                    "date": ed_date,
                    "start_time": ed_start,
                    "end_time": ed_end,
                    "break_minutes": ed_break,
                    "notes": ed_notes,
                    "hours": hours,
                    "warns": warns,
                }
            else:
                db = get_db()
                try:
                    shift_obj = db.query(Shift).filter(Shift.id == sel_shift_id).first()
                    shift_obj.employee_id = emp_name_to_id[ed_emp]
                    shift_obj.date = ed_date
                    shift_obj.start_time = ed_start
                    shift_obj.end_time = ed_end
                    shift_obj.break_minutes = ed_break
                    shift_obj.notes = ed_notes
                    db.commit()
                finally:
                    db.close()
                st.success(f"✅ 班次已更新！工時：{hours:.2f} 小時")
                st.rerun()

if "pending_edit" in st.session_state:
    _edit_confirm_dialog()

if "_edit_success" in st.session_state:
    st.success(f"✅ 班次已更新！工時：{st.session_state.pop('_edit_success'):.2f} 小時")

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
