#!/usr/bin/env python3
"""Pull Tushare Pro daily quotes into sqlite table daily_stock_quotes.

Usage examples:
  python pull_daily_stock_quotes.py
  python pull_daily_stock_quotes.py --db shares_stat.db --trade_date 20260518
  python pull_daily_stock_quotes.py --start_date 20260501 --end_date 20260510
  python pull_daily_stock_quotes.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import tushare as ts

TABLE_NAME = "daily_stock_quotes"
TABLE_COLUMNS = [
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
]

EXPECTED_SCHEMA_TYPES = {
    "ts_code": "TEXT",
    "trade_date": "TEXT",
    "open": "REAL",
    "high": "REAL",
    "low": "REAL",
    "close": "REAL",
    "pre_close": "REAL",
    "change": "REAL",
    "pct_chg": "REAL",
    "vol": "REAL",
    "amount": "REAL",
}


class RetryableTushareError(RuntimeError):
    """Retryable Tushare API exception wrapper."""


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pull Tushare Pro daily quotes into sqlite table daily_stock_quotes"
    )
    parser.add_argument("--db", default="shares_stat.db", help="sqlite DB path")
    parser.add_argument("--trade_date", help="single trade date, format YYYYMMDD")
    parser.add_argument("--start_date", help="start date, format YYYYMMDD")
    parser.add_argument("--end_date", help="end date, format YYYYMMDD")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview target dates and actions without calling Tushare or writing DB",
    )
    return parser.parse_args()


def validate_date_str(date_str: str, arg_name: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"{arg_name} must be YYYYMMDD, got: {date_str}") from exc


def iter_weekdays(start_dt: datetime, end_dt: datetime) -> list[str]:
    dates: list[str] = []
    cur = start_dt
    while cur <= end_dt:
        if cur.weekday() < 5:
            dates.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return dates


def call_with_retry(func, *args, retries: int = 3, base_delay: float = 1.0, **kwargs):
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt >= retries:
                break
            sleep_s = base_delay * (2 ** (attempt - 1))
            logging.warning(
                "API call failed (attempt %d/%d): %s; retry in %.1fs",
                attempt,
                retries,
                exc,
                sleep_s,
            )
            time.sleep(sleep_s)
    raise RetryableTushareError(f"API call failed after {retries} attempts: {last_err}")


def resolve_open_trading_day(pro, now: datetime) -> str:
    """Resolve today's or previous open trading day using trade calendar.

    Rule:
    - now >= 17:00: target today if open, else latest open day <= today
    - now < 17:00: target latest open day < today
    """
    today = now.strftime("%Y%m%d")
    start = (now - timedelta(days=30)).strftime("%Y%m%d")

    cal_df = call_with_retry(
        pro.trade_cal,
        exchange="",
        start_date=start,
        end_date=today,
        fields="cal_date,is_open",
    )
    if cal_df is None or cal_df.empty:
        raise RuntimeError("trade_cal returned empty result; cannot resolve target date")

    open_dates = sorted(cal_df.loc[cal_df["is_open"] == 1, "cal_date"].tolist())
    if not open_dates:
        raise RuntimeError("no open trading day found in recent trade calendar window")

    if now.hour >= 17:
        # Prefer today when open; otherwise nearest prior open day.
        if today in open_dates:
            return today
        return max(d for d in open_dates if d <= today)

    prior = [d for d in open_dates if d < today]
    if not prior:
        raise RuntimeError("no prior open trading day found before today")
    return prior[-1]


def decide_dates(args: argparse.Namespace, pro) -> list[str]:
    if args.trade_date and (args.start_date or args.end_date):
        raise ValueError("--trade_date cannot be used with --start_date/--end_date")

    if args.trade_date:
        validate_date_str(args.trade_date, "trade_date")
        return [args.trade_date]

    if args.start_date or args.end_date:
        if not (args.start_date and args.end_date):
            raise ValueError("--start_date and --end_date must be provided together")

        start_dt = validate_date_str(args.start_date, "start_date")
        end_dt = validate_date_str(args.end_date, "end_date")
        if start_dt > end_dt:
            raise ValueError("start_date cannot be later than end_date")

        return iter_weekdays(start_dt, end_dt)

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return [resolve_open_trading_day(pro, now)]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def validate_table_schema(conn: sqlite3.Connection, table_name: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    if not rows:
        raise RuntimeError(f"cannot inspect schema for table: {table_name}")

    actual = {row[1]: (row[2] or "").upper() for row in rows}  # name -> type
    missing = [c for c in TABLE_COLUMNS if c not in actual]
    if missing:
        raise RuntimeError(f"table {table_name} missing columns: {missing}")

    type_mismatch: list[str] = []
    for col, exp_t in EXPECTED_SCHEMA_TYPES.items():
        act_t = actual.get(col, "")
        if exp_t and exp_t not in act_t:
            type_mismatch.append(f"{col}: expected {exp_t}, got {act_t or 'EMPTY'}")

    if type_mismatch:
        raise RuntimeError(
            "table schema type mismatch: " + "; ".join(type_mismatch)
        )


def get_row_count_for_date(conn: sqlite3.Connection, trade_date: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(1) FROM {TABLE_NAME} WHERE trade_date = ?",
        (trade_date,),
    ).fetchone()
    return int(row[0] if row else 0)


def insert_rows(conn: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> int:
    sql = f"""
        INSERT OR IGNORE INTO {TABLE_NAME}
        ({", ".join(TABLE_COLUMNS)})
        VALUES ({", ".join(["?"] * len(TABLE_COLUMNS))})
    """
    before = conn.total_changes
    conn.executemany(sql, rows)
    conn.commit()
    return conn.total_changes - before


def fetch_daily_with_retry(pro, trade_date: str):
    return call_with_retry(pro.daily, trade_date=trade_date)


def pull_for_date(pro, conn: sqlite3.Connection, trade_date: str, dry_run: bool) -> dict[str, Any]:
    before_count = get_row_count_for_date(conn, trade_date)

    if dry_run:
        logging.info("[%s] dry-run: existing_rows=%d", trade_date, before_count)
        return {
            "trade_date": trade_date,
            "status": "dry_run",
            "fetched": 0,
            "inserted": 0,
            "before": before_count,
            "after": before_count,
        }

    df = fetch_daily_with_retry(pro, trade_date)
    if df is None or df.empty:
        logging.info("[%s] no data returned, skip", trade_date)
        return {
            "trade_date": trade_date,
            "status": "no_data",
            "fetched": 0,
            "inserted": 0,
            "before": before_count,
            "after": before_count,
        }

    missing = [c for c in TABLE_COLUMNS if c not in df.columns]
    if missing:
        raise RuntimeError(f"missing columns in Tushare response: {missing}")

    subset = df[TABLE_COLUMNS]
    # Faster conversion than iterrows for bulk insert.
    rows = list(subset.itertuples(index=False, name=None))
    inserted = insert_rows(conn, rows)
    after_count = get_row_count_for_date(conn, trade_date)

    fetched = len(rows)
    if before_count > 0 and after_count < fetched:
        logging.warning(
            "[%s] partial coverage remains: fetched=%d, before=%d, after=%d",
            trade_date,
            fetched,
            before_count,
            after_count,
        )
        status = "partial"
    elif inserted == 0 and before_count > 0:
        status = "already_complete"
    else:
        status = "loaded"

    logging.info(
        "[%s] status=%s fetched=%d inserted=%d before=%d after=%d",
        trade_date,
        status,
        fetched,
        inserted,
        before_count,
        after_count,
    )

    return {
        "trade_date": trade_date,
        "status": status,
        "fetched": fetched,
        "inserted": inserted,
        "before": before_count,
        "after": after_count,
    }


def main() -> int:
    setup_logging()
    args = parse_args()

    token = os.getenv("TUSHARE_TOKEN") or os.getenv("TS_TOKEN")
    if not token and not args.dry_run:
        logging.error("set environment variable TUSHARE_TOKEN (or TS_TOKEN)")
        return 1

    pro = ts.pro_api(token) if token else None

    try:
        target_dates = decide_dates(args, pro) if pro else []
    except ValueError as exc:
        logging.error("%s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        logging.error("failed to resolve target date(s): %s", exc)
        return 1

    if args.dry_run and not target_dates:
        # In dry-run without token, infer date using local rule as fallback.
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        local_fallback = now if now.hour >= 17 else (now - timedelta(days=1))
        while local_fallback.weekday() >= 5:
            local_fallback -= timedelta(days=1)
        target_dates = [local_fallback.strftime("%Y%m%d")]
        logging.info(
            "dry-run without token: fallback date rule used (weekday-only): %s",
            target_dates[0],
        )

    if not target_dates:
        logging.info("no target dates to process")
        return 0

    conn = sqlite3.connect(args.db)
    summary: list[dict[str, Any]] = []
    try:
        if not table_exists(conn, TABLE_NAME):
            logging.error(
                "table '%s' not found in DB: %s. Please create it using daily_stock_quotes.sql first.",
                TABLE_NAME,
                args.db,
            )
            return 1

        validate_table_schema(conn, TABLE_NAME)

        logging.info("target_dates=%s", ",".join(target_dates))
        for i, trade_date in enumerate(target_dates):
            result = pull_for_date(pro, conn, trade_date, args.dry_run)
            summary.append(result)
            if i < len(target_dates) - 1:
                time.sleep(5)
    except Exception as exc:  # noqa: BLE001
        logging.error("run failed: %s", exc)
        return 1
    finally:
        conn.close()

    total_dates = len(summary)
    total_fetched = sum(x["fetched"] for x in summary)
    total_inserted = sum(x["inserted"] for x in summary)
    status_breakdown: dict[str, int] = {}
    for item in summary:
        status_breakdown[item["status"]] = status_breakdown.get(item["status"], 0) + 1

    logging.info(
        "summary: dates=%d fetched=%d inserted=%d statuses=%s",
        total_dates,
        total_fetched,
        total_inserted,
        status_breakdown,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
