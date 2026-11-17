import os
import sqlite3
import tempfile
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from import_data import DB, load
from container_detail import show_container_detail
from supplier_overview import show_supplier_overview

st.set_page_config(page_title="司顺国际物流港后运营工作台", page_icon="🚢", layout="wide")
st.markdown("""<style>
.stApp{background:linear-gradient(120deg,#f6f9ff,#eaf2ff);color:#071b51}
[data-testid="stSidebar"]{background:#092550}
[data-testid="stSidebar"] *{color:white!important}
[data-testid="stMetric"]{background:white;border:1px solid #d5e4ff;border-radius:12px;padding:12px}
[data-testid="stMetricValue"]{color:#1154dc}
.brand{background:white;padding:18px;border-bottom:4px solid #ff510c;border-radius:10px;font-size:25px;font-weight:800;color:#071b60}
</style>""", unsafe_allow_html=True)
st.markdown('<div class="brand">🚢 司顺国际物流港后运营工作台 · V2.1</div>', unsafe_allow_html=True)
st.caption("美国六区 · 港后拖车行口径 · 非实时码头数据")

@st.cache_data(show_spinner=False)
def read_db(mtime):
    with sqlite3.connect(DB) as conn:
        return pd.read_sql_query("SELECT * FROM containers", conn)

def region(value):
    s = str(value).lower()
    mappings = {
        "新泽西 NJ": ["新泽西", "new jersey", "-nj", "nj-"],
        "洛杉矶 LA/LB": ["洛杉矶", "美西ca", "los angeles", "long beach"],
        "休斯顿 HOU": ["休斯顿", "houston", "德州", "texas"],
        "芝加哥 CHI": ["芝加哥", "chicago", "伊利诺伊"],
        "亚特兰大 ATL": ["亚特兰大", "atlanta", "佐治亚"],
        "萨凡纳 SAV": ["萨凡纳", "savannah"],
    }
    return next((name for name, keys in mappings.items() if any(k in s for k in keys)), "其他区域")

def grid(data, key="default"):
    columns = ["柜号显示", "区域", "目的仓", "船公司", "实际船名", "实际航次",
               "ETA日期", "ATA日期", "港后拖车行", "LFD", "进口实际提箱时间",
               "实际送仓时间", "实际还柜日期", "风险"]
    visible = data[columns].rename(columns={"柜号显示": "箱号/排柜单号"})
    st.dataframe(visible, hide_index=True, use_container_width=True, height=450)
    st.download_button("导出当前结果 CSV",
                       visible.to_csv(index=False).encode("utf-8-sig"),
                       file_name="港后货柜查询.csv", mime="text/csv",
                       key=f"download_csv_{key}")

with st.sidebar:
    page = st.radio("业务模块", ["运营总览", "全美港后供应商总览", "货柜查询", "货柜详情", "LFD预警", "拖车商分析", "数据管理"])
    st.caption("供应商仅使用“港后拖车行”字段，不混用港前拖车商。")

# Allow first-time cloud imports before attempting to read the database.
if page == "数据管理":
    st.subheader("业务数据管理")
    st.caption("上传文件仅保存在当前 Streamlit 实例中；免费云端本地数据库不保证持久保存。")
    if not os.path.exists(DB):
        st.info("尚未导入业务数据。请先上传源文件。")
    else:
        with sqlite3.connect(DB) as conn:
            st.metric("当前数据库记录数", conn.execute("SELECT COUNT(*) FROM containers").fetchone()[0])
    admin_password = st.secrets.get("ADMIN_PASSWORD", "")
    if not admin_password:
        st.error("为防止公开网页被任意人员上传或覆盖业务数据，请先在 Streamlit App settings → Secrets 配置 ADMIN_PASSWORD。")
        st.code('ADMIN_PASSWORD = "请设置一个强密码"', language="toml")
        st.stop()
    import hmac
    if not st.session_state.get("data_admin_authenticated", False):
        with st.form("data_admin_login", clear_on_submit=True):
            supplied_password = st.text_input("数据管理员密码", type="password")
            submitted = st.form_submit_button("登录数据管理", type="primary")
        if submitted:
            if hmac.compare_digest(supplied_password.encode("utf-8"), str(admin_password).encode("utf-8")):
                st.session_state.data_admin_authenticated = True
                st.rerun()
            else:
                st.error("管理员密码不正确，请检查 Streamlit Cloud → App settings → Secrets 中的 ADMIN_PASSWORD。")
        else:
            st.info("输入管理员密码后，点击「登录数据管理」。")
        st.stop()
    st.success("管理员验证成功，可以上传业务数据。")
    if st.button("退出数据管理"):
        st.session_state.data_admin_authenticated = False
        st.rerun()
    uploaded = st.file_uploader("上传 HTML 表格导出格式的 .xls / .html 文件", type=["xls", "html", "htm"])
    if uploaded is not None and st.button("确认导入并替换当前数据库", type="primary"):
        with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
            tmp.write(uploaded.getbuffer())
            path = tmp.name
        try:
            with st.spinner("正在导入并校验数据..."):
                load(path)
                read_db.clear()
            st.success("导入成功，报表已可使用。请在左侧切换到运营总览。")
            st.rerun()
        except Exception as exc:
            st.error(f"导入失败，原有数据库未被替换：{exc}")
        finally:
            os.unlink(path)
    st.stop()

if not os.path.exists(DB):
    st.warning("云端尚无业务数据库。请从左侧选择「数据管理」上传原始文件。")
    st.stop()

df = read_db(os.path.getmtime(DB))
df["区域"] = df["目的仓物流区域"].fillna("").map(region)
for col in ["ETA日期", "ATA日期", "LFD", "进口实际提箱时间", "实际送仓时间", "实际还柜日期"]:
    df[col + "_dt"] = pd.to_datetime(df[col], errors="coerce", format="mixed")
with st.sidebar:
    regions = sorted(df["区域"].unique())
    selected = st.multiselect("运营区域", regions, default=regions)
    carriers = sorted(df["港后拖车行"].dropna().astype(str).loc[lambda s: s.str.strip().ne("")].unique())
    carrier = st.selectbox("港后拖车商", ["全部"] + carriers)
    eta_range = st.date_input("ETA范围", value=(date.today()-timedelta(days=30), date.today()+timedelta(days=60)))

q = df[df["区域"].isin(selected)].copy()
if carrier != "全部":
    q = q[q["港后拖车行"] == carrier]
if len(eta_range) == 2:
    q = q[q["ETA日期_dt"].between(pd.Timestamp(eta_range[0]),
        pd.Timestamp(eta_range[1]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))]

today = pd.Timestamp(date.today())
lfd, pickup = q["LFD_dt"], q["进口实际提箱时间_dt"]
q["风险"] = "正常/待核实"
q.loc[lfd.isna(), "风险"] = "缺少LFD"
q.loc[lfd.notna() & pickup.isna() & (lfd < today), "风险"] = "LFD已过/提箱待核实"
q.loc[lfd.notna() & pickup.isna() & (lfd >= today) & (lfd < today + pd.Timedelta(days=3)), "风险"] = "LFD 3天内"
q.loc[lfd.notna() & pickup.notna() & (pickup.dt.normalize() > lfd.dt.normalize()), "风险"] = "提箱晚于LFD"
q.loc[lfd.notna() & pickup.notna() & (pickup.dt.normalize() <= lfd.dt.normalize()), "风险"] = "已按LFD提箱"
q["柜号显示"] = q["箱号"].replace("", pd.NA).fillna(q["排柜单号"])

if page == "全美港后供应商总览":
    show_supplier_overview(df, grid)
elif page == "运营总览":
    names = [None, "新泽西 NJ", "萨凡纳 SAV", "洛杉矶 LA/LB", "休斯顿 HOU", "芝加哥 CHI", "亚特兰大 ATL"]
    tabs = st.tabs(["🇺🇸 全美总览", "🗽 新泽西 NJ", "🚢 萨凡纳 SAV", "⚓ 洛杉矶 LA/LB",
                    "🚛 休斯顿 HOU", "🚆 芝加哥 CHI", "🏭 亚特兰大 ATL"])
    for i, (tab, name) in enumerate(zip(tabs, names)):
        with tab:
            z = q if name is None else q[q["区域"] == name]
            st.subheader(name or "美国港后运营总览")
            arrived = z["ATA日期_dt"].notna()
            picked = z["进口实际提箱时间_dt"].notna()
            delivered = z["实际送仓时间_dt"].notna()
            returned = z["实际还柜日期_dt"].notna()
            metric_masks = [
                ("货柜记录", pd.Series(True, index=z.index)),
                ("已到港", arrived),
                ("LFD已过待核实", z["风险"].eq("LFD已过/提箱待核实")),
                ("已提柜", picked),
                ("已送仓", delivered),
                ("已还空", returned),
                ("LFD三天内", z["风险"].eq("LFD 3天内")),
                ("到港未记录提柜", arrived & ~picked),
            ]
            selected_metric_key = f"overview_selected_metric_{i}"
            # Style only the clickable KPI numbers; preserve the original compact 8-column layout.
            st.markdown("""
            <style>
            div[class*="st-key-overview_metric_"] button {
                border: 0 !important;
                background: transparent !important;
                box-shadow: none !important;
                padding: 0 !important;
                min-height: 2rem !important;
                justify-content: flex-start !important;
            }
            div[class*="st-key-overview_metric_"] button p {
                font-size: 1.65rem !important;
                font-weight: 650 !important;
                line-height: 1.2 !important;
            }
            div[class*="st-key-overview_metric_"] button:hover p {
                text-decoration: underline;
            }
            </style>
            """, unsafe_allow_html=True)
            for metric_idx, (col, (label, mask)) in enumerate(zip(st.columns(8), metric_masks)):
                count = int(mask.sum())
                with col:
                    st.caption(label)
                    if st.button(f"{count:,}", key=f"overview_metric_{i}_{metric_idx}",
                                 help=f"点击查看「{label}」的 {count:,} 条货柜记录",
                                 disabled=count == 0):
                        st.session_state[selected_metric_key] = (
                            None if st.session_state.get(selected_metric_key) == metric_idx else metric_idx
                        )
            selected_metric = st.session_state.get(selected_metric_key)
            if selected_metric is not None and 0 <= selected_metric < len(metric_masks):
                detail_label, detail_mask = metric_masks[selected_metric]
                detail_rows = z.loc[detail_mask].copy()
                with st.container(border=True):
                    header_col, close_col = st.columns([5, 1])
                    header_col.markdown(f"#### 📋 {detail_label} · {len(detail_rows):,} 柜")
                    if close_col.button("收起明细", key=f"overview_metric_close_{i}"):
                        st.session_state[selected_metric_key] = None
                        st.rerun()
                    st.caption("明细受当前区域、拖车商及 ETA 范围筛选影响；缺少提柜记录不代表确认未提柜。")
                    grid(detail_rows, key=f"metric_detail_{i}_{selected_metric}")

            st.markdown("### 📊 区域业务与拖车商分配")
            chart_left, chart_right = st.columns([1, 1], gap="large")
            with chart_left:
                with st.container(border=True):
                    st.markdown("#### 各区域总业务柜量")
                    st.caption("单位：柜 · 当前筛选范围")
                    volume = z["区域"].value_counts().sort_values(ascending=True)
                    if volume.empty:
                        st.info("当前范围内暂无货柜记录")
                    else:
                        st.bar_chart(volume, horizontal=True, height=350,
                                     x_label="柜量", y_label="运营区域")
            with chart_right:
                with st.container(border=True):
                    st.markdown("#### 各区域港后拖车商占比")
                    st.caption("100% 堆叠 · 按港后拖车行统计（含未分配）")
                    share_data = z[["区域", "港后拖车行"]].copy()
                    share_data["港后拖车行"] = share_data["港后拖车行"].fillna("").astype(str).str.strip()
                    share_data.loc[share_data["港后拖车行"].eq(""), "港后拖车行"] = "未分配/未记录"
                    counts = pd.crosstab(share_data["区域"], share_data["港后拖车行"])
                    if counts.empty:
                        st.info("当前范围内暂无货柜记录")
                    else:
                        shares = counts.div(counts.sum(axis=1), axis=0).mul(100).round(2)
                        st.bar_chart(shares, stack=True, height=350,
                                     x_label="运营区域", y_label="占比 (%)")
                        if carrier != "全部":
                            st.caption("当前已筛选单个拖车商；选择左侧「全部」查看完整供应商占比。")
            if not z.empty:
                with st.expander("📋 查看区域柜量及港后拖车商占比明细"):
                    total = z["区域"].value_counts().rename_axis("区域").reset_index(name="总柜量")
                    st.dataframe(total, hide_index=True, use_container_width=True)
                    if not counts.empty:
                        detail = (counts.stack().rename("柜量").to_frame()
                                  .join(shares.stack().rename("占比 (%)"))
                                  .reset_index().rename(columns={"港后拖车行": "港后拖车商"}))
                        st.dataframe(detail.sort_values(["区域", "柜量"], ascending=[True, False]),
                                     hide_index=True, use_container_width=True)

            st.markdown("### 🚢 近期船舶与到港计划")
            with st.container(border=True):
                ships = z.copy()
                ships["船舶/航次"] = ships["实际船名"].fillna("未知") + " / " + ships["实际航次"].fillna("未知")
                ships["预计到港 ETA"] = ships["ETA日期_dt"].dt.strftime("%Y-%m-%d").fillna("未记录")
                ships["实际到港 ATA"] = ships["ATA日期_dt"].dt.strftime("%Y-%m-%d").fillna("未记录")
                summary = (ships.groupby(["船公司", "船舶/航次", "预计到港 ETA", "实际到港 ATA"], dropna=False)
                           .size().reset_index(name="柜量"))
                st.dataframe(summary.sort_values(["柜量", "实际到港 ATA"], ascending=[False, False]).head(20),
                             hide_index=True, use_container_width=True)
            st.subheader("重点货柜明细")
            choices = st.multiselect("风险筛选", ["LFD已过/提箱待核实", "LFD 3天内", "提箱晚于LFD", "缺少LFD"],
                                    default=["LFD已过/提箱待核实", "LFD 3天内", "提箱晚于LFD"],
                                    key=f"overview_filter_{i}")
            focused = z[z["风险"].isin(choices)].sort_values("LFD_dt", na_position="last")
            st.caption(f"匹配 {len(focused):,} 条；缺少提柜记录不等于确认未提柜。")
            grid(focused.head(1000), key=f"overview_{i}")
elif page == "货柜详情":
    show_container_detail(q)
elif page == "货柜查询":
    term = st.text_input("搜索柜号 / 提单号 / 船名 / 排柜单号")
    if term:
        q = q[q[["箱号", "MB/L No.", "实际船名", "排柜单号"]].fillna("").astype(str)
              .apply(lambda s: s.str.contains(term, case=False, regex=False)).any(axis=1)]
    st.caption(f"符合条件 {len(q):,} 条")
    grid(q, key="container_search")
elif page == "LFD预警":
    st.info("根据原始 LFD 与提柜时间推断；缺少提柜记录需人工核实，非实时码头状态。")
    choices = st.multiselect("风险类型", sorted(q["风险"].unique()),
                             default=[x for x in ["LFD 3天内", "LFD已过/提箱待核实", "提箱晚于LFD"] if x in q["风险"].values])
    grid(q[q["风险"].isin(choices)].sort_values("LFD_dt", na_position="last"), key="lfd_alerts")
elif page == "拖车商分析":
    st.subheader("港后拖车商业务量")
    s = q[q["港后拖车行"].fillna("").astype(str).str.strip().ne("")]
    st.bar_chart(s["港后拖车行"].value_counts().head(25))
    st.dataframe(pd.crosstab(s["港后拖车行"], s["区域"]), use_container_width=True)
else:
    st.warning("上传将替换本地数据库，请先备份 port_ops.db。")
    uploaded = st.file_uploader("上传 HTML 导出格式 .xls", type=["xls", "html", "htm"])
    if uploaded and st.button("确认导入并重建数据库", type="primary"):
        with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
            tmp.write(uploaded.getbuffer())
            path = tmp.name
        try:
            with st.spinner("正在导入..."):
                load(path)
                read_db.clear()
            st.success("导入完成，请刷新页面")
        finally:
            os.unlink(path)
    st.write("数据库记录数", len(df))
