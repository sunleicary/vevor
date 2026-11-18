# Neon 后端切换（测试分支）

本分支 `neon-backend-v3` **尚未部署到生产 main**，保留原 SQLite 应用作为回滚路径。

## 上线前

1. 在 Neon SQL Editor 检查全部 10 张表记录数，并确认选择正确的 project、branch 和 database。
2. 在 Streamlit Cloud → App → Settings → Secrets 配置：
   ```toml
   DATABASE_URL = "postgresql://USER:PASSWORD@HOST/neondb?sslmode=require&channel_binding=require"
   ```
   不要把真实密码提交到 GitHub。之前暴露的密码应在 Neon 重置后再配置。
3. 先用单独的 Streamlit 测试应用部署本分支，主文件 `app.py`，不要立即覆盖现有正式应用。
4. 测试：原账号登录；全球总览/美国六区/LFD 预警；货柜查询；KPI 月份和台账分页；管理员创建用户及修改密码。
5. 数据写入测试应使用 **Neon 测试分支**，不要在生产数据上尝试“替换当前数据库”或重新导入 KPI，因为它们会按设计覆盖现有记录。
6. 测试通过后再合并至 main，并在正式 Streamlit App Secrets 设置同一 Neon 数据库的最新连接字符串。

## 行为说明

- 配置 `DATABASE_URL` 时使用 Neon PostgreSQL；未配置时保持原 SQLite 模式。
- `containers`、`users`、`kpi_raw_rows_v2`、`kpi_batches_v2` 读写改为当前后端。
- KPI 上传在 Neon 模式下同时更新六张分类明细表，整批事务提交。
- 货柜上传在 Neon 模式下先完整校验，然后在事务内替换 `containers`。
- 旧的 SQLite 备份页面在 Neon 模式下停用；请使用 Neon 的数据库备份/导出机制。
- 现有报表逻辑仍使用 Pandas 在应用端聚合，尚未实现数据库端聚合、增量更新和并发压测。
- 数据表记录数正确不代表所有字段正确，正式切换前应进行字段抽查。
