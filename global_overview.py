"""全球港后业务量分析：目的仓国家口径，供应商只取港后拖车行。"""
from datetime import date
import pandas as pd
import streamlit as st

COUNTRY_NAMES = {
    "美国": "美国", "AMERICA": "美国", "USA": "美国", "US": "美国", "UNITED STATES": "美国", "UNITED STATES OF AMERICA": "美国",
    "加拿大": "加拿大", "CANADA": "加拿大", "CA": "加拿大",
    "英国": "英国", "UNITED KINGDOM": "英国", "UK": "英国", "GREAT BRITAIN": "英国",
    "德国": "德国", "GERMANY": "德国", "DE": "德国",
    "法国": "法国", "FRANCE": "法国",
    "意大利": "意大利", "ITALY": "意大利",
    "西班牙": "西班牙", "SPAIN": "西班牙",
    "澳大利亚": "澳大利亚", "AUSTRALIA": "澳大利亚",
    "日本": "日本", "JAPAN": "日本",
    "墨西哥": "墨西哥", "MEXICO": "墨西哥",
    "荷兰": "荷兰", "NETHERLANDS": "荷兰",
    "波兰": "波兰", "POLAND": "波兰",
    "比利时": "比利时", "BELGIUM": "比利时",
    "新加坡": "新加坡", "SINGAPORE": "新加坡",
    "马来西亚": "马来西亚", "MALAYSIA": "马来西亚",
    "泰国": "泰国", "THAILAND": "泰国",
    "阿联酋": "阿联酋", "UNITED ARAB EMIRATES": "阿联酋", "UAE": "阿联酋",
}
USA_VALUES = {"美国", "AMERICA", "USA", "US", "UNITED STATES", "UNITED STATES OF AMERICA"}


def normalize_country(value):
    name = str(value).strip()
    if not name or name.lower() in ("nan", "none", "null"):
        return "未记录国家"
    return COUNTRY_NAMES.get(name.upper(), name)


def is_us_country(value):
    return str(value).strip().upper() in USA_VALUES


def show_global_overview(df):
    st.markdown("""<div style="background:linear-gradient(110deg,#092452,#0a529d 75%,#f05b1c);
      border-radius:14px;padding:20px 26px;color:white;margin-bottom:14px">
      <h2 style="color:white;margin:0">🌍 全球港后业务量分析</h2>
      <div style="color:#d9eaff;margin-top:6px">Global Post-Port Operations · Destination Warehouse Country</div></div>""",
      unsafe_allow_html=True)
    if "目的仓国家" not in df:
        st.error("数据库缺少「目的仓国家」字段。")
        return
    data = df.copy()
    data["国家"] = data["目的仓国家"].map(normalize_country)
    data["港后供应商"] = data["港后拖车行"].fillna("").astype(str).str.strip()
    data.loc[data["港后供应商"].isin(["", "nan", "None", "港后拖车测试"]), "港后供应商"] = "待分配/未记录"
    if "ETA日期_dt" not in data:
        data["ETA日期_dt"] = pd.to_datetime(data["ETA日期"], errors="coerce", format="mixed")
    valid = data["ETA日期_dt"].dropna()
    if valid.empty:
        st.warning("当前数据库没有有效 ETA 日期，无法按 ETA 统计全球业务量。")
        return
    years = sorted(valid.dt.year.unique().astype(int).tolist(), reverse=True)
    default_year = 2026 if 2026 in years else years[0]
    a, b, c = st.columns([1, 2, 2])
    with a:
        year = st.selectbox("统计年份（ETA）", years, index=years.index(default_year), key="global_year")
    with b:
        dates = st.date_input("ETA 统计区间", (date(year, 1, 1), date(year, 12, 31)),
                              key=f"global_dates_{year}")
    with c:
        countries = sorted(data["国家"].unique().tolist())
        selected = st.multiselect("目的仓国家", countries, default=countries, key="global_countries")
    if len(dates) != 2:
        st.info("请选择完整的 ETA 起止日期。")
        return
    z = data[data["国家"].isin(selected) & data["ETA日期_dt"].between(
        pd.Timestamp(dates[0]), pd.Timestamp(dates[1]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))].copy()
    if z.empty:
        st.info("当前国家和 ETA 范围内没有记录。")
        return
    z["月份"] = z["ETA日期_dt"].dt.strftime("%Y-%m")
    total = len(z)
    pending = int(z["港后供应商"].eq("待分配/未记录").sum())
    country_counts = z["国家"].value_counts()
    metrics = [
        ("全球总柜量", f"{total:,} 柜"),
        ("覆盖国家", f"{z['国家'].nunique()} 个"),
        ("已分配柜量", f"{total-pending:,} 柜"),
        ("待分配/未记录", f"{pending:,} 柜"),
        ("已分配比例", f"{(total-pending)/total:.1%}"),
        ("最大业务国家", country_counts.index[0]),
    ]
    for col, (label, value) in zip(st.columns(6), metrics):
        col.metric(label, value)
    st.caption("口径：目的仓国家 + ETA；按原始数据行计数（非去重箱号）。"
               "「港后拖车测试」及空白供应商视为待分配；供应商字段有值不等于已确认运力。")
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        st.markdown("#### 🌐 各国家港后业务量")
        st.bar_chart(country_counts.sort_values(), horizontal=True, height=max(320, min(720, 32*len(country_counts))),
                     x_label="柜量", y_label="目的仓国家")
    with right:
        st.markdown("#### 📈 全球月度业务趋势")
        st.bar_chart(z.groupby("月份").size().rename("柜量"), height=320, x_label="ETA月份", y_label="柜量")
        st.markdown("#### 🚛 港后供应商分配结构")
        st.bar_chart(z["港后供应商"].value_counts().head(12).sort_values(), horizontal=True,
                     height=300, x_label="柜量", y_label="港后供应商")
    st.markdown("#### 📋 国家业务量与供应商分配")
    summary = z.groupby("国家").size().rename("总柜量").to_frame()
    pending_by_country = z[z["港后供应商"].eq("待分配/未记录")].groupby("国家").size()
    summary["待分配/未记录"] = pending_by_country.reindex(summary.index, fill_value=0)
    summary["已分配"] = summary["总柜量"] - summary["待分配/未记录"]
    summary["全球占比(%)"] = (summary["总柜量"] / total * 100).round(2)
    summary["分配率(%)"] = (summary["已分配"] / summary["总柜量"] * 100).round(2)
    summary = summary.sort_values("总柜量", ascending=False).reset_index()
    st.dataframe(summary, hide_index=True, use_container_width=True)
    st.download_button("导出国家汇总 CSV", summary.to_csv(index=False).encode("utf-8-sig"),
                       "全球港后国家业务量.csv", "text/csv", key="global_country_export")
    with st.expander("🔎 国家 × 港后供应商 · 明细查询", expanded=True):
        x, y = st.columns(2)
        with x:
            country = st.selectbox("查询国家", ["全部"] + sorted(z["国家"].unique().tolist()), key="global_query_country")
        scope = z if country == "全部" else z[z["国家"].eq(country)]
        with y:
            vendor = st.selectbox("港后供应商", ["全部"] + sorted(scope["港后供应商"].unique().tolist()),
                                  key="global_query_vendor")
        detail = scope if vendor == "全部" else scope[scope["港后供应商"].eq(vendor)]
        cross = pd.crosstab(detail["国家"], detail["港后供应商"])
        st.dataframe(cross, use_container_width=True)
        st.caption(f"匹配 {len(detail):,} 条记录")
        fields = ["国家", "箱号", "排柜单号", "目的仓", "目的仓物流区域", "ETA日期",
                  "ATA日期", "卸货港", "实际船名", "实际航次", "港后拖车行", "港后供应商",
                  "LFD", "进口实际提箱时间", "实际送仓时间", "实际还柜日期"]
        visible = detail[[col for col in fields if col in detail.columns]]
        st.dataframe(visible, hide_index=True, use_container_width=True, height=400)
        st.download_button("导出当前货柜明细 CSV", visible.to_csv(index=False).encode("utf-8-sig"),
                           "全球港后货柜明细.csv", "text/csv", key="global_detail_export")
    st.info("全球分析仅覆盖当前已导入数据库的数据。若此前导入时仅保留美国记录，"
            "需要管理员重新上传包含全球国家的完整源文件，才会显示其他国家。")
