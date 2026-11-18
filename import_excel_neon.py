"""Append Excel HTML .xls rows to Neon without overwriting historical SQLite rows.

Prerequisite: run migrate_to_neon.py --apply on a machine holding the original
three SQLite databases, or otherwise migrate their records first.
Usage:
    python import_excel_neon.py "/path/to/全量数据表1118(1).xls"
    python import_excel_neon.py "/path/to/全量数据表1118(1).xls" --apply
DATABASE_URL must be set locally. Credentials are never embedded in this file.
"""
import argparse
import os
import sys
from lxml import etree
import psycopg
from psycopg import sql
from import_data import FIELDS

def run(path, apply=False):
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL locally before running.")
    with psycopg.connect(url, connect_timeout=20) as conn:
        # Prevent concurrent imports from allocating the same integer IDs.
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(20261118)")
            existing = {r[0] for r in conn.execute(
                'SELECT "排柜单号" FROM containers WHERE "排柜单号" IS NOT NULL')}
            initial = len(existing)
            next_id = conn.execute("SELECT COALESCE(MAX(id),0) FROM containers").fetchone()[0]
            columns = ["id", *FIELDS]
            insert = sql.SQL("INSERT INTO containers ({}) VALUES ({})").format(
                sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.SQL(",").join([sql.Placeholder()] * len(columns)))
            header = None
            pending = []
            seen = set()
            added = duplicates = missing = 0
            def flush():
                if apply and pending:
                    with conn.cursor() as cursor:
                        cursor.executemany(insert, pending)
                pending.clear()
            for _, el in etree.iterparse(path, events=("end",), tag="tr", html=True):
                cells = el.xpath("./th|./td")
                values = ["".join(cell.itertext()).strip() for cell in cells]
                if header is None:
                    header = values
                    if "排柜单号" not in header:
                        raise ValueError("Missing 排柜单号 header")
                elif len(values) == len(header):
                    row = dict(zip(header, values))
                    order = row.get("排柜单号", "").strip()
                    if not order:
                        missing += 1
                    elif order in existing or order in seen:
                        duplicates += 1
                    else:
                        seen.add(order)
                        next_id += 1
                        pending.append((next_id, *(row.get(col, "") for col in FIELDS)))
                        added += 1
                        if len(pending) >= 500:
                            flush()
                el.clear()
                while el.getprevious() is not None:
                    del el.getparent()[0]
            flush()
            print(f"Existing orders preserved: {initial:,}")
            print(f"New Excel orders: {added:,}; duplicate orders skipped: {duplicates:,}; missing order IDs: {missing:,}")
            if not apply:
                print("DRY RUN: rolling back; no data was written.")
                conn.rollback()
            else:
                actual = conn.execute("SELECT COUNT(*) FROM containers").fetchone()[0]
                print(f"Destination containers rows after import: {actual:,}")
    print("Finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("excel_path")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        run(args.excel_path, args.apply)
    except Exception as exc:
        print(f"Import failed ({type(exc).__name__}): {str(exc)[:250]}", file=sys.stderr)
        sys.exit(1)
