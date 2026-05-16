from __future__ import annotations

from typing import Protocol

import pandas as pd

from aflux.models import SourceName


class DataSourceError(RuntimeError):
    pass


class DataSource(Protocol):
    def fetch_realtime_snapshot(self) -> pd.DataFrame:
        """Return columns: code, name, price, turnover, prev_close, board."""

    def fetch_daily_bars(self, code: str, start: str, end: str) -> pd.DataFrame:
        """Return columns: code, date, open, high, low, close, turnover, volume."""

    def fetch_trading_calendar(self) -> list[str]:
        """Return trading dates as YYYY-MM-DD strings."""


def get_datasource(source: str | SourceName) -> DataSource:
    source_name = SourceName(source)
    if source_name is SourceName.AKSHARE:
        from aflux.datasource.akshare_src import AKShareSource

        return AKShareSource()
    if source_name is SourceName.EASTMONEY:
        from aflux.datasource.eastmoney_src import EastMoneySource

        return EastMoneySource()
    raise DataSourceError(f"Unsupported data source: {source}")
