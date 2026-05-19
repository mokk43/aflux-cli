#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

PCT_CHG_THRESHOLD = 5.0
VOL_RATIO_THRESHOLD = 1.77
DAILY_TABLE = "daily_stock_quotes"
STOCK_BASIC_TABLE = "stock_basic"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基于本地 SQLite 数据筛选放量上涨股票")
    parser.add_argument("trade_date", nargs="?", default=None, help="目标交易日，格式 YYYYMMDD")
    parser.add_argument("--db", default="shares_stat.db", help="sqlite DB path")
    return parser.parse_args()


def validate_trade_date(trade_date: str) -> None:
    try:
        datetime.strptime(trade_date, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"trade_date 必须为 YYYYMMDD，当前值: {trade_date}") from exc


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def has_rows_for_date(conn: sqlite3.Connection, trade_date: str) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {DAILY_TABLE} WHERE trade_date=? LIMIT 1",
        (trade_date,),
    ).fetchone()
    return row is not None


def get_last_two_trade_dates(conn: sqlite3.Connection, as_of: str | None = None) -> list[str]:
    if as_of:
        rows = conn.execute(
            f"""
            SELECT DISTINCT trade_date
            FROM {DAILY_TABLE}
            WHERE trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT 2
            """,
            (as_of,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT DISTINCT trade_date
            FROM {DAILY_TABLE}
            ORDER BY trade_date DESC
            LIMIT 2
            """
        ).fetchall()
    return [row[0] for row in rows]


def ensure_data(conn: sqlite3.Connection, trade_date: str | None) -> None:
    existing_dates = get_last_two_trade_dates(conn, trade_date)
    if len(existing_dates) >= 2 and (trade_date is None or existing_dates[0] == trade_date):
        return

    print("本地数据不足，尝试自动拉取目标交易日及前一交易日数据...")
    try:
        import tushare as ts
        from pull_daily_stock_quotes import call_with_retry, pull_for_date, resolve_open_trading_day
    except Exception as exc:  # noqa: BLE001
        print(f"警告: 无法加载自动拉取依赖 ({exc})，将继续使用数据库现有数据。")
        return

    try:
        pro = ts.pro_api()
        if trade_date:
            target_date = trade_date
        else:
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            target_date = resolve_open_trading_day(pro, now)

        start_date = (datetime.strptime(target_date, "%Y%m%d") - timedelta(days=20)).strftime(
            "%Y%m%d"
        )
        cal = call_with_retry(
            pro.trade_cal,
            exchange="",
            start_date=start_date,
            end_date=target_date,
            fields="cal_date,is_open",
        )
        if cal is None or cal.empty:
            raise RuntimeError("trade_cal 返回空数据")

        open_dates = sorted(cal.loc[cal["is_open"] == 1, "cal_date"].tolist())
        open_dates = [d for d in open_dates if d <= target_date]
        dates_to_pull = open_dates[-2:]
        if not dates_to_pull:
            raise RuntimeError("未找到可拉取的交易日")

        for date_to_pull in dates_to_pull:
            pull_for_date(pro, conn, date_to_pull, dry_run=False)
    except Exception as exc:  # noqa: BLE001
        print(f"警告: 自动拉取数据失败 ({exc})，将继续使用数据库现有数据。")


def resolve_trade_dates(conn: sqlite3.Connection, trade_date: str | None) -> tuple[str, str]:
    if trade_date:
        if not has_rows_for_date(conn, trade_date):
            raise RuntimeError(f"数据库中没有 {trade_date} 的日线数据")
        dates = get_last_two_trade_dates(conn, trade_date)
    else:
        dates = get_last_two_trade_dates(conn)

    if len(dates) < 2:
        raise RuntimeError("数据库中可用交易日不足 2 天，无法计算 vol_ratio")
    return dates[0], dates[1]


def query_screened_quotes(conn: sqlite3.Connection, trade_date: str, prev_date: str) -> pd.DataFrame:
    sql = f"""
    SELECT
      t.ts_code,
      t.close,
      t.pct_chg,
      t.vol,
      t.amount,
      p.vol AS vol_p
    FROM {DAILY_TABLE} t
    JOIN {DAILY_TABLE} p
      ON t.ts_code = p.ts_code
     AND p.trade_date = ?
    WHERE t.trade_date = ?
      AND t.pct_chg >= ?
      AND COALESCE(p.vol, 0) > 0
    """
    df = pd.read_sql_query(sql, conn, params=(prev_date, trade_date, PCT_CHG_THRESHOLD))
    if df.empty:
        return df

    df["vol_ratio"] = df["vol"] / df["vol_p"]
    return df[df["vol_ratio"] >= VOL_RATIO_THRESHOLD].copy().sort_values("pct_chg", ascending=False)


def attach_stock_info(conn: sqlite3.Connection, result: pd.DataFrame) -> pd.DataFrame:
    if result.empty:
        result["name"] = ""
        result["industry"] = ""
        return result

    if not table_exists(conn, STOCK_BASIC_TABLE):
        print("警告: stock_basic 表不存在，名称/行业列将显示为空。")
        result["name"] = ""
        result["industry"] = ""
        return result

    stock_info = pd.read_sql_query(
        f"SELECT ts_code, name, industry FROM {STOCK_BASIC_TABLE}",
        conn,
    )
    if stock_info.empty:
        print("警告: stock_basic 表为空，名称/行业列将显示为空。")
        result["name"] = ""
        result["industry"] = ""
        return result

    merged = result.merge(stock_info, on="ts_code", how="left")
    merged["name"] = merged["name"].fillna("")
    merged["industry"] = merged["industry"].fillna("")
    return merged


def screen_volume_boom(conn: sqlite3.Connection, trade_date: str | None = None):
    ensure_data(conn, trade_date)
    trade_date, prev_date = resolve_trade_dates(conn, trade_date)
    print(f"对比交易日: {trade_date} vs {prev_date}")

    result = query_screened_quotes(conn, trade_date, prev_date)
    result = attach_stock_info(conn, result)
    return result, trade_date, prev_date


def main() -> int:
    args = parse_args()
    if args.trade_date:
        try:
            validate_trade_date(args.trade_date)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1

    conn = sqlite3.connect(args.db)
    try:
        if not table_exists(conn, DAILY_TABLE):
            print(
                f"ERROR: 表 '{DAILY_TABLE}' 在数据库中不存在: {args.db}。"
                "请先用 daily_stock_quotes.sql 创建表结构。"
            )
            return 1

        result, today, _ = screen_volume_boom(conn, args.trade_date)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        return 1
    finally:
        conn.close()

    print("\n===== 筛选结果 =====")
    print(f"满足条件(涨幅>=5% 且 量比>=1.77): {len(result)} 只\n")

    if result.empty:
        print("无符合条件的股票")
        return 0

    cols = ["ts_code", "name", "industry", "close", "pct_chg", "vol", "vol_ratio", "amount"]
    disp = result[cols].copy()
    for col in ["close", "pct_chg", "vol", "vol_ratio", "amount"]:
        disp[col] = disp[col].round(2)

    print(disp.to_string(index=False))

    print("\n===== 统计摘要 =====")
    print(f"平均涨幅: {disp['pct_chg'].mean():.2f}%")
    print(f"最大涨幅: {disp['pct_chg'].max():.2f}%")
    print(f"中位数量比: {disp['vol_ratio'].median():.2f}")

    industry_count = result["industry"].replace("", pd.NA).dropna().value_counts().head(10)
    print("\n行业分布 (Top 10):")
    if industry_count.empty:
        print("  行业信息不可用")
    else:
        for ind, cnt in industry_count.items():
            print(f"  {ind}: {cnt}只")

    csv_path = f"volume_surge_{today}.csv"
    disp.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n结果已保存至: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
