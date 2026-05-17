from __future__ import annotations

import time
from typing import Any

import httpx
import pandas as pd

from aflux.datasource import DataSourceError
from aflux.datasource.akshare_src import AKShareSource
from aflux.market import infer_board, normalize_code

EASTMONEY_SNAPSHOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://quote.eastmoney.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}
TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.ProxyError,
)


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
        payload = self._fetch_snapshot_payload(params)

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

    def _fetch_snapshot_payload(self, params: dict[str, str]) -> dict[str, Any]:
        """Fetch snapshot JSON with retry for transient transport errors."""
        errors: list[str] = []
        for trust_env in (True, False):
            for attempt in range(1, 4):
                try:
                    with httpx.Client(
                        timeout=15,
                        headers=EASTMONEY_HEADERS,
                        follow_redirects=True,
                        trust_env=trust_env,
                    ) as client:
                        response = client.get(EASTMONEY_SNAPSHOT_URL, params=params)
                    response.raise_for_status()
                    return response.json()
                except TRANSIENT_EXCEPTIONS as exc:
                    errors.append(f"attempt={attempt} trust_env={trust_env}: {exc}")
                    if attempt < 3:
                        time.sleep(0.3 * attempt)
                except Exception as exc:  # pragma: no cover - external API failure path
                    raise DataSourceError(f"East Money realtime snapshot failed: {exc}") from exc

        detail = "; ".join(errors) if errors else "unknown error"
        raise DataSourceError(
            "East Money realtime snapshot failed after retries. "
            f"Details: {detail}. Try `--source akshare` as fallback."
        )

    def fetch_daily_bars(self, code: str, start: str, end: str) -> pd.DataFrame:
        return self._akshare.fetch_daily_bars(code=code, start=start, end=end)

    def fetch_trading_calendar(self) -> list[str]:
        return self._akshare.fetch_trading_calendar()
