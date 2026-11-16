# 司顺国际物流港后运营工作台 V2.1

Streamlit + SQLite 港后运营工作台，提供全美六区总览、货柜查询、LFD 风险预警、港后拖车商分析和数据更新。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python import_data.py /path/to/原始文件.xls
streamlit run app.py
```

请先使用你自己持有且有权处理的业务报表在本地导入数据。此公开仓库**不包含任何业务数据库或原始 Excel**。

## 数据口径

- 仅保留目的仓国家为美国的记录。
- 供应商仅使用 `港后拖车行` 字段，不使用 `港前拖车行`。
- 区域通过目的仓物流区域关键词推断，未匹配的归入其他区域。
- KPI 为筛选记录数，可能并非去重柜数。
- LFD 为日期级推断，不是实时码头接口；提箱记录缺失应人工核实。
- 数据管理会覆盖本地数据库，更新前请备份。

## V2.1 修复

`grid(x, key=...)` 支持唯一的下载按钮 key，修复重复 Streamlit 元素 ID、参数不匹配及未定义变量错误。
