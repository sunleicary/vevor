"""Persisted monthly post-port supplier KPI assessments.
SQLite is stored separately from the replaceable imported containers database.
"""
import os
import sqlite3
from datetime import datetime, timezone
import pandas as pd
import streamlit as st

DB_PATH = os.environ.get("KPI_DB_PATH", os.path.join(os.path.dirname(__file__), "supplier_kpi.db"))
METRICS = ["送仓准时率", "送仓时效达成率", "送仓准确率", "还空柜及时率", "文件返回及时率", "系统数据准确性"]
STATUSES = ["待核实", "达标", "不达标", "免责"]

def connection():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.execute("""CREATE TABLE IF NOT EXISTS kpi_reviews (
        month TEXT NOT NULL, order_no TEXT NOT NULL, metric TEXT NOT NULL,
        status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
        updated_by TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
        PRIMARY KEY(month, order_no, metric))""")
    conn.commit()
    return conn

def load_reviews(month):
    with connection() as conn:
        return pd.read_sql_query("SELECT * FROM kpi_reviews WHERE month=?", conn, params=(month,))

def save_reviews(rows, month, operator):
    now = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        conn.executemany("""INSERT INTO kpi_reviews(month,order_no,metric,status,note,updated_by,updated_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(month,order_no,metric) DO UPDATE SET
            status=excluded.status,note=excluded.note,
            updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
            [(month, str(row["排柜单号"]).strip(), str(row["KPI指标"]).strip(),
              str(row["考核结果"]).strip(), str(row["证据说明"]).strip(), operator, now)
             for _, row in rows.iterrows()])
        conn.commit()

def show_supplier_kpi(df, user):
    st.title("📊 美国港后供应商月度 KPI 评分与补录")
    st.caption("LFD=提柜LFD；预计还柜时间=还柜LFD。提柜及时率分母为该供应商考核月全部作业排柜单数。"
               "业务主键为排柜单号，供应商仅按港后拖车行。")
    st.warning("提柜及时率按本次指定的严格口径：实际提柜日期早于提柜LFD才计达标；等于LFD不计达标。"
               "缺少提柜日期或LFD同样不计入分子。其他六项需补录或审核，不自动推断违约。")
    data = df.copy()
    data["供应商"] = data["港后拖车行"].fillna("").astype(str).str.strip()
    data = data[data["供应商"].ne("") & ~data["供应商"].isin(["港后拖车测试", "nan", "None"])].copy()
    for col in ["ETA日期", "LFD", "进口实际提箱时间", "预计还柜时间", "实际还柜日期"]:
        if col not in data.columns:
            data[col] = ""
        data[col + "_parsed"] = pd.to_datetime(data[col], errors="coerce", format="mixed")
    data["排柜单号"] = data["排柜单号"].fillna("").astype(str).str.strip()
    data = data[data["排柜单号"].ne("")].drop_duplicates("排柜单号")
    month = st.selectbox("考核月份（按ETA日期归属）",
                         pd.period_range("2025-01", pd.Timestamp.today().to_period("M") + 3,
                                         freq="M").astype(str).tolist()[::-1],
                         index=3, key="persist_kpi_month")
    start = pd.Period(month).start_time
    end = pd.Period(month).end_time
    data = data[data["ETA日期_parsed"].between(start, end)].copy()
    if data.empty:
        st.info("所选月份没有美国港后业务记录。")
        return
    data["区域"] = data["区域"].fillna("其他区域")
    c1, c2 = st.columns(2)
    with c1:
        area = st.selectbox("区域", ["全部区域"] + sorted(data["区域"].unique().tolist()), key="persist_kpi_area")
    if area != "全部区域":
        data = data[data["区域"].eq(area)]
    with c2:
        vendor = st.selectbox("港后拖车商", ["全部供应商"] + sorted(data["供应商"].unique().tolist()), key="persist_kpi_vendor")
    if vendor != "全部供应商":
        data = data[data["供应商"].eq(vendor)]
    if data.empty:
        st.info("当前筛选没有业务。")
        return
    pickup = data["进口实际提箱时间_parsed"]
    pickup_lfd = data["LFD_parsed"]
    data["提柜达标"] = pickup.notna() & pickup_lfd.notna() & (pickup.dt.normalize() < pickup_lfd.dt.normalize())
    data["提柜LFD状态"] = "未达标/待核实"
    data.loc[data["提柜达标"], "提柜LFD状态"] = "早于LFD"
    data.loc[pickup.isna() | pickup_lfd.isna(), "提柜LFD状态"] = "缺少时间（计入分母）"
    data.loc[pickup.notna() & pickup_lfd.notna() &
             pickup.dt.normalize().eq(pickup_lfd.dt.normalize()), "提柜LFD状态"] = "LFD当天提柜（不计达标）"
    st.markdown("### 提柜及时率（系统自动计算）")
    group = data.groupby(["区域", "供应商"], dropna=False).agg(
        本月作业柜数=("排柜单号", "nunique"),
        早于提柜LFD柜数=("提柜达标", "sum")).reset_index()
    group["提柜及时率%"] = (100 * group["早于提柜LFD柜数"] / group["本月作业柜数"]).round(2)
    st.dataframe(group, hide_index=True, use_container_width=True)
    st.markdown("### 其他六项 KPI 数据补录（保存到数据库）")
    st.caption("补录记录按考核月份 + 排柜单号 + KPI指标唯一保存；下次打开会自动读取。"
               "仅达标/不达标进入该指标分母，免责与待核实不计入。")
    reviews = load_reviews(month)
    base = data[["排柜单号", "供应商", "区域", "箱号"]].copy()
    template = base.loc[base.index.repeat(len(METRICS))].reset_index(drop=True)
    template["KPI指标"] = METRICS * len(base)
    template = template.merge(reviews[["order_no", "metric", "status", "note"]], how="left",
                              left_on=["排柜单号", "KPI指标"], right_on=["order_no", "metric"])
    template["考核结果"] = template["status"].fillna("待核实")
    template["证据说明"] = template["note"].fillna("")
    editable = template[["排柜单号", "箱号", "区域", "供应商", "KPI指标", "考核结果", "证据说明"]]
    if user.get("role") == "管理员":
        with st.form("persist_kpi_edit_form"):
            changed = st.data_editor(editable, hide_index=True, use_container_width=True,
                height=440, num_rows="fixed", disabled=["排柜单号", "箱号", "区域", "供应商", "KPI指标"],
                column_config={"考核结果": st.column_config.SelectboxColumn(
                    "考核结果", options=STATUSES, required=True),
                    "证据说明": st.column_config.TextColumn("证据说明")})
            submitted = st.form_submit_button("保存补录结果到数据库", type="primary")
        if submitted:
            invalid = ~changed["考核结果"].isin(STATUSES)
            evidence_missing = (changed["考核结果"].isin(["达标", "不达标", "免责"])
                                & changed["证据说明"].fillna("").astype(str).str.strip().eq(""))
            if invalid.any() or evidence_missing.any():
                st.error("状态不合法，或已确认的达标/不达标/免责记录缺少证据说明。")
            else:
                to_save = changed
                try:
                    save_reviews(to_save, month, user.get("username", "管理员"))
                    st.success(f"已保存 {len(to_save)} 条记录至独立KPI数据库。")
                    st.rerun()
                except (OSError, sqlite3.Error) as exc:
                    st.error(f"数据库保存失败：{exc}")
    else:
        st.dataframe(editable, hide_index=True, use_container_width=True, height=420)
        st.info("仅管理员可以补录和修改考核结果。")
    st.markdown("### 六项补录指标评分")
    assessed = template[["供应商", "区域", "KPI指标", "考核结果"]].copy()
    summary = assessed.groupby(["区域", "供应商", "KPI指标", "考核结果"]).size().unstack(fill_value=0)
    for name in STATUSES:
        if name not in summary.columns:
            summary[name] = 0
    summary["有效样本"] = summary["达标"] + summary["不达标"]
    summary["得分%"] = (100 * summary["达标"] / summary["有效样本"].replace(0, float("nan"))).round(2)
    st.dataframe(summary.reset_index(), hide_index=True, use_container_width=True)
    st.download_button("导出提柜及时率CSV", group.to_csv(index=False).encode("utf-8-sig"),
                       "提柜及时率月度考核.csv", "text/csv", key="persist_pickup_export")
    st.download_button("导出补录数据CSV（备份）", editable.to_csv(index=False).encode("utf-8-sig"),
                       "供应商KPI补录备份.csv", "text/csv", key="persist_reviews_export")
    st.warning("数据库文件默认位于应用本地磁盘。Streamlit Community Cloud重启或重新部署可能清除本地文件，"
               "因此目前不能保证跨重启永久保存。生产环境应设置KPI_DB_PATH为持久化磁盘路径，"
               "或迁移至托管数据库；请定期导出备份。")
