"""One-time, opt-in SQLite -> Neon PostgreSQL migration. No application switch.

Usage:
  DATABASE_URL=... python migrate_to_neon.py --dry-run
  DATABASE_URL=... python migrate_to_neon.py --apply

Requires psycopg[binary]. Never print the connection string.
"""
import argparse
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = {
    "containers": ("port_ops.db", "containers"),
    "kpi_raw_rows_v2": ("supplier_kpi.db", "kpi_raw_rows_v2"),
    "kpi_batches_v2": ("supplier_kpi.db", "kpi_batches_v2"),
    "users": ("users.db", "users"),
}

def source_rows(filename, table):
    path = ROOT / filename
    if not path.is_file():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists:
            return None
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        return columns, count
    finally:
        conn.close()

def migrate(url, apply):
    import psycopg
    from psycopg import sql
    specs = {name: source_rows(*source) for name, source in SOURCES.items()}
    for name, info in specs.items():
        print(f"{name}: " + (f"{info[1]:,} SQLite rows" if info else "source unavailable"))
    if not apply:
        print("DRY RUN ONLY: no destination changes.")
        return
    if not url:
        raise SystemExit("DATABASE_URL environment variable is required.")
    if not all(specs.values()):
        raise SystemExit("Missing source SQLite file/table; refusing partial migration.")
    with psycopg.connect(url, connect_timeout=15) as pg:
        # Transaction covers all four tables; a failure rolls back the entire migration.
        with pg.transaction():
            pg.execute("""CREATE TABLE IF NOT EXISTS containers (
                id BIGINT PRIMARY KEY
            )""")
            # Preserve the source column names and TEXT values, including Chinese headers.
            for name, (filename, table) in SOURCES.items():
                columns, count = specs[name]
                if name == "containers":
                    for col in columns:
                        if col != "id":
                            pg.execute(sql.SQL("ALTER TABLE containers ADD COLUMN IF NOT EXISTS {} TEXT").format(sql.Identifier(col)))
                elif name == "kpi_raw_rows_v2":
                    pg.execute("""CREATE TABLE IF NOT EXISTS kpi_raw_rows_v2 (
                        month TEXT NOT NULL, metric TEXT NOT NULL, source_row INTEGER NOT NULL,
                        payload TEXT NOT NULL, source_file TEXT NOT NULL, imported_at TEXT NOT NULL,
                        PRIMARY KEY(month,metric,source_row))""")
                elif name == "kpi_batches_v2":
                    pg.execute("""CREATE TABLE IF NOT EXISTS kpi_batches_v2 (
                        month TEXT PRIMARY KEY, source_file TEXT NOT NULL,
                        imported_at TEXT NOT NULL, row_count INTEGER NOT NULL)""")
                elif name == "users":
                    pg.execute("""CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY, salt TEXT NOT NULL,
                        password_hash TEXT NOT NULL, role TEXT NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL)""")
                    pg.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_idx ON users (lower(username))")
                existing = pg.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(name))).fetchone()[0]
                if existing:
                    raise RuntimeError(f"Destination {name} already has {existing} rows; refusing overwrite.")
                source_path = ROOT / filename
                with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as src:
                    cursor = src.execute(f'SELECT * FROM "{table}"')
                    cols = [d[0] for d in cursor.description]
                    insert = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        sql.Identifier(name),
                        sql.SQL(", ").join(map(sql.Identifier, cols)),
                        sql.SQL(", ").join([sql.Placeholder()] * len(cols)))
                    imported = 0
                    while True:
                        batch = cursor.fetchmany(500)
                        if not batch:
                            break
                        with pg.cursor() as dst:
                            dst.executemany(insert, batch)
                        imported += len(batch)
                    if imported != count:
                        raise RuntimeError(f"{name}: source {count}, imported {imported}")
                actual = pg.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(name))).fetchone()[0]
                if actual != count:
                    raise RuntimeError(f"{name}: destination count mismatch")
                print(f"Verified {name}: {actual:,} rows")
            pg.execute('CREATE INDEX IF NOT EXISTS idx_containers_order ON containers ("排柜单号")')
            pg.execute('CREATE INDEX IF NOT EXISTS idx_containers_region ON containers ("目的仓物流区域")')
            pg.execute("CREATE INDEX IF NOT EXISTS idx_kpi_month_metric ON kpi_raw_rows_v2 (month,metric)")
    print("Migration committed. SQLite originals were not modified.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    migrate(os.getenv("DATABASE_URL"), args.apply)
