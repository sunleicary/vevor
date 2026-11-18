"""Import the original monthly KPI workbook once and browse saved overdue rows."""
import os
import re
import sqlite3
from datetime import datetime, timezone
from io import BytesIO
import pandas as pd
import streamlit as st

DB = os.environ.get("KPI_DB_PATH", os.path.join(os.path.dirname(__file__), "supplier_kpi.db"))
SHEETS = {
    "港后提柜及时率": ("是否及时", {"不及时", "否", "超时"}),
    "送仓准时率": ("是否准时", {"不准时", "否"}),
    "送仓时效": ("是否超时", {"是", "超时"}),
    "提空及时率": ("是否超时", {"是", "超时"}),
    "还柜及时率": ("是否超时", {"是", "超时"}),
}
def connect():
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS kpi_imported_details(
        month TEXT NOT NULL, metric TEXT NOT NULL, order_no TEXT NOT NULL,
        supplier TEXT NOT NULL, region TEXT, container_no TEXT,
        status TEXT, overdue_days TEXT, standard TEXT, actual TEXT,
        destination TEXT, source_file TEXT, imported_at TEXT,
        PRIMARY KEY(month,metric,order_no))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS kpi_import_batches(
        month TEXT PRIMARY KEY, source_file TEXT, imported_at TEXT,
        row_count INTEGER NOT NULL)""")
    conn.commit()
    return conn

def parse_workbook(payload, assessment_month):
    from openpyxl import load_workbook
    book = load_workbook(BytesIO(payload), read_only=True, data_only=True)
    if any(sheet not in book.sheetnames for sheet in SHEETS):
        raise ValueError("缺少KPI工作表：" + "、".join(s for s in SHEETS if s not in book.sheetnames))
    records = []
    months = set()
    for metric, (status_col, fail_values) in SHEETS.items():
        ws = book[metric]
        header = [str(v).strip() if v is not None else "" for v in next(ws.iter_rows(min_row=2,max_row=2,values_only=True))]
        idx = {v:i for i,v in enumerate(header) if v}
        required = ["月份","排柜单号","港后拖车行",status_col,"目的仓国家"]
        if any(k not in idx for k in required):
            raise ValueError(f"{metric} 缺少字段：" + "、".join(k for k in required if k not in idx))
        def get(row,name):
            i=idx.get(name)
            return str(row[i]).strip() if i is not None and i<len(row) and row[i] is not None else ""
        for row in ws.iter_rows(min_row=3,values_only=True):
            order = get(row,"排柜单号")
            if not order:
                continue
            country = get(row,"目的仓国家").upper()
            if country not in {"AMERICA","美国","USA","US","UNITED STATES","UNITED STATES OF AMERICA"}:
                continue
            supplier = get(row,"港后拖车行")
            if not supplier or supplier in {"nan","None","港后拖车测试"}:
                continue
            raw_month = get(row,"月份")
            try:
                m=int(float(raw_month))
                if m<1 or m>12:continue
            except (ValueError,TypeError):
                continue
            month=assessment_month
            if m != int(assessment_month[-2:]):
                raise ValueError(f"{metric} 的源文件月份 {m} 与所选考核月份 {assessment_month} 不一致，请核对。")
            months.add(month)
            status=get(row,status_col)
            overdue=get(row,"超时天数") or get(row,"超LFD天数")
            records.append((month,metric,order,supplier,get(row,"目的仓物流区域"),
                get(row,"箱号"),status,overdue,
                get(row,"标准时效") or get(row,"时效标准"),
                get(row,"提空时效") or get(row,"还柜时效") or get(row,"送仓时效"),
                get(row,"目的仓"), "", ""))
    book.close()
    if not records:
        raise ValueError("文件中未找到美国港后拖车商的有效KPI记录。")
    return records, months

def show_monthly_supplier_entry(df, user):
    st.title("港后供应商 KPI 考核｜月度文件导入与超时明细")
    st.caption("一次上传整份KPI工作簿，分别查看五项指标的超时/不及时记录。月份来自Excel各工作表的「月份」字段。")
    try:
        with connect() as conn:
            batches=pd.read_sql_query("SELECT * FROM kpi_import_batches ORDER BY month DESC",conn)
    except (sqlite3.Error,OSError) as exc:
        st.error(f"KPI数据库无法读取：{exc}")
        return
    if user.get("role")=="管理员":
        with st.expander("统一导入月度KPI文件",expanded=batches.empty):
            uploaded=st.file_uploader("上传国际物流服务商KPI工作簿",type=["xlsx"],key="kpi_unified_upload")
            assessment_month=st.selectbox("考核月份",
                [f"{y}-{m:02d}" for y in range(2024, 2036) for m in range(1,13)],
                index=(2026-2024)*12+9, key="kpi_import_month")
            if st.button("解析并保存五项KPI明细",disabled=uploaded is None,type="primary"):
                try:
                    rows,months=parse_workbook(uploaded.getvalue(),assessment_month)
                    # Verify uniqueness before changing any stored data.
                    keys=[(r[0],r[1],r[2]) for r in rows]
                    if len(keys)!=len(set(keys)):
                        raise ValueError("原文件存在同一月份、同一指标下重复的排柜单号，请先核对原始数据。")
                    now=datetime.now(timezone.utc).isoformat()
                    records=[r[:-2]+(uploaded.name,now) for r in rows]
                    with connect() as conn:
                        for month in months:
                            conn.execute("DELETE FROM kpi_imported_details WHERE month=?",(month,))
                            conn.execute("DELETE FROM kpi_import_batches WHERE month=?",(month,))
                        conn.executemany("""INSERT INTO kpi_imported_details
                            (month,metric,order_no,supplier,region,container_no,status,
                            overdue_days,standard,actual,destination,source_file,imported_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",records)
                        conn.executemany("""INSERT INTO kpi_import_batches(month,source_file,imported_at,row_count)
                            VALUES (?,?,?,?)""",[(m,uploaded.name,now,sum(r[0]==m for r in rows)) for m in months])
                        conn.commit()
                    st.success(f"已保存 {len(records):,} 条KPI明细，考核月份：{', '.join(sorted(months))}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"导入失败，原有数据未覆盖：{exc}")
            st.caption("重复导入同一月份将替换该月份已有的五项指标数据。业务主键为排柜单号，箱号允许重复。")
    if batches.empty:
        st.info("尚未导入月度KPI文件，请管理员上传后查看。")
        return
    months=batches["month"].tolist()
    month=st.selectbox("已导入考核月份",months,key="kpi_saved_month")
    batch=batches[batches["month"].eq(month)].iloc[0]
    st.caption(f"来源文件：{batch['source_file']}｜已保存记录：{int(batch['row_count']):,}｜导入时间(UTC)：{batch['imported_at']}")
    with connect() as conn:
        data=pd.read_sql_query("SELECT * FROM kpi_imported_details WHERE month=?",conn,params=(month,))
    if data.empty:
        st.info("该月份无可显示记录。")
        return
    c1,c2=st.columns(2)
    with c1:
        region=st.selectbox("目的仓区域",["全部"]+sorted(data["region"].fillna("").unique().tolist()),key="kpi_saved_region")
    with c2:
        supplier=st.selectbox("港后拖车商",["全部"]+sorted(data["supplier"].unique().tolist()),key="kpi_saved_supplier")
    if region!="全部":data=data[data["region"].eq(region)]
    if supplier!="全部":data=data[data["supplier"].eq(supplier)]
    tabs=st.tabs(list(SHEETS))
    for tab,(metric,(status_col,fail_values)) in zip(tabs,SHEETS.items()):
        with tab:
            subset=data[data["metric"].eq(metric)].copy()
            state=subset["status"].fillna("").astype(str).str.strip()
            # Source statuses are authoritative; question marks and blanks remain pending.
            late=subset[state.isin(fail_values)].copy()
            unknown=subset[~state.isin(fail_values) & ~state.isin(
                {"及时","准时","否","未超时","不及时","不准时","是","超时"})].copy()
            a,b,c=st.columns(3)
            a.metric("本项记录",f"{len(subset):,}")
            b.metric("超时/不及时",f"{len(late):,}")
            c.metric("状态待核实",f"{len(unknown):,}")
            if not late.empty:
                summary=late.groupby("supplier").size().reset_index(name="超时业务数").sort_values("超时业务数",ascending=False)
                st.dataframe(summary.rename(columns={"supplier":"港后拖车商"}),hide_index=True,use_container_width=True)
            cols={"order_no":"排柜单号","supplier":"港后拖车商","region":"目的仓区域",
                  "container_no":"箱号","status":"原始考核状态","overdue_days":"超时天数",
                  "standard":"标准时效","actual":"实际时效","destination":"目的仓"}
            st.markdown("#### 超时/不及时逐单明细")
            st.dataframe(late[list(cols)].rename(columns=cols),hide_index=True,use_container_width=True,height=390)
            st.download_button("导出本指标超时明细",late[list(cols)].rename(columns=cols).to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"{month}_{metric}_超时明细.csv",mime="text/csv",key=f"kpi_export_{metric}")
            if not unknown.empty:
                with st.expander(f"待核实记录（{len(unknown):,}）"):
                    st.dataframe(unknown[list(cols)].rename(columns=cols),hide_index=True,use_container_width=True)
    st.warning("数据保存在独立SQLite文件中。若Streamlit云端运行环境不提供持久化磁盘，重启后可能丢失；"
               "生产环境需配置KPI_DB_PATH到持久化存储。")
