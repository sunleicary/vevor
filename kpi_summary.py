"""Five-column KPI summary calculated from imported workbook payloads.

Metric value is the user-specified attributable failure ratio, not pass rate.
"""
import json
import math
import pandas as pd

METRICS = ("港后提柜及时率", "送仓准时率", "送仓时效", "提空及时率", "还柜及时率")
STATUS = {
    "送仓准时率": ("是否准时", {"不准时"}, {"准时"}),
    "送仓时效": ("是否超时", {"是", "超时"}, {"否", "未超时"}),
    "提空及时率": ("是否超时", {"是", "超时"}, {"否", "未超时"}),
    "还柜及时率": ("是否超时", {"是", "超时"}, {"否", "未超时"}),
}
EXEMPT = "车队无责"

def _clean(value):
    return str(value if value is not None else "").strip()

def _positive_number(value):
    raw = _clean(value).replace(",", "")
    if not raw:
        return None
    try:
        number = float(raw)
        return number > 0 if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None

def summarize(raw):
    summary, warnings = [], []
    for metric in METRICS:
        part = raw.loc[raw["metric"].eq(metric)] if not raw.empty else pd.DataFrame()
        records = []
        for value in part["payload"] if not part.empty else []:
            try:
                records.append(value if isinstance(value, dict) else json.loads(value))
            except (TypeError, ValueError, json.JSONDecodeError):
                warnings.append(f"{metric}：存在无法解析的原始记录")
        total = len(records)
        failed, exempt = 0, 0
        unknown = 0
        for record in records:
            if metric == "港后提柜及时率":
                field = "超LFD天数"
                if field not in record:
                    unknown += 1
                    continue
                is_failed = _positive_number(record[field])
                if is_failed is None:
                    unknown += 1
                    continue
            else:
                field, fail_values, pass_values = STATUS[metric]
                if field not in record:
                    unknown += 1
                    continue
                value = _clean(record[field])
                if value in fail_values:
                    is_failed = True
                elif value in pass_values:
                    is_failed = False
                else:
                    unknown += 1
                    continue
            if is_failed:
                failed += 1
                if _clean(record.get("运营判责")) == EXEMPT:
                    exempt += 1
        if unknown:
            warnings.append(f"{metric}：{unknown:,} 条记录的考核状态无法判定，指标值暂不计算")
        ratio = (failed - exempt) / total if total and not unknown else None
        summary.append({
            "指标": metric,
            "考核期间总记录数": total,
            "考核不达标记录数": failed,
            "供应商无责记录数": exempt,
            "指标值": f"{ratio:.2%}" if ratio is not None else "待核实",
        })
    return pd.DataFrame(summary), warnings
