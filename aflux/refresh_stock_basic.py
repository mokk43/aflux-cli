#!/usr/bin/env python3
"""Refresh stock_basic table in sqlite DB from Tushare Pro stock_basic endpoint.

Reference: https://tushare.pro/document/2?doc_id=25
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Iterable

import pandas as pd
import tushare as ts

TABLE_NAME = "stock_basic"
TABLE_COLUMNS = [
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "fullname",
    "market",
    "exchange",
    "list_date",
    "is_hs",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh sqlite stock_basic table from Tushare Pro"
    )
    parser.add_argument("--db", default="shares_stat.db", help="sqlite DB path")
    parser.add_argument(
        "--list-status",
        default="L,D,P",
        help="comma-separated list statuses to pull (L,D,P). default: L,D,P",
    )
    return parser.parse_args()


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def validate_table_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE_NAME})").fetchall()}
    missing = [c for c in TABLE_COLUMNS if c not in cols]
    if missing:
        raise RuntimeError(f"table {TABLE_NAME} missing columns: {missing}")


def normalize_statuses(raw: str) -> list[str]:
    allowed = {"L", "D", "P"}
    statuses = [x.strip().upper() for x in raw.split(",") if x.strip()]
    if not statuses:
        raise ValueError("--list-status cannot be empty")
    invalid = [x for x in statuses if x not in allowed]
    if invalid:
        raise ValueError(f"invalid status values: {invalid}; allowed: L,D,P")
    # preserve order but dedup
    seen = set()
    out = []
    for s in statuses:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def fetch_stock_basic_rows(pro, statuses: Iterable[str]) -> list[tuple]:
    frames = []
    fields = ",".join(TABLE_COLUMNS)
    for st in statuses:
        df = pro.stock_basic(exchange="", list_status=st, fields=fields)
        if df is not None and not df.empty:
            frames.append(df[TABLE_COLUMNS])

    if not frames:
        return []

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["ts_code"], keep="first")
    return list(combined.itertuples(index=False, name=None))


def refresh_table(conn: sqlite3.Connection, rows: list[tuple]) -> int:
    placeholders = ", ".join(["?"] * len(TABLE_COLUMNS))
    sql = f"INSERT INTO {TABLE_NAME} ({', '.join(TABLE_COLUMNS)}) VALUES ({placeholders})"

    with conn:
        conn.execute(f"DELETE FROM {TABLE_NAME}")
        if rows:
            conn.executemany(sql, rows)

    return len(rows)


def main() -> int:
    args = parse_args()

    token = os.getenv("TUSHARE_TOKEN") or os.getenv("TS_TOKEN")
    if not token:
        print("ERROR: set TUSHARE_TOKEN (or TS_TOKEN)", file=sys.stderr)
        return 1

    try:
        statuses = normalize_statuses(args.list_status)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    try:
        if not table_exists(conn, TABLE_NAME):
            print(
                f"ERROR: table '{TABLE_NAME}' not found in DB: {args.db}. "
                "Please create it using stock_info.sql first.",
                file=sys.stderr,
            )
            return 1

        validate_table_columns(conn)

        pro = ts.pro_api(token)
        rows = fetch_stock_basic_rows(pro, statuses)
        inserted = refresh_table(conn, rows)
    finally:
        conn.close()

    print(f"Refreshed {TABLE_NAME}: inserted_rows={inserted}, statuses={','.join(statuses)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
