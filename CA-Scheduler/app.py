"""
app.py – Main entry point for the CA Scheduler Streamlit application.
Run with:  streamlit run app.py

Link to Streamlit documentation: https://ca-scheduler-7q5hhzcqhdka9htmvkwbu9.streamlit.app/
"""

import os
import sys

# Ensure project root is importable from sub-pages as well
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

from database import init_db

st.set_page_config(
    page_title="加州排班系統",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Database bootstrap (idempotent) ────────────────────────────────────────
init_db()

# ── Home page content ──────────────────────────────────────────────────────
st.title("📅 加州時薪員工排班系統")
st.markdown("---")

col1, col2, col3 = st.columns(3)

with col1:
    st.info(
        "### 👥 員工管理\n"
        "新增、編輯、刪除員工基本資料及時薪設定。"
    )

with col2:
    st.info(
        "### 📆 班次排程\n"
        "建立、編輯、刪除班次，並以週曆視圖查看排班狀況。"
    )

with col3:
    st.info(
        "### 💰 薪資預覽\n"
        "查看正常、加班（1.5×）、雙倍薪（2×）明細及勞工法合規警示。"
    )

st.markdown("---")

st.markdown(
    """
    #### ⚖️ 本系統依據以下加州勞動法規自動計算薪資與提供合規提醒：

    | 規則 | 說明 |
    |------|------|
    | **每日加班** | 每日工時超過 8 小時按 1.5 倍、超過 12 小時按 2 倍計薪 |
    | **每週加班** | 每週正常工時超過 40 小時按 1.5 倍計薪 |
    | **第七連續工作日** | 連續第七個工作日前 8 小時按 1.5 倍、超過 8 小時按 2 倍計薪 |
    | **餐飲休息** | 工作超過 5 小時須提供 30 分鐘不間斷餐飲休息；超過 10 小時須再提供一次 |
    | **帶薪休息** | 每 4 小時工作需安排一次 10 分鐘帶薪休息 |
    """
)

st.caption(
    "本系統為本地單機應用，所有資料儲存於本機 SQLite 資料庫（ca_scheduler.db）。"
)
