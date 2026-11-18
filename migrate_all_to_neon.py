"""One-time, all-or-nothing migration of three SQLite files into 10 Neon tables.

Run in the folder containing port_ops.db, supplier_kpi.db, users.db.
  python migrate_all_to_neon.py --dry-run
  python migrate_all_to_neon.py --apply

Set DATABASE_URL only in your local terminal environment. NEVER commit SQLite
files or credentials. An existing populated Neon target is NOT overwritten.
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = {
    "containers": ("port_ops.db", "containers"),
    "kpi_raw_rows_v2": ("supplier_kpi.db", "kpi_raw_rows_v2"),
    "kpi_batches_v2": ("supplier_kpi.db", "kpi_batches_v2"),
    "users": ("users.db", "users"),
}
from create_neon_schema import KPI_TABLES

ALL_TABLES = [*SOURCE, *KPI_TABLES.values()]


def read_source_checks():
    stats = {}
    for target, (filename, table) in SOURCE.items():
        path = ROOT / filename
        if not path.is_file():
            raise RuntimeError(f"Missing source file: {filename}")
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                raise RuntimeError(f"Missing SQLite table: {filename}:{table}")
            integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {filename}")
            stats[target] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return stats


def print_source_details(stats):
    for key, count in stats.items():
        print(f"SOURCE {key}: {count:,} rows")
    with sqlite3.connect((ROOT / "supplier_kpi.db").resolve().as_uri() + "?mode=ro", uri=True) as conn:
        counter = dict(conn.execute(
            "SELECT metric,COUNT(*) FROM kpi_raw_rows_v2 GROUP BY metric"))
    unknown = set(counter) - set(KPI_TABLES)
    if unknown:
        raise RuntimeError("Unknown KPI metric names: " + ", ".join(sorted(unknown)))
    print("KPI metric breakdown:")
    for metric, name in KPI_TABLES.items():
        print(f"  {metric} -> {name}: {counter.get(metric,0):,} rows")
    if sum(counter.values()) != stats["kpi_raw_rows_v2"]:
        raise RuntimeError("KPI metric summary does not match total row count")
    return counter


def copy_simple(pg, table, filename, sqlite_table, expected):
    from psycopg import sql
    path = ROOT / filename
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as source:
        source.row_factory = None
        cursor = source.execute(f'SELECT * FROM "{sqlite_table}"')
        columns = [col[0] for col in cursor.description]
        target_columns = {
            row[0] for row in pg.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=current_schema() AND table_name=%s",
                (table,),
            )
        }
        absent = set(columns) - target_columns
        if absent:
            raise RuntimeError(f"{table}: Neon missing columns {sorted(absent)}")
        statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        count = 0
        with pg.cursor() as destination:
            while True:
                batch = cursor.fetchmany(500)
                if not batch:
                    break
                destination.executemany(statement, batch)
                count += len(batch)
        if count != expected:
            raise RuntimeError(f"{table}: copied {count}, expected {expected}")
        print(f"COPIED {table}: {count:,}")
        return count


def copy_six_metrics(pg, expected_counts):
    from psycopg import sql
    statements = {
        metric: sql.SQL(
            "INSERT INTO {} "
            "(month,source_row,order_no,supplier,payload,source_file,imported_at) "
            "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s)"
        ).format(sql.Identifier(table))
        for metric, table in KPI_TABLES.items()
    }
    results = Counter()
    path = ROOT / "supplier_kpi.db"
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as src:
        cur = src.execute(
            "SELECT month,metric,source_row,payload,source_file,imported_at "
            "FROM kpi_raw_rows_v2 ORDER BY month,metric,source_row"
        )
        buffers = {metric: [] for metric in KPI_TABLES}
        with pg.cursor() as dst:
            while True:
                rows = cur.fetchmany(500)
                if not rows:
                    break
                for month,metric,source_row,payload,source_file,imported_at in rows:
                    if metric not in KPI_TABLES:
                        raise RuntimeError(f"Unsupported KPI metric: {metric!r}")
                    record = json.loads(payload)
                    if not isinstance(record, dict):
                        raise RuntimeError(f"Invalid KPI JSON object in {metric}:{source_row}")
                    order = str(record.get("排柜单号") or "").strip() or None
                    # Only 港后拖车行 is used to identify the post-port supplier.
                    supplier = str(record.get("港后拖车行") or "").strip() or None
                    buffers[metric].append(
                        (month,source_row,order,supplier,payload,source_file,imported_at))
                    results[metric] += 1
                for metric, values in buffers.items():
                    if values:
                        dst.executemany(statements[metric], values)
                        values.clear()
    for metric, table in KPI_TABLES.items():
        if results[metric] != expected_counts.get(metric, 0):
            raise RuntimeError(f"{table}: wrong KPI copy count")
        print(f"COPIED {table}: {results[metric]:,}")
    return results


def verify_destination(pg, expected_source, expected_metrics):
    from psycopg import sql
    expected = {**expected_source}
    expected.update({KPI_TABLES[metric]: expected_metrics.get(metric,0)
                     for metric in KPI_TABLES})
    for table, count in expected.items():
        actual = pg.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))
        ).fetchone()[0]
        if actual != count:
            raise RuntimeError(f"VERIFICATION FAILED {table}: {actual} != {count}")
        print(f"VERIFIED {table}: {actual:,}")
    total_detail = sum(expected_metrics.values())
    if total_detail != expected_source["kpi_raw_rows_v2"]:
        raise RuntimeError("KPI totals do not reconcile")


def migrate(apply):
    stats = read_source_checks()
    counts = print_source_details(stats)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL locally before checking Neon.")
    import psycopg
    from psycopg import sql
    with psycopg.connect(url, connect_timeout=20) as pg:
        # Ensure all destination tables already exist: no silent schema guessing.
        with pg.transaction():
            pg.execute("SELECT pg_advisory_xact_lock(2026111801)")
            for table in ALL_TABLES:
                exists = pg.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]
                if exists is None:
                    raise RuntimeError(f"Missing Neon target table: {table}. Run create_neon_schema.py")
                count = pg.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()[0]
                print(f"NEON {table}: {count:,} existing rows")
                if count != 0:
                    raise RuntimeError(
                        f"Target {table} contains {count} rows; refusing any migration. "
                        "Do not truncate or overwrite without reviewing existing data."
                    )
            if not apply:
                print("DRY RUN PASSED: all SQLite sources readable, all 10 Neon tables empty.")
                return
            # Every INSERT and verification is in one PostgreSQL transaction.
            for table,(filename,sqlite_table) in SOURCE.items():
                copy_simple(pg,table,filename,sqlite_table,stats[table])
            copy_six_metrics(pg, counts)
            verify_destination(pg,stats,counts)
    print("SUCCESS: 10 tables committed atomically; SQLite originals unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--dry-run",action="store_true")
    selection.add_argument("--apply",action="store_true")
    args = parser.parse_args()
    try:
        migrate(args.apply)
    except Exception as exc:
        # Don't print full backend exceptions; may contain the secret DSN.
        print(f"FAILED ({type(exc).__name__}): migration did not complete. "
              "Check source structure and target counts.",file=sys.stderr)
        print("Database changes, if any, have been rolled back.",file=sys.stderr)
        sys.exit(1)
