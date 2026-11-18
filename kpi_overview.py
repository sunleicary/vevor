"""美国港后拖车供应商KPI：依据《国际物流服务质量协议（2026年11月版）》港后条款。"""
from datetime import date
import pandas as pd
import streamlit as st

RULES = [
    ("提柜及时率", "100%", "免堆期内提柜；清关放行延误可在放行后2天内提柜，周五放行可顺延至周一。", "拖车行责任导致的 demurrage / Storage / detention 由车队承担", "LFD、清关/码头放行记录、码头关闭证明"),
    ("送仓时效达成率", "100%", "美国卡车：提柜至送仓2个工作日；火车：火车站卸柜起2个工作日。", "超出正常时效造成的超期用箱费由车队承担；司顺主动晚约仓除外", "提柜时间、运输方式、火车卸柜时间、POD"),
    ("送仓准时率", "100%", "按司顺运营及海外仓预约送仓日期当天送达。", "车队责任造成的爽约费及二程派送费由车队承担", "预约日期、POD"),
    ("送仓准确率", "100%", "按司顺运营预约的海外仓地址准确送仓。", "错仓相关爽约、二程及超期用箱费用按协议承担", "预约仓地址、实际送仓地址、POD"),
    ("还空柜及时率", "100%", "仓库通知提空当天不计，3个自然日内提空并还至指定堆场或码头；节假日不豁免。", "第四个自然日起的车架费、超期用箱费等由车队承担", "提空通知、还空日期、EIR"),
    ("文件返回及时率", "100%", "每周一在TMS批量回传上周送仓CMR/POD，命名为排柜单号-CMR/POD。", "逾期每条记录50元及其他相关费用", "POD/CMR及TMS上传时间"),
    ("系统数据准确性", "100%", "业务发生后第二个工作日下午2:00前准确维护系统字段。", "逾期或不准确每条记录50元及其他相关费用", "业务发生时间、TMS操作日志"),
]
def show_kpi_overview(df):
    st.title("📋 美国港后拖车供应商 KPI 考核")
    st.caption("依据《国际物流服务质量协议（2026年11月版）》港后服务质量条款。业务主键为排柜单号；供应商只取港后拖车行。")
    st.warning("当前源表缺少部分考核证据。页面仅显示可核算的参考指标和待核实清单，不自动判定合同违约、扣款或最终KPI达标率。")
    data = df.copy()
    data["供应商"] = data["港后拖车行"].fillna("").astype(str).str.strip()
    data = data[data["供应商"].ne("") & ~data["供应商"].isin(["港后拖车测试", "nan", "None"])].copy()
    for field in ["ETA日期", "LFD", "进口实际提箱时间", "实际送仓时间", "实际还柜日期"]:
        data[field + "_kpi_dt"] = pd.to_datetime(data[field], errors="coerce", format="mixed")
    regions = sorted(data["区域"].dropna().unique().tolist())
    c1, c2, c3 = st.columns(3)
    with c1:
        region = st.selectbox("运营区域", ["全部区域"] + regions, key="kpi_region")
    scoped = data if region == "全部区域" else data[data["区域"].eq(region)]
    with c2:
        vendor = st.selectbox("港后拖车供应商",
                              ["全部供应商"] + sorted(scoped["供应商"].unique().tolist()),
                              key="kpi_vendor")
    with c3:
        dates = st.date_input("ETA统计区间", (date.today().replace(month=1, day=1), date.today()),
                              key="kpi_eta_dates")
    if vendor != "全部供应商":
        scoped = scoped[scoped["供应商"].eq(vendor)]
    if len(dates) != 2:
        st.info("请选择完整ETA起止日期。")
        return
    scoped = scoped[scoped["ETA日期_kpi_dt"].between(
        pd.Timestamp(dates[0]), pd.Timestamp(dates[1]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))].copy()
    if scoped.empty:
        st.info("当前筛选范围没有可考核的港后业务记录。")
        return
    pickup = scoped["进口实际提箱时间_kpi_dt"]
    lfd = scoped["LFD_kpi_dt"]
    delivery = scoped["实际送仓时间_kpi_dt"]
    scoped["LFD参考状态"] = "证据不足/待核实"
    known = pickup.notna() & lfd.notna()
    scoped.loc[known & (pickup.dt.normalize() <= lfd.dt.normalize()), "LFD参考状态"] = "日期内提柜（待确认放行等条件）"
    scoped.loc[known & (pickup.dt.normalize() > lfd.dt.normalize()), "LFD参考状态"] = "晚于LFD（需核实免责）"
    scoped.loc[pickup.isna() & lfd.notna() & (lfd.dt.normalize() < pd.Timestamp(date.today())), "LFD参考状态"] = "LFD已过/无提柜记录"
    scoped["送仓时效参考"] = "证据不足/运输方式待确认"
    valid_delivery = pickup.notna() & delivery.notna()
    if valid_delivery.any():
        # Only an indicative truck benchmark; rail uses station-discharge time, not pickup time.
        business_days = pd.Series(pd.NA, index=scoped.index, dtype="Int64")
        for idx in scoped.index[valid_delivery]:
            p = pickup.loc[idx].normalize()
            d = delivery.loc[idx].normalize()
            if d >= p:
                business_days.loc[idx] = len(pd.bdate_range(p + pd.Timedelta(days=1), d))
        scoped["提柜后工作日数"] = business_days
        scoped.loc[valid_delivery & business_days.le(2).fillna(False), "送仓时效参考"] = "2工作日内（待核实运输方式）"
        scoped.loc[valid_delivery & business_days.gt(2).fillna(False), "送仓时效参考"] = "超过2工作日（待核实免责）"
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("范围内业务单", f"{len(scoped):,}")
    k2.metric("晚于LFD提柜（待核实）", f"{int(scoped['LFD参考状态'].eq('晚于LFD（需核实免责）').sum()):,}")
    k3.metric("已过LFD/无提柜记录", f"{int(scoped['LFD参考状态'].eq('LFD已过/无提柜记录').sum()):,}")
    k4.metric("送仓超2工作日（参考）", f"{int(scoped['送仓时效参考'].eq('超过2工作日（待核实免责）').sum()):,}")
    st.markdown("### 📊 区域 × 港后供应商考核参考")
    summary = scoped.groupby(["区域", "供应商"]).agg(
        业务单量=("排柜单号", "size"),
        晚于LFD待核实=("LFD参考状态", lambda s: s.eq("晚于LFD（需核实免责）").sum()),
        LFD已过未记录提柜=("LFD参考状态", lambda s: s.eq("LFD已过/无提柜记录").sum()),
        送仓超2工作日参考=("送仓时效参考", lambda s: s.eq("超过2工作日（待核实免责）").sum())
    ).reset_index().sort_values(["晚于LFD待核实", "LFD已过未记录提柜"], ascending=False)
    st.dataframe(summary, hide_index=True, use_container_width=True)
    st.download_button("导出供应商考核参考汇总", summary.to_csv(index=False).encode("utf-8-sig"),
                       file_name="美国港后供应商KPI参考汇总.csv", mime="text/csv", key="kpi_summary_csv")
    st.markdown("### 📑 协议 KPI 定义与证据要求")
    rules = pd.DataFrame(RULES, columns=["指标", "目标值", "协议考核定义", "违约责任", "所需证明"])
    rules["当前自动考核能力"] = [
        "仅可比较LFD与提柜日期；放行/免责须核实",
        "仅可计算提柜到送仓的工作日参考；运输方式及免责须核实",
        "缺预约送仓日期，待补数据", "缺预约与实际仓地址对照，待补数据",
        "缺仓库提空通知时间，待补数据", "缺POD上传时间，待补数据",
        "缺TMS字段变更日志，待补数据"
    ]
    st.dataframe(rules, hide_index=True, use_container_width=True)
    st.markdown("### 🔍 KPI 异常待核实业务")
    only_risks = st.checkbox("仅显示参考异常", value=True, key="kpi_risks_only")
    detail = scoped.copy()
    if only_risks:
        detail = detail[
            detail["LFD参考状态"].isin(["晚于LFD（需核实免责）", "LFD已过/无提柜记录"])
            | detail["送仓时效参考"].eq("超过2工作日（待核实免责）")]
    columns = ["排柜单号", "箱号", "区域", "供应商", "ETA日期", "LFD",
               "进口实际提箱时间", "实际送仓时间", "LFD参考状态", "送仓时效参考"]
    st.dataframe(detail[columns], hide_index=True, use_container_width=True, height=440)
    st.download_button("导出待核实业务清单", detail[columns].to_csv(index=False).encode("utf-8-sig"),
                       file_name="港后KPI待核实业务.csv", mime="text/csv", key="kpi_details_csv")
    st.caption("协议目标值100%不等于系统自动得分；费用责任须结合码头公告、清关放行、POD、EIR及合同例外确认。")
