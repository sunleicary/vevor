"""Additive Neon PostgreSQL index optimization; never changes business rows.

Run on the user's machine after setting DATABASE_URL:
    python optimize_neon_indexes.py

CREATE INDEX CONCURRENTLY avoids long write-blocking index builds.
This script is repeatable and does not modify table contents.
"""
import os
import sys
import time

INDEXES = [
    # Containers: ETA time window combined with post-port supplier or destination region.
    ("idx_containers_eta", 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_containers_eta ON containers ("ETA日期")'),
    ("idx_containers_supplier_eta", 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_containers_supplier_eta ON containers ("港后拖车行", "ETA日期")'),
    ("idx_containers_region_eta", 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_containers_region_eta ON containers ("目的仓物流区域", "ETA日期")'),
    ("idx_containers_lfd", 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_containers_lfd ON containers ("LFD")'),
    ("idx_containers_container_no", 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_containers_container_no ON containers ("箱号")'),
    # The raw KPI table already has an index on (month, metric) and a PK on
    # (month, metric, source_row). Do not duplicate either index.
    # Expression indexes match JSON field filters only if queries use these expressions.
    ("idx_kpi_raw_month_supplier", """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kpi_raw_month_supplier
        ON kpi_raw_rows_v2 (month, (payload::jsonb ->> '港后拖车行'))
        WHERE metric <> '台账'"""),
    ("idx_kpi_raw_month_region", """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kpi_raw_month_region
        ON kpi_raw_rows_v2 (month, (payload::jsonb ->> '目的仓物流区域'))
        WHERE metric <> '台账'"""),
    ("idx_kpi_raw_month_supplier_region", """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kpi_raw_month_supplier_region
        ON kpi_raw_rows_v2 (month, (payload::jsonb ->> '港后拖车行'),
                             (payload::jsonb ->> '目的仓物流区域'))
        WHERE metric <> '台账'"""),
]

def main():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        sys.exit("请先设置 DATABASE_URL 环境变量（不要提交到 GitHub）。")
    import psycopg
    from psycopg import sql

    try:
        # CONCURRENTLY cannot run inside a transaction block.
        with psycopg.connect(url, connect_timeout=15, autocommit=True) as conn:
            for name, statement in INDEXES:
                started = time.perf_counter()
                try:
                    conn.execute(statement)
                    print(f"OK {name} ({time.perf_counter()-started:.2f}s)")
                except Exception as exc:
                    print(f"FAILED {name}: {type(exc).__name__}")
                    # An interrupted concurrent build can leave an INVALID index.
                    # Do not drop indexes automatically; inspect pg_index first.
                    raise
            for table in ("containers", "kpi_raw_rows_v2"):
                conn.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
                print(f"ANALYZE {table}: OK")
            invalid = conn.execute("""
                SELECT c.relname FROM pg_index i
                JOIN pg_class c ON c.oid=i.indexrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND NOT i.indisvalid
                ORDER BY c.relname
            """).fetchall()
            if invalid:
                print("WARNING: invalid indexes:", ", ".join(row[0] for row in invalid))
        print("索引优化完成。业务数据未被修改。")
    except Exception as exc:
        print(f"索引优化中止：{type(exc).__name__}。请检查权限、连接和是否存在 INVALID 索引。")
        sys.exit(1)

if __name__ == "__main__":
    main()
