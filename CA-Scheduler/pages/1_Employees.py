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

# ── Dialog for save success ────────────────────────────────────────────────

@st.dialog("✅ 儲存成功")
def show_save_success():
    st.balloons()
    st.markdown("### 員工資料已成功變更！")
    if st.button("關閉", use_container_width=True):
        st.rerun()

@st.dialog("🎉 歡迎新員工加入")
def show_welcome_new_employee(emp_name: str):
    st.balloons()
    st.markdown(f"### 🎊 歡迎 **{emp_name}** 加入！")
    if st.button("返回", use_container_width=True):
        st.session_state.pop("add_df_state", None)
        st.rerun()

@st.dialog("🗑️ 確認刪除")
def show_confirm_delete(emp_name: str, emp_id: int):
    st.error(f"⚠️ 即將永久刪除員工：**{emp_name}**", icon="⚠️")
    st.markdown("此操作會同時刪除該員工的所有班次記錄，且無法復原。")
    col1, col2 = st.columns(2)
    if col1.button("❌ 取消", use_container_width=True):
        st.rerun()
    if col2.button("🗑️ 確認刪除", type="primary", use_container_width=True):
        db = get_db()
        try:
            db.query(Shift).filter(Shift.employee_id == emp_id).delete()
            db.query(Employee).filter(Employee.id == emp_id).delete()
            db.commit()
            st.success(f"✅ 員工「{emp_name}」及其班次已刪除！")
        finally:
            db.close()
        st.session_state.pop("confirm_del", None)
        st.rerun()

# ── Availability helpers ──────────────────────────────────────────────────────

DAYS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
DAY_KEYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

DEPT_OPTIONS = ["", "管理", "行政", "前台", "後廚"]
DEPT_POSITIONS: dict = {
    "": [],
    "管理": ["店長", "區經理", "其他"],
    "行政": ["行政"],
    "前台": ["前台"],
    "後廚": ["Precook", "Cook", "Dishwasher"],
}

TIME_SLOTS: list[str] = [
    f"{h:02d}:{m:02d}" for h in range(10, 24) for m in (0, 15, 30, 45)
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

    # ── Business hours quick-apply ──────────────────────────────────────────
    st.markdown("**🏢 一鍵套用可排班時間**")

    bh1, bh2 = st.columns(2)
    biz_start = bh1.time_input(
        "可排班開始時間", value=dt_time(11, 0), key=f"{key}_biz_start"
    )
    biz_end = bh2.time_input(
        "可排班結束時間", value=dt_time(22, 0), key=f"{key}_biz_end"
    )

    # Slots that fall within [biz_start, biz_end)
    biz_slots = [
        t for t in TIME_SLOTS
        if biz_start <= dt_time(int(t[:2]), int(t[3:])) <= biz_end
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

    app1, app2, app3 = st.columns(3)
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
    if app3.button("❌ 全清", key=f"{key}_clear"):
        df = pd.DataFrame(False, index=TIME_SLOTS, columns=DAYS)
        df.index.name = "時間"
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
        key=f"{key}_timetable",
    )
    # Persist manual edits back to session state for next rerun
    st.session_state[state_key] = edited
    return edited


st.title("👥 員工管理")
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
                    "部門": e.department or "—",
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

    ac1, ac2, ac3, ac4, ac5 = st.columns(5)
    with ac1:
        add_name = st.text_input("姓名 *", key="add_name")
    with ac2:
        add_dept = st.selectbox("部門", options=DEPT_OPTIONS, key="add_dept")
    with ac3:
        add_pos_opts = DEPT_POSITIONS.get(add_dept, [])
        if st.session_state.get("add_position") not in add_pos_opts:
            st.session_state["add_position"] = add_pos_opts[0] if add_pos_opts else ""
        add_position = st.selectbox("職位", options=add_pos_opts, key="add_position", disabled=not add_pos_opts)
    with ac4:
        add_rate = st.number_input(
            "時薪（美元）*",
            min_value=0.01,
            value=16.00,
            step=0.25,
            format="%.2f",
            key="add_rate",
        )
    with ac5:
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
                    department=add_dept.strip(),
                    position=(add_position or "").strip(),
                    hourly_rate=add_rate,
                    target_hours=add_target_hours,
                    availability=avail_json,
                )
                db.add(emp)
                db.commit()
                show_welcome_new_employee(add_name.strip())
            finally:
                db.close()


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
            "department": sel_emp.department or "",
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
        safe_dept = snap["department"] if snap["department"] in DEPT_OPTIONS else ""
        safe_pos_opts = DEPT_POSITIONS.get(safe_dept, [])
        safe_pos = snap["position"] if snap["position"] in safe_pos_opts else (safe_pos_opts[0] if safe_pos_opts else "")
        st.session_state["ed_name"]         = snap["name"]
        st.session_state["ed_dept"]         = safe_dept
        st.session_state["ed_pos"]          = safe_pos
        st.session_state["ed_rate"]         = snap["hourly_rate"]
        st.session_state["ed_target_hours"] = snap["target_hours"]
        st.session_state["_edit_last_id"]   = selected_id

    # ── Edit panel ─────────────────────────────────────────────────────────
    with col_ed:
        st.markdown("### ✏️ 編輯員工資料")
        ec1, ec2, ec3, ec4, ec5 = st.columns(5)
        with ec1:
            ed_name = st.text_input("姓名", key="ed_name")
        with ec2:
            ed_dept = st.selectbox("部門", options=DEPT_OPTIONS, key="ed_dept")
        with ec3:
            ed_pos_opts = DEPT_POSITIONS.get(ed_dept, [])
            if st.session_state.get("ed_pos") not in ed_pos_opts:
                st.session_state["ed_pos"] = ed_pos_opts[0] if ed_pos_opts else ""
            ed_pos = st.selectbox("職位", options=ed_pos_opts, key="ed_pos", disabled=not ed_pos_opts)
        with ec4:
            ed_rate = st.number_input(
                "時薪",
                min_value=0.01,
                step=0.25,
                format="%.2f",
                key="ed_rate",
            )
        with ec5:
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
                    emp_obj.department = ed_dept.strip()
                    emp_obj.position = (ed_pos or "").strip()
                    emp_obj.hourly_rate = ed_rate
                    emp_obj.target_hours = ed_target_hours
                    emp_obj.availability = avail_json
                    db.commit()
                    # Force reload from DB on next visit
                    st.session_state.pop(f"edit_{selected_id}_df_state", None)
                    show_save_success()
                finally:
                    db.close()

    # ── Delete panel ───────────────────────────────────────────────────────
    with col_dl:
        st.markdown("### 🗑️ 刪除員工")
        st.warning(
            f"即將刪除員工：**{snap['name']}**\n\n"
            "⚠️ 注意：此操作會同時刪除該員工的所有班次記錄，且無法復原。"
        )
        confirm_delete = st.checkbox("我確認要刪除此員工及其所有班次", key="confirm_del")
        if st.button("確認刪除", type="primary", disabled=not confirm_delete, key="del_btn"):
            show_confirm_delete(snap['name'], selected_id)
