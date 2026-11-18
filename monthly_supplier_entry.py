"""Global monthly KPI workbook import: preserve every source data row for reconciliation."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from io import BytesIO
import pandas as pd
import streamlit as st

DB = os.environ.get("KPI_DB_PATH", os.path.join(os.path.dirname(__file__), "supplier_kpi.db"))
SHEETS = ["港后提柜及时率", "送仓准时率", "送仓时效", "提空及时率", "还柜及时率", "台账"]

def connect():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("""CREATE TABLE IF NOT EXISTS kpi_raw_rows_v2(
        month TEXT NOT NULL, metric TEXT NOT NULL, source_row INTEGER NOT NULL,
        payload TEXT NOT NULL, source_file TEXT NOT NULL, imported_at TEXT NOT NULL,
        PRIMARY KEY(month,metric,source_row))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS kpi_batches_v2(
        month TEXT PRIMARY KEY, source_file TEXT NOT NULL, imported_at TEXT NOT NULL,
        row_count INTEGER NOT NULL)""")
    conn.commit()
    return conn

def parse_month(value, chosen_month):
    if value is None or str(value).strip() == "":
        return chosen_month
    if isinstance(value, datetime):
        m = value.month
        year = value.year
    else:
        raw = str(value).strip()
        try:
            if raw.replace(".0", "").isdigit() and int(float(raw)) <= 12:
                m = int(float(raw))
                year = int(chosen_month[:4])
            else:
                parsed = pd.to_datetime(raw, errors="raise")
                m, year = parsed.month, parsed.year
        except (ValueError, TypeError):
            raise ValueError(f"无法识别源文件月份：{raw}")
    month = f"{year}-{m:02d}"
    if month != chosen_month:
        raise ValueError(f"源文件月份 {month} 与所选考核月份 {chosen_month} 不一致。")
    return month

def parse_workbook(payload, month):
    from openpyxl import load_workbook
    book = load_workbook(BytesIO(payload), read_only=True, data_only=True)
    missing = [s for s in SHEETS if s not in book.sheetnames]
    if missing:
        book.close()
        raise ValueError("缺少工作表：" + "、".join(missing))
    rows = []
    counts = {}
    for sheet in SHEETS:
        ws = book[sheet]
        header_row = 1 if sheet == "台账" else 2
        headers = next(ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True))
        columns = [str(v).strip() if v is not None and str(v).strip()
                   else f"未命名列_{i+1}" for i,v in enumerate(headers)]
        if sheet != "台账" and "月份" not in columns:
            book.close()
            raise ValueError(f"{sheet} 缺少月份字段")
        count = 0
        for source_row, values in enumerate(ws.iter_rows(min_row=header_row+1, values_only=True), start=header_row+1):
            # Only skip completely empty Excel rows; do not filter by country, status,
            # supplier, order number or duplicates.
            if not any(v is not None and str(v).strip() for v in values):
                continue
            data = {}
            for i, col in enumerate(columns):
                v = values[i] if i < len(values) else None
                if isinstance(v, (datetime, pd.Timestamp)):
                    v = v.isoformat()
                data[col] = "" if v is None else str(v)
            if sheet != "台账":
                parse_month(data.get("月份"), month)
                if sheet == "送仓准时率" and not str(data.get("排柜单号", "")).strip():
                    continue
            rows.append((month, sheet, source_row, json.dumps(data, ensure_ascii=False, default=str)))
            count += 1
        counts[sheet] = count
    book.close()
    return rows, counts

def show_monthly_supplier_entry(df, user):
    st.title("港后供应商 KPI 考核｜全球原始数据核对")
    st.caption("统一导入全球五项 KPI 及台账；送仓准时率不展示排柜单号为空的记录，并通过排柜单号与台账匹配。")
    try:
        with connect() as conn:
            batches = pd.read_sql_query("SELECT * FROM kpi_batches_v2 ORDER BY month DESC", conn)
    except (sqlite3.Error, OSError) as exc:
        st.error(f"无法读取数据库：{exc}")
        return
    if user.get("role") == "管理员":
        with st.expander("统一导入 KPI 文件", expanded=batches.empty):
            uploaded = st.file_uploader("上传完整 KPI 工作簿", type=["xlsx"], key="kpi_global_upload")
            choices = [f"{y}-{m:02d}" for y in range(2024, 2036) for m in range(1,13)]
            now = datetime.now()
            default = f"{now.year}-{now.month:02d}"
            month = st.selectbox("考核月份", choices,
                                 index=choices.index(default) if default in choices else 0,
                                 key="kpi_global_month")
            if st.button("导入并保存全部原始记录", disabled=uploaded is None, type="primary"):
                try:
                    rows, counts = parse_workbook(uploaded.getvalue(), month)
                    timestamp = datetime.now(timezone.utc).isoformat()
                    with connect() as conn:
                        conn.execute("DELETE FROM kpi_raw_rows_v2 WHERE month=?", (month,))
                        conn.execute("DELETE FROM kpi_batches_v2 WHERE month=?", (month,))
                        conn.executemany("""INSERT INTO kpi_raw_rows_v2
                            (month,metric,source_row,payload,source_file,imported_at)
                            VALUES (?,?,?,?,?,?)""",
                            [(m,s,n,p,uploaded.name,timestamp) for m,s,n,p in rows])
                        conn.execute("""INSERT INTO kpi_batches_v2
                            (month,source_file,imported_at,row_count) VALUES (?,?,?,?)""",
                            (month,uploaded.name,timestamp,len(rows)))
                        conn.commit()
                    st.success(f"已保存 {len(rows):,} 条原始明细。")
                    st.dataframe(pd.DataFrame([{"指标":k,"导入记录数":v} for k,v in counts.items()]),
                                 hide_index=True,use_container_width=True)
                    st.rerun()
                except Exception as exc:
                    st.error(f"导入失败，原有数据保持不变：{exc}")
            st.caption("再次导入相同考核月份将覆盖该月原始记录；不会修改 Excel 中的原始考核结果。")
    if batches.empty:
        st.info("尚无已导入的全球 KPI 文件。")
        return
    selected = st.selectbox("已导入考核月份", batches["month"].tolist(), key="kpi_global_saved_month")
    batch = batches[batches["month"].eq(selected)].iloc[0]
    st.caption(f"来源文件：{batch['source_file']}｜总记录数：{int(batch['row_count']):,}")
    with connect() as conn:
        raw = pd.read_sql_query("""SELECT metric,source_row,payload FROM kpi_raw_rows_v2
            WHERE month=? ORDER BY metric,source_row""",conn,params=(selected,))
    counts = raw.groupby("metric").size().reindex(SHEETS, fill_value=0)
    st.dataframe(pd.DataFrame({"指标":SHEETS,"已保存记录数":counts.values}),
                 hide_index=True,use_container_width=True)
    tabs = st.tabs(SHEETS)
    for tab, metric in zip(tabs,SHEETS):
        with tab:
            part = raw[raw["metric"].eq(metric)]
            records = [json.loads(v) for v in part["payload"]]
            detail = pd.DataFrame(records)
            detail.insert(0,"序列号",range(1,len(detail)+1))
            detail.insert(1,"Excel原始行号",part["source_row"].tolist())
            if metric == "送仓准时率" and not detail.empty:
                ledger_part = raw[raw["metric"].eq("台账")]
                ledger_keys = set()
                for item in ledger_part["payload"]:
                    record = json.loads(item)
                    key = str(record.get("排柜单号", "")).strip()
                    if key:
                        ledger_keys.add(key)
                keys = detail["排柜单号"].fillna("").astype(str).str.strip()
                detail.insert(2, "台账匹配结果", keys.map(lambda k: "已匹配" if k in ledger_keys else "未匹配"))
                matched = int((detail["台账匹配结果"] == "已匹配").sum())
                st.caption(f"台账匹配：{matched:,} 条；未匹配：{len(detail)-matched:,} 条。仅展示排柜单号非空的送仓准时率记录。")
            st.metric("全部原始记录",f"{len(detail):,}")
            st.dataframe(detail,hide_index=True,use_container_width=True,height=540)
            st.download_button("导出全部明细CSV",
                detail.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{selected}_{metric}_全球全部明细.csv",
                mime="text/csv",key=f"kpi_global_export_{metric}")
    st.warning("SQLite 文件默认位于应用本地磁盘。Streamlit Community Cloud 重启或重新部署可能清除数据；"
               "正式持久化需使用外部数据库或持久化存储。")
