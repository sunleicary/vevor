# Neon PostgreSQL migration runbook

Status: **preparation only**. The production Streamlit app still uses SQLite. Do not remove the SQLite databases until application cutover is tested.

## Security
Rotate any previously shared Neon database password. Set `DATABASE_URL` only in a local environment variable or Streamlit Cloud Secrets. Never commit credentials or .db files. Use a dedicated restricted database role for production when possible.

## Source data prerequisites
The migration must run **where all three existing SQLite files are actually present**:
- `port_ops.db` with `containers`
- `supplier_kpi.db` with `kpi_raw_rows_v2` and `kpi_batches_v2`
- `users.db` with `users`

Streamlit Community Cloud local files may be ephemeral. If these files are not available locally, obtain authorized backups from the running environment or reimport original Excel/HTML files after implementing the Neon write path. Do not assume cloning GitHub downloads SQLite data.

## Execute locally
1. Back up the three SQLite files.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Export `DATABASE_URL` in the current shell (avoid shell history containing credentials).
4. Run `python migrate_to_neon.py --dry-run`.
5. Check all four source tables and row counts.
6. Run `python migrate_to_neon.py --apply` only when the Neon destination tables are empty.

The script refuses to overwrite any nonempty target table. It runs the four-table migration in a single PostgreSQL transaction and verifies counts. It does not switch the Streamlit application.

## Cutover checklist (not yet performed)
- Implement a selectable PostgreSQL backend for business data, KPI, and authentication.
- Verify import, login, KPI pagination, permissions and global reporting against Neon.
- Test Streamlit restart and persistence.
- Only then enable Neon in Cloud Secrets; retain SQLite fallback configuration for rollback.
- Avoid automatically falling back to an empty local user database after Neon failures: that could create inconsistent accounts.
