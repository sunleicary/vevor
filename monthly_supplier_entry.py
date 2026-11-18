"""Minimal monthly supplier KPI entry and display. No automatic scoring."""
import os
import sqlite3
from datetime import datetime, timezone
import pandas as pd
import streamlit as st

DB = os.environ.get("KPI_DB_PATH", os.path.join(os.path.dirname(__file__), "supplier_kpi.db"))
METRICS = ["提柜及时率", "送仓时效达成率", "送仓准时率", "送仓准确率",
           "还空柜及时率", "文件返回及时率", "系统数据准确性"]

def connect():
    conn = sqlite3.connect(DB, timeout=20)
    conn.execute("""CREATE TABLE IF NOT EXISTS supplier_monthly_kpi (
        month TEXT NOT NULL, supplier TEXT NOT NULL, metric TEXT NOT NULL,
        score REAL, note TEXT NOT NULL DEFAULT '', updated_by TEXT NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(month,supplier,metric))""")
    conn.commit()
    return conn

def show_monthly_supplier_entry(df, user):
    st.title("港后供应商 KPI 考核｜月度数据补录")
    st.caption("当前仅提供月度 KPI 数据补录、数据库保存及已录入数据展示。暂不自动计算、排名或判定违约。")
    month = st.text_input("考核月份（YYYY-MM）", value=pd.Timestamp.today().strftime("%Y-%m"),
                          key="monthly_entry_month")
    try:
        parsed = pd.Period(month, freq="M")
        if str(parsed) != month or len(month) != 7:
            raise ValueError()
    except ValueError:
        st.error("请输入正确的考核月份，例如 2026-10。")
        return
    supplier_names = sorted(set(df["港后拖车行"].fillna("").astype(str).str.strip()) -
                            {"", "nan", "None", "港后拖车测试"})
    with connect() as conn:
        existing = pd.read_sql_query(
            "SELECT month,supplier,metric,score,note,updated_by,updated_at "
            "FROM supplier_monthly_kpi WHERE month=? ORDER BY supplier,metric",
            conn, params=(month,))
    st.subheader("已保存的月度考核数据")
    if existing.empty:
        st.info("该月份尚无已保存的 KPI 考核数据。")
    else:
        st.dataframe(existing.rename(columns={"month":"考核月份","supplier":"港后拖车商",
            "metric":"KPI指标","score":"考核值（%）","note":"备注/依据",
            "updated_by":"更新人","updated_at":"更新时间"}),
            hide_index=True, use_container_width=True, height=370)
        st.download_button("导出当前月份已保存数据", existing.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"港后供应商KPI补录_{month}.csv", mime="text/csv",
                           key="monthly_entry_export")
    st.subheader("补录或修改供应商月度 KPI")
    if user.get("role") != "管理员":
        st.info("仅管理员可补录或修改；其他用户可查看已保存的数据。")
        return
    choices = sorted(set(supplier_names) | set(existing["supplier"].tolist()))
    supplier = st.selectbox("港后拖车商（仅港后拖车行）", choices,
                            index=None, placeholder="请选择供应商", key="monthly_entry_supplier")
    if not supplier:
        st.info("请选择供应商开始补录。")
        return
    selected = existing[existing["supplier"].eq(supplier)].set_index("metric")
    rows = []
    for metric in METRICS:
        old = selected.loc[metric] if metric in selected.index else None
        rows.append({"KPI指标":metric,
                     "考核值（%）":float(old["score"]) if old is not None and pd.notna(old["score"]) else None,
                     "备注/依据":str(old["note"]) if old is not None else ""})
    with st.form("monthly_supplier_kpi_form"):
        edited = st.data_editor(pd.DataFrame(rows), hide_index=True, num_rows="fixed",
            use_container_width=True, disabled=["KPI指标"],
            column_config={"考核值（%）":st.column_config.NumberColumn(
                "考核值（%）", min_value=0.0, max_value=100.0, step=0.01, format="%.2f"),
                "备注/依据":st.column_config.TextColumn("备注/依据")})
        save = st.form_submit_button("保存该供应商本月 KPI 数据", type="primary")
    if save:
        values = pd.to_numeric(edited["考核值（%）"], errors="coerce")
        if values.notna().any() and ((values.dropna() < 0) | (values.dropna() > 100)).any():
            st.error("考核值必须在 0–100% 之间。")
            return
        now = datetime.now(timezone.utc).isoformat()
        records = [(month,supplier,str(row["KPI指标"]),
                    float(row["考核值（%）"]) if pd.notna(row["考核值（%）"]) else None,
                    str(row["备注/依据"]) if pd.notna(row["备注/依据"]) else "",
                    user.get("username","管理员"),now)
                   for _,row in edited.iterrows()]
        try:
            with connect() as conn:
                conn.executemany("""INSERT INTO supplier_monthly_kpi
                    (month,supplier,metric,score,note,updated_by,updated_at)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(month,supplier,metric) DO UPDATE SET
                    score=excluded.score,note=excluded.note,
                    updated_by=excluded.updated_by,updated_at=excluded.updated_at""", records)
                conn.commit()
            st.success("月度 KPI 数据已保存到数据库。")
            st.rerun()
        except (sqlite3.Error, OSError) as exc:
            st.error(f"保存失败：{exc}")
    st.caption("数据库默认保存在应用本地。若部署于 Streamlit Community Cloud，重启/重新部署可能清除文件；"
               "要永久保存请使用持久化磁盘或托管数据库，并定期备份。")
