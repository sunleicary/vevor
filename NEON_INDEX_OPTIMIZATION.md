# Neon PostgreSQL 索引优化

运行方式（在本地 VEVOR 项目目录）：

```bash
python -m pip install "psycopg[binary]>=3.2,<4"
export DATABASE_URL='从 Neon 控制台复制的连接字符串'
python optimize_neon_indexes.py
```

注意：不要把数据库连接字符串上传到 GitHub、聊天或截图中。建议先在 Neon 创建备份分支，再于业务低峰执行。

该脚本使用 `CREATE INDEX CONCURRENTLY IF NOT EXISTS`，不删除表、不删除记录、不更改 KPI 判责逻辑。创建索引需要消耗 CPU、存储与 I/O，可能暂时增加数据库负载；Neon 需要有创建索引权限。执行完成后对 `containers` 和 `kpi_raw_rows_v2` 执行 `ANALYZE`。

已存在的主键及 `(month,metric)`、`(month,supplier)` 等索引不重复创建。

**重要限制：** 现有 Streamlit KPI 页面仍使用 `WHERE month=?` 拉取整月 JSON 后在 Python 中筛选供应商/区域。新 JSON 表达式索引**不会自动加速这种查询**。后续需要把筛选下推为 SQL，例如：

```sql
SELECT metric, source_row, payload
FROM kpi_raw_rows_v2
WHERE month = $1
  AND metric <> '台账'
  AND payload::jsonb ->> '港后拖车行' = $2
  AND payload::jsonb ->> '目的仓物流区域' = $3;
```

同时主工作台 `SELECT * FROM containers` 全表读取不会因索引而显著变快。建议后续做分页、按需加载和缓存。

可使用 `EXPLAIN (ANALYZE, BUFFERS)` 验证代表性查询，避免仅凭创建索引推断性能提升。若某个 `CREATE INDEX CONCURRENTLY` 失败，可能遗留 INVALID 索引；脚本会停止而不会自动删除，需人工确认后处理。
