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


def _download(frame, filename, key):
    st.download_button("导出 CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name=filename, mime="text/csv", key=key)


def _prepare(df):
    z = df.copy()
    z["国家"] = z["目的仓国家"].map(normalize_country)
    z["区域"] = z["目的仓物流区域"].fillna("").astype(str).str.strip()
    z.loc[z["区域"].isin(["", "nan", "None"]), "区域"] = "未记录区域"
    z["港后供应商"] = z["港后拖车行"].fillna("").astype(str).str.strip()
    z.loc[z["港后供应商"].isin(["", "nan", "None", "港后拖车测试"]), "港后供应商"] = "待分配/未记录"
    for field in ("ETA日期", "ATA日期", "LFD", "进口实际提箱时间", "实际送仓时间", "实际还柜日期"):
        z[field + "_dt"] = pd.to_datetime(z[field], errors="coerce", format="mixed")
    z["已到港"] = z["ATA日期_dt"].notna()
    z["已提柜"] = z["进口实际提箱时间_dt"].notna()
    z["已送仓"] = z["实际送仓时间_dt"].notna()
    z["已还空"] = z["实际还柜日期_dt"].notna()
    z["待提柜（已到港）"] = z["已到港"] & ~z["已提柜"]
    z["待送仓（已提柜）"] = z["已提柜"] & ~z["已送仓"]
    z["待还空（已送仓）"] = z["已送仓"] & ~z["已还空"]
    z["待分配"] = z["港后供应商"].eq("待分配/未记录")
    today = pd.Timestamp(date.today())
    lfd = z["LFD_dt"]
    z["LFD超期待核实"] = lfd.notna() & ~z["已提柜"] & (lfd < today)
    z["LFD三天内"] = lfd.notna() & ~z["已提柜"] & (lfd >= today) & (lfd < today + pd.Timedelta(days=3))
    z["缺少ETA"] = z["ETA日期_dt"].isna()
    return z


def _summary(z, by):
    keys = [by] if isinstance(by, str) else list(by)
    measures = ["已到港", "已提柜", "已送仓", "已还空", "待提柜（已到港）",
                "待送仓（已提柜）", "待还空（已送仓）", "待分配",
                "LFD超期待核实", "LFD三天内", "缺少ETA"]
    out = z.groupby(keys, dropna=False).agg(**{"总柜量": ("国家", "size"),
                        **{name: (name, "sum") for name in measures}}).reset_index()
    out["送仓率%"] = (100 * out["已送仓"] / out["总柜量"]).round(1)
    out["还空率%"] = (100 * out["已还空"] / out["总柜量"]).round(1)
    return out.sort_values("总柜量", ascending=False)


def _details(z, key):
    columns = ["国家", "区域", "箱号", "排柜单号", "目的仓", "港后供应商",
               "ETA日期", "ATA日期", "LFD", "进口实际提箱时间",
               "实际送仓时间", "实际还柜日期"]
    visible = z[[x for x in columns if x in z.columns]].copy()
    st.caption(f"匹配 {len(visible):,} 条货柜记录")
    st.dataframe(visible, use_container_width=True, hide_index=True, height=390)
    _download(visible, f"全球港后货柜明细_{key}.csv", f"global_details_{key}")


def show_global_overview(df):
    st.markdown("""<div style="background:linear-gradient(110deg,#092452,#0b4d94 75%,#ef5b20);
        padding:20px 26px;border-radius:12px;color:white;margin-bottom:12px">
        <h2 style="margin:0;color:white">🌍 全球港后运营总览</h2>
        <div style="color:#dbeaff;margin-top:5px">国家 → 目的仓物流区域 → 货柜处理进度 · Global Post-Port Operations</div>
        </div>""", unsafe_allow_html=True)
    needed = {"目的仓国家", "目的仓物流区域", "港后拖车行"}
    if not needed.issubset(df.columns):
        st.error("数据库缺少必要字段：" + "、".join(sorted(needed - set(df.columns))))
        return
    z = _prepare(df)
    valid = z["ETA日期_dt"].dropna()
    years = sorted(valid.dt.year.unique().astype(int).tolist(), reverse=True)
    c1, c2, c3 = st.columns([1.2, 1.6, 2])
    with c1:
        mode = st.radio("统计范围", ["全部历史记录", "按ETA日期"], key="global_mode")
    with c2:
        if mode == "按ETA日期" and years:
            yr = st.selectbox("ETA年份", years, index=years.index(2026) if 2026 in years else 0, key="global_year")
            dates = st.date_input("ETA日期范围", (date(yr, 1, 1), date(yr, 12, 31)), key=f"global_dates_{yr}")
        else:
            dates = None
            st.caption("全部历史记录包含缺少 ETA 的货柜")
    with c3:
        country_options = sorted(z["国家"].unique().tolist())
        selected_countries = st.multiselect("国家筛选", country_options, default=country_options,
                                            key="global_countries")
    z = z[z["国家"].isin(selected_countries)].copy()
    if mode == "按ETA日期":
        if not years:
            st.warning("当前没有有效 ETA 日期，请切换到全部历史记录。")
            return
        if len(dates) != 2:
            st.info("请选择完整 ETA 起止日期。")
            return
        z = z[z["ETA日期_dt"].between(pd.Timestamp(dates[0]),
              pd.Timestamp(dates[1]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))]
    if z.empty:
        st.info("当前筛选范围内没有货柜记录。")
        return

    total = len(z)
    kpis = [("总柜量", total), ("覆盖国家", z["国家"].nunique()),
            ("覆盖区域", z[["国家", "区域"]].drop_duplicates().shape[0]),
            ("已到港", int(z["已到港"].sum())),
            ("已提柜", int(z["已提柜"].sum())),
            ("已送仓", int(z["已送仓"].sum())),
            ("已还空", int(z["已还空"].sum())),
            ("LFD超期待核实", int(z["LFD超期待核实"].sum()))]
    for col, (label, count) in zip(st.columns(8), kpis):
        col.metric(label, f"{count:,}")
    st.caption("统计单位为原始货柜记录（非去重箱号）。运营节点按对应日期字段是否有记录计算；"
               "“待处理”表示系统尚无下一节点记录，不代表现场实际未完成。")

    st.markdown("#### ① 国家级货柜处理进度")
    by_country = _summary(z, "国家")
    st.dataframe(by_country, hide_index=True, use_container_width=True,
                 column_config={"送仓率%": st.column_config.ProgressColumn("送仓率%", min_value=0, max_value=100, format="%.1f%%"),
                                "还空率%": st.column_config.ProgressColumn("还空率%", min_value=0, max_value=100, format="%.1f%%")})
    _download(by_country, "全球国家港后处理进度.csv", "global_country_status_export")

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("##### 各国家货柜量")
        st.bar_chart(by_country.set_index("国家")["总柜量"].sort_values(),
                     horizontal=True, height=max(300, min(600, 34 * len(by_country))))
    with right:
        st.markdown("##### 各国家送仓与还空进度")
        st.bar_chart(by_country.set_index("国家")[["已送仓", "已还空"]],
                     horizontal=True, height=max(300, min(600, 34 * len(by_country))))

    st.markdown("#### ② 国家 → 区域处理情况")
    country = st.selectbox("选择国家，查看该国全部运营区域", ["全部国家"] + by_country["国家"].tolist(),
                           key="global_focus_country")
    scope = z if country == "全部国家" else z[z["国家"].eq(country)]
    by_region = _summary(scope, ["国家", "区域"])
    st.dataframe(by_region, hide_index=True, use_container_width=True,
                 column_config={"送仓率%": st.column_config.ProgressColumn("送仓率%", min_value=0, max_value=100, format="%.1f%%"),
                                "还空率%": st.column_config.ProgressColumn("还空率%", min_value=0, max_value=100, format="%.1f%%")})
    _download(by_region, "全球国家区域港后处理进度.csv", "global_region_status_export")
    st.markdown("##### 区域待处理货柜对比")
    chart = by_region.copy()
    chart["国家/区域"] = chart["国家"] + " / " + chart["区域"]
    st.bar_chart(chart.set_index("国家/区域")[["待提柜（已到港）", "待送仓（已提柜）", "待还空（已送仓）"]],
                 horizontal=True, height=max(320, min(850, 30 * len(chart))))

    st.markdown("#### ③ 区域货柜处理明细")
    d1, d2, d3 = st.columns(3)
    with d1:
        region_options = sorted(scope["区域"].unique().tolist())
        focus_region = st.selectbox("区域", ["全部区域"] + region_options, key="global_focus_region")
    detail = scope if focus_region == "全部区域" else scope[scope["区域"].eq(focus_region)]
    with d2:
        statuses = ["全部", "已到港", "已提柜", "已送仓", "已还空", "待提柜（已到港）",
                    "待送仓（已提柜）", "待还空（已送仓）", "待分配", "LFD超期待核实", "LFD三天内", "缺少ETA"]
        status = st.selectbox("处理状态", statuses, key="global_focus_status")
    with d3:
        vendors = sorted(detail["港后供应商"].unique().tolist())
        vendor = st.selectbox("港后拖车商", ["全部供应商"] + vendors, key="global_focus_vendor")
    if status != "全部":
        detail = detail[detail[status]]
    if vendor != "全部供应商":
        detail = detail[detail["港后供应商"].eq(vendor)]
    _details(detail, "region")

    with st.expander("④ 国家 / 区域 / 港后拖车商业务分配", expanded=False):
        supplier = scope.groupby(["国家", "区域", "港后供应商"]).size().rename("柜量").reset_index()
        supplier = supplier.sort_values("柜量", ascending=False)
        st.dataframe(supplier, hide_index=True, use_container_width=True)
        _download(supplier, "全球区域港后供应商分配.csv", "global_supplier_export")

    st.caption("港后供应商严格使用「港后拖车行」，空白及「港后拖车测试」按待分配统计。"
               "LFD风险为数据预警，跨国家规则不同，需人工核实。"
               "如数据库此前仅导入美国数据，请管理员备份并重新上传全球完整文件。")
