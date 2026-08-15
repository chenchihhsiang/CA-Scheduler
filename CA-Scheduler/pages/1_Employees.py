"""
pages/1_Employees.py – Employee management page (CRUD) with availability timetable.
"""

import json
import os
import sys
from datetime import time as dt_time
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from database import get_db, init_db
from models import Employee, Shift

st.set_page_config(page_title="員工管理", page_icon="👥", layout="wide")

init_db()

# ── Availability helpers ──────────────────────────────────────────────────────

DAYS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
DAY_KEYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

TIME_SLOTS: list[str] = [
    f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)
]


def avail_json_to_df(availability_json: Optional[str]) -> pd.DataFrame:
    """Convert stored JSON → boolean DataFrame (rows=time, cols=days)."""
    avail: dict = {}
    if availability_json:
        try:
            avail = json.loads(availability_json)
        except (json.JSONDecodeError, TypeError):
            avail = {}
    df = pd.DataFrame(False, index=TIME_SLOTS, columns=DAYS)
    df.index.name = "時間"
    for day_key, day_label in zip(DAY_KEYS, DAYS):
        for slot in avail.get(day_key, []):
            if slot in df.index:
                df.at[slot, day_label] = True
    return df


def avail_df_to_json(df: pd.DataFrame) -> str:
    """Convert edited boolean DataFrame → JSON string for storage."""
    result: Dict[str, List[str]] = {}
    for day_key, day_label in zip(DAY_KEYS, DAYS):
        if day_label in df.columns:
            result[day_key] = [t for t in df.index if df.at[t, day_label]]
    return json.dumps(result, ensure_ascii=False)


def render_avail_editor(key: str, initial_json: Optional[str] = None) -> pd.DataFrame:
    """
    Render availability timetable with business-hours quick-apply buttons.
    Uses session_state to persist manual edits and button actions between reruns.
    """
    state_key = f"{key}_df_state"

    # Initialize from saved JSON only on first visit for this key
    if state_key not in st.session_state:
        st.session_state[state_key] = avail_json_to_df(initial_json)

    # ── Section header ──────────────────────────────────────────────────────
    st.markdown(
        "**📅 可排班時間**  \n"
        "<small>勾選員工可接受排班的時間段（每格 30 分鐘）</small>",
        unsafe_allow_html=True,
    )

    # ── Global quick-select ─────────────────────────────────────────────────
    qc1, qc2, qc3 = st.columns(3)
    if qc1.button("✅ 全選", key=f"{key}_all"):
        df = pd.DataFrame(True, index=TIME_SLOTS, columns=DAYS)
        df.index.name = "時間"
        st.session_state[state_key] = df
        st.rerun()
    if qc2.button("❌ 全清", key=f"{key}_clear"):
        df = pd.DataFrame(False, index=TIME_SLOTS, columns=DAYS)
        df.index.name = "時間"
        st.session_state[state_key] = df
        st.rerun()
    if qc3.button("🗓 僅平日（週一～週五）", key=f"{key}_weekday"):
        df = pd.DataFrame(False, index=TIME_SLOTS, columns=DAYS)
        df.index.name = "時間"
        for day in ["週一", "週二", "週三", "週四", "週五"]:
            df[day] = True
        st.session_state[state_key] = df
        st.rerun()

    # ── Business hours quick-apply ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("**🏢 一鍵套用營業時間**")

    bh1, bh2 = st.columns(2)
    biz_start = bh1.time_input(
        "營業開始時間", value=dt_time(11, 0), key=f"{key}_biz_start"
    )
    biz_end = bh2.time_input(
        "營業結束時間", value=dt_time(21, 0), key=f"{key}_biz_end"
    )

    # Slots that fall within [biz_start, biz_end)
    biz_slots = [
        t for t in TIME_SLOTS
        if biz_start <= dt_time(int(t[:2]), int(t[3:])) < biz_end
    ]

    st.caption(
        f"將把 {biz_start.strftime('%H:%M')}–{biz_end.strftime('%H:%M')} "
        f"（共 {len(biz_slots)} 個時段，{len(biz_slots)*0.5:.1f} 小時）套用至所選天。"
    )

    # Per-day apply buttons
    day_cols = st.columns(7)
    for i, (dk, dl) in enumerate(zip(DAY_KEYS, DAYS)):
        if day_cols[i].button(
            dl, key=f"{key}_biz_{dk}",
            help=f"將 {biz_start.strftime('%H:%M')}–{biz_end.strftime('%H:%M')} 套用至{dl}"
        ):
            df = st.session_state[state_key].copy()
            df[dl] = False
            for slot in biz_slots:
                df.at[slot, dl] = True
            st.session_state[state_key] = df
            st.rerun()

    app1, app2 = st.columns(2)
    if app1.button("🗓 套用至所有平日（週一～週五）", key=f"{key}_biz_weekdays"):
        df = st.session_state[state_key].copy()
        for dl in ["週一", "週二", "週三", "週四", "週五"]:
            df[dl] = False
            for slot in biz_slots:
                df.at[slot, dl] = True
        st.session_state[state_key] = df
        st.rerun()
    if app2.button("📅 套用至全週（週一～週日）", key=f"{key}_biz_allweek"):
        df = pd.DataFrame(False, index=TIME_SLOTS, columns=DAYS)
        df.index.name = "時間"
        for dl in DAYS:
            for slot in biz_slots:
                df.at[slot, dl] = True
        st.session_state[state_key] = df
        st.rerun()

    # ── Timetable ───────────────────────────────────────────────────────────
    st.markdown("---")
    col_cfg = {day: st.column_config.CheckboxColumn(day, default=False) for day in DAYS}
    edited = st.data_editor(
        st.session_state[state_key],
        column_config=col_cfg,
        use_container_width=True,
        height=520,
    )
    # Persist manual edits back to session state for next rerun
    st.session_state[state_key] = edited
    return edited


st.title("👥 員工管理_T")
st.markdown("---")

tab_list, tab_add, tab_edit = st.tabs(["📋 員工列表", "➕ 新增員工", "✏️ 編輯 / 刪除員工"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 – Employee list
# ══════════════════════════════════════════════════════════════════════════════
with tab_list:
    db = get_db()
    try:
        employees = db.query(Employee).order_by(Employee.id).all()
    finally:
        db.close()

    if not employees:
        st.info("目前尚無員工資料，請至「新增員工」頁籤建立。")
    else:
        df_list = pd.DataFrame(
            [
                {
                    "ID": e.id,
                    "姓名": e.name,
                    "職位": e.position or "—",
                    "時薪（美元）": f"${e.hourly_rate:.2f}",
                    "目標週工時": f"{e.target_hours:.1f} h",
                }
                for e in employees
            ]
        )
        st.dataframe(df_list, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("員工可排班時段預覽")
        sel_preview = st.selectbox(
            "選擇員工查看可排班時間表",
            [f"{e.name}  (ID: {e.id})" for e in employees],
            key="preview_sel",
        )
        sel_id_preview = int(sel_preview.split("ID: ")[1].rstrip(")"))
        prev_emp = next(e for e in employees if e.id == sel_id_preview)
        prev_df = avail_json_to_df(prev_emp.availability)

        summary_cols = st.columns(7)
        for i, day in enumerate(DAYS):
            count = int(prev_df[day].sum())
            summary_cols[i].metric(day, f"{count} 格", f"{count * 0.5:.1f} h")

        st.dataframe(
            prev_df.map(lambda x: "✅" if x else ""),
            use_container_width=True,
            height=380,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 – Add employee
# ══════════════════════════════════════════════════════════════════════════════
with tab_add:
    st.subheader("新增員工")

    ac1, ac2, ac3, ac4 = st.columns(4)
    with ac1:
        add_name = st.text_input("姓名 *", key="add_name")
    with ac2:
        add_position = st.text_input("職位", key="add_position")
    with ac3:
        add_rate = st.number_input(
            "時薪（美元）*",
            min_value=0.01,
            value=16.00,
            step=0.25,
            format="%.2f",
            key="add_rate",
        )
    with ac4:
        add_target_hours = st.number_input(
            "目標週工時（小時）",
            min_value=1.0,
            max_value=168.0,
            value=40.0,
            step=0.5,
            format="%.1f",
            key="add_target_hours",
        )

    st.markdown("---")
    add_avail_df = render_avail_editor(key="add")

    st.markdown("---")
    if st.button("✅ 新增員工", type="primary", key="add_submit"):
        if not add_name.strip():
            st.error("❌ 姓名欄位不能為空。")
        else:
            avail_json = avail_df_to_json(add_avail_df)
            db = get_db()
            try:
                emp = Employee(
                    name=add_name.strip(),
                    position=add_position.strip(),
                    hourly_rate=add_rate,
                    target_hours=add_target_hours,
                    availability=avail_json,
                )
                db.add(emp)
                db.commit()
                st.success(f"✅ 員工「{add_name.strip()}」已新增！")
                st.balloons()
            finally:
                db.close()
            # Reset timetable state so next add starts blank
            st.session_state.pop("add_df_state", None)
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 – Edit / Delete employee
# ══════════════════════════════════════════════════════════════════════════════
with tab_edit:
    db = get_db()
    try:
        employees_ed = db.query(Employee).order_by(Employee.id).all()
    finally:
        db.close()

    if not employees_ed:
        st.info("目前尚無員工資料。")
        st.stop()

    emp_options = {f"{e.name}  (ID: {e.id})": e.id for e in employees_ed}
    selected_label = st.selectbox("選擇要操作的員工", list(emp_options.keys()), key="edit_sel")
    selected_id = emp_options[selected_label]

    db = get_db()
    try:
        sel_emp = db.query(Employee).filter(Employee.id == selected_id).first()
        snap = {
            "name": sel_emp.name,
            "position": sel_emp.position or "",
            "hourly_rate": float(sel_emp.hourly_rate),
            "target_hours": float(sel_emp.target_hours) if sel_emp.target_hours is not None else 40.0,
            "availability": sel_emp.availability or "{}",
        }
    finally:
        db.close()

    st.markdown("---")
    col_ed, col_dl = st.columns([3, 2])

    # ── Sync form fields when selected employee changes ─────────────────────
    if st.session_state.get("_edit_last_id") != selected_id:
        st.session_state["ed_name"]         = snap["name"]
        st.session_state["ed_pos"]          = snap["position"]
        st.session_state["ed_rate"]         = snap["hourly_rate"]
        st.session_state["ed_target_hours"] = snap["target_hours"]
        st.session_state["_edit_last_id"]   = selected_id

    # ── Edit panel ─────────────────────────────────────────────────────────
    with col_ed:
        st.markdown("### ✏️ 編輯員工資料")
        ec1, ec2, ec3, ec4 = st.columns(4)
        with ec1:
            ed_name = st.text_input("姓名", key="ed_name")
        with ec2:
            ed_pos = st.text_input("職位", key="ed_pos")
        with ec3:
            ed_rate = st.number_input(
                "時薪",
                min_value=0.01,
                step=0.25,
                format="%.2f",
                key="ed_rate",
            )
        with ec4:
            ed_target_hours = st.number_input(
                "目標週工時（小時）",
                min_value=1.0,
                max_value=168.0,
                step=0.5,
                format="%.1f",
                key="ed_target_hours",
            )

        st.markdown("---")
        ed_avail_df = render_avail_editor(
            key=f"edit_{selected_id}", initial_json=snap["availability"]
        )

        st.markdown("---")
        if st.button("💾 儲存變更", type="primary", key="ed_save"):
            if not ed_name.strip():
                st.error("❌ 姓名欄位不能為空。")
            else:
                avail_json = avail_df_to_json(ed_avail_df)
                db = get_db()
                try:
                    emp_obj = db.query(Employee).filter(Employee.id == selected_id).first()
                    emp_obj.name = ed_name.strip()
                    emp_obj.position = ed_pos.strip()
                    emp_obj.hourly_rate = ed_rate
                    emp_obj.target_hours = ed_target_hours
                    emp_obj.availability = avail_json
                    db.commit()
                    st.success("✅ 員工資料已更新！")
                finally:
                    db.close()
                # Force reload from DB on next visit
                st.session_state.pop(f"edit_{selected_id}_df_state", None)
                st.rerun()

    # ── Delete panel ───────────────────────────────────────────────────────
    with col_dl:
        st.markdown("### 🗑️ 刪除員工")
        st.warning(
            f"即將刪除員工：**{snap['name']}**\n\n"
            "⚠️ 注意：此操作會同時刪除該員工的所有班次記錄，且無法復原。"
        )
        confirm_delete = st.checkbox("我確認要刪除此員工及其所有班次", key="confirm_del")
        if st.button("確認刪除", type="primary", disabled=not confirm_delete, key="del_btn"):
            db = get_db()
            try:
                db.query(Shift).filter(Shift.employee_id == selected_id).delete()
                db.query(Employee).filter(Employee.id == selected_id).delete()
                db.commit()
                st.success(f"✅ 員工「{snap['name']}」及其班次已刪除！")
            finally:
                db.close()
            st.rerun()
