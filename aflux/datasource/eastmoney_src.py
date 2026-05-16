from __future__ import annotations

from typing import Any

import httpx
import pandas as pd

from aflux.datasource import DataSourceError
from aflux.datasource.akshare_src import AKShareSource
from aflux.market import infer_board, normalize_code

EASTMONEY_SNAPSHOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if value in {"", "-", "--"}:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class EastMoneySource:
    """Direct East Money realtime source with AKShare historical fallback."""

    def __init__(self) -> None:
        self._akshare = AKShareSource()

    def fetch_realtime_snapshot(self) -> pd.DataFrame:
        params = {
            "pn": "1",
            "pz": "6000",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            # SH/SZ A-share plus Beijing board where available.
            "fs": "m:0+t:6,m:0+t:80,m:0+t:81+s:2048,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f2,f6,f18",
        }
        try:
            response = httpx.get(EASTMONEY_SNAPSHOT_URL, params=params, timeout=15)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # pragma: no cover - external API failure path
            raise DataSourceError(f"East Money realtime snapshot failed: {exc}") from exc

        items = payload.get("data", {}).get("diff") or []
        rows: list[dict[str, Any]] = []
        for item in items:
            code = normalize_code(str(item.get("f12", "")))
            price = _to_float(item.get("f2"))
            prev_close = _to_float(item.get("f18"))
            turnover = _to_float(item.get("f6")) or 0.0
            if price is None or prev_close is None:
                continue
            rows.append(
                {
                    "code": code,
                    "name": str(item.get("f14", "")),
                    "price": price,
                    "turnover": turnover,
                    "prev_close": prev_close,
                    "board": infer_board(code),
                }
            )
        return pd.DataFrame(rows)

    def fetch_daily_bars(self, code: str, start: str, end: str) -> pd.DataFrame:
        return self._akshare.fetch_daily_bars(code=code, start=start, end=end)

    def fetch_trading_calendar(self) -> list[str]:
        return self._akshare.fetch_trading_calendar()
