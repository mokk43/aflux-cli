from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from aflux.datasource import DataSourceError
from aflux.market import infer_board, normalize_code


def _import_akshare() -> Any:
    try:
        import akshare as ak  # type: ignore[import-not-found]
    except ImportError as exc:
        raise DataSourceError(
            "AKShare is not installed. Install project dependencies with `pip install -e .`."
        ) from exc
    return ak


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if value in {"", "-", "--"}:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None else None


def _to_date_string(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    parsed = pd.to_datetime(value)
    return parsed.date().isoformat()


def _normalize_turnover(value: Any, unit: str = "yuan") -> float:
    number = _to_float(value)
    if number is None:
        return 0.0
    if unit == "wan":
        return number * 10_000
    return number


class AKShareSource:
    def fetch_realtime_snapshot(self) -> pd.DataFrame:
        ak = _import_akshare()
        try:
            raw = ak.stock_zh_a_spot_em()
        except Exception as exc:  # pragma: no cover - external API failure path
            raise DataSourceError(f"AKShare realtime snapshot failed: {exc}") from exc

        required = {"代码", "名称", "最新价", "成交额", "昨收"}
        missing = required - set(raw.columns)
        if missing:
            raise DataSourceError(f"AKShare realtime snapshot missing columns: {missing}")

        rows: list[dict[str, Any]] = []
        for _, item in raw.iterrows():
            code = normalize_code(str(item["代码"]))
            price = _to_float(item["最新价"])
            prev_close = _to_float(item["昨收"])
            if price is None or prev_close is None:
                continue
            rows.append(
                {
                    "code": code,
                    "name": str(item["名称"]),
                    "price": price,
                    "turnover": _normalize_turnover(item["成交额"], unit="yuan"),
                    "prev_close": prev_close,
                    "board": infer_board(code),
                }
            )
        return pd.DataFrame(rows)

    def fetch_daily_bars(self, code: str, start: str, end: str) -> pd.DataFrame:
        ak = _import_akshare()
        symbol = normalize_code(code)
        start_date = start.replace("-", "")
        end_date = end.replace("-", "")
        try:
            raw = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="",
            )
        except Exception as exc:  # pragma: no cover - external API failure path
            raise DataSourceError(f"AKShare daily bars failed for {symbol}: {exc}") from exc

        if raw is None or raw.empty:
            return pd.DataFrame(
                columns=["code", "date", "open", "high", "low", "close", "turnover", "volume"]
            )

        rows: list[dict[str, Any]] = []
        for _, item in raw.iterrows():
            turnover = item.get("成交额")
            rows.append(
                {
                    "code": symbol,
                    "date": _to_date_string(item["日期"]),
                    "open": _to_float(item.get("开盘")),
                    "high": _to_float(item.get("最高")),
                    "low": _to_float(item.get("最低")),
                    "close": _to_float(item.get("收盘")) or 0.0,
                    "turnover": _normalize_turnover(turnover, unit="yuan"),
                    "volume": _to_int(item.get("成交量")),
                }
            )
        return pd.DataFrame(rows)

    def fetch_trading_calendar(self) -> list[str]:
        ak = _import_akshare()
        try:
            raw = ak.tool_trade_date_hist_sina()
        except Exception as exc:  # pragma: no cover - external API failure path
            raise DataSourceError(f"AKShare trading calendar failed: {exc}") from exc

        column = "trade_date" if "trade_date" in raw.columns else raw.columns[0]
        return [_to_date_string(item) for item in raw[column].tolist()]
