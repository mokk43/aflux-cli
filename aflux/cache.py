from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from aflux.models import DailyBar, StockSnapshot

DEFAULT_CACHE_DIR = Path.home() / ".aflux" / "cache"
DB_NAME = "market_data.db"


def resolve_cache_path(cache_dir: str | Path | None = None) -> Path:
    directory = Path(cache_dir).expanduser() if cache_dir else DEFAULT_CACHE_DIR
    return directory / DB_NAME


class MarketDataCache:
    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self.db_path = resolve_cache_path(cache_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_bars (
                    code TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL NOT NULL,
                    turnover REAL NOT NULL,
                    volume INTEGER,
                    PRIMARY KEY (code, date)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS realtime_snapshot (
                    code TEXT NOT NULL,
                    fetch_date TEXT NOT NULL,
                    fetch_time TEXT NOT NULL,
                    name TEXT NOT NULL,
                    price REAL NOT NULL,
                    turnover REAL NOT NULL,
                    prev_close REAL NOT NULL,
                    board TEXT,
                    PRIMARY KEY (code, fetch_date)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trading_calendar (
                    date TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get_daily_bar(self, code: str, trading_date: date) -> DailyBar | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT code, date, open, high, low, close, turnover, volume
                FROM daily_bars
                WHERE code = ? AND date = ?
                """,
                (code, trading_date.isoformat()),
            ).fetchone()
        return self._row_to_daily_bar(row) if row else None

    def get_daily_bars(self, codes: Iterable[str], trading_date: date) -> dict[str, DailyBar]:
        code_list = list(dict.fromkeys(codes))
        if not code_list:
            return {}
        placeholders = ",".join("?" for _ in code_list)
        params = [*code_list, trading_date.isoformat()]
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT code, date, open, high, low, close, turnover, volume
                FROM daily_bars
                WHERE code IN ({placeholders}) AND date = ?
                """,
                params,
            ).fetchall()
        return {row["code"]: self._row_to_daily_bar(row) for row in rows}

    def get_daily_bars_frame(self, codes: Iterable[str], trading_date: date) -> pd.DataFrame:
        code_list = list(dict.fromkeys(codes))
        if not code_list:
            return pd.DataFrame(
                columns=["code", "date", "open", "high", "low", "close", "turnover", "volume"]
            )
        placeholders = ",".join("?" for _ in code_list)
        params = [*code_list, trading_date.isoformat()]
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT code, date, open, high, low, close, turnover, volume
                FROM daily_bars
                WHERE code IN ({placeholders}) AND date = ?
                """,
                params,
            ).fetchall()
        if not rows:
            return pd.DataFrame(
                columns=["code", "date", "open", "high", "low", "close", "turnover", "volume"]
            )
        return pd.DataFrame([dict(row) for row in rows])

    def upsert_daily_bars(self, bars: Iterable[DailyBar]) -> None:
        rows = [
            (
                bar.code,
                bar.date.isoformat(),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.turnover,
                bar.volume,
            )
            for bar in bars
        ]
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                -- Closed trading-day rows are immutable by design.
                INSERT INTO daily_bars
                    (code, date, open, high, low, close, turnover, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code, date) DO NOTHING
                """,
                rows,
            )

    def upsert_daily_bars_frame(self, frame: pd.DataFrame) -> None:
        if frame is None or frame.empty:
            return
        rows = [
            (
                str(row["code"]),
                pd.to_datetime(row["date"]).date().isoformat(),
                row.get("open"),
                row.get("high"),
                row.get("low"),
                row["close"],
                row["turnover"],
                row.get("volume"),
            )
            for _, row in frame.iterrows()
        ]
        with self.connect() as conn:
            conn.executemany(
                """
                -- Closed trading-day rows are immutable by design.
                INSERT INTO daily_bars
                    (code, date, open, high, low, close, turnover, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code, date) DO NOTHING
                """,
                rows,
            )

    def clear_realtime_snapshots(self, fetch_date: date | None = None) -> None:
        with self.connect() as conn:
            if fetch_date is None:
                conn.execute("DELETE FROM realtime_snapshot")
            else:
                conn.execute(
                    "DELETE FROM realtime_snapshot WHERE fetch_date = ?",
                    (fetch_date.isoformat(),),
                )

    def upsert_realtime_snapshots(
        self,
        snapshots: Iterable[StockSnapshot],
        fetch_time: datetime | None = None,
    ) -> None:
        timestamp = fetch_time or datetime.now(tz=UTC)
        rows = [
            (
                snapshot.code,
                timestamp.date().isoformat(),
                timestamp.isoformat(),
                snapshot.name,
                snapshot.price,
                snapshot.turnover,
                snapshot.prev_close,
                str(snapshot.board) if snapshot.board else None,
            )
            for snapshot in snapshots
        ]
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO realtime_snapshot
                    (code, fetch_date, fetch_time, name, price, turnover, prev_close, board)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code, fetch_date) DO UPDATE SET
                    fetch_time = excluded.fetch_time,
                    name = excluded.name,
                    price = excluded.price,
                    turnover = excluded.turnover,
                    prev_close = excluded.prev_close,
                    board = excluded.board
                """,
                rows,
            )

    def get_trading_calendar(self, ttl: timedelta = timedelta(hours=24)) -> list[str] | None:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT date, updated_at FROM trading_calendar ORDER BY date"
            ).fetchall()
        if not rows:
            return None

        latest_update = max(datetime.fromisoformat(row["updated_at"]) for row in rows)
        if datetime.now(tz=UTC) - latest_update > ttl:
            return None
        return [row["date"] for row in rows]

    def set_trading_calendar(self, trading_dates: Iterable[str | date]) -> None:
        updated_at = datetime.now(tz=UTC).isoformat()
        rows = [
            (item.isoformat() if isinstance(item, date) else str(item), updated_at)
            for item in trading_dates
        ]
        if not rows:
            return
        with self.connect() as conn:
            conn.execute("DELETE FROM trading_calendar")
            conn.executemany(
                """
                INSERT INTO trading_calendar (date, updated_at)
                VALUES (?, ?)
                ON CONFLICT(date) DO UPDATE SET updated_at = excluded.updated_at
                """,
                rows,
            )

    @staticmethod
    def _row_to_daily_bar(row: sqlite3.Row) -> DailyBar:
        return DailyBar(
            code=row["code"],
            date=date.fromisoformat(row["date"]),
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            turnover=row["turnover"],
            volume=row["volume"],
        )
