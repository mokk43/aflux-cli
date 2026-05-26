from __future__ import annotations

from typing import Any

import pandas as pd

from aflux.market import code_in_boards, infer_board, normalize_code
from aflux.models import Board, ScanResult


def _empty_snapshot() -> pd.DataFrame:
    return pd.DataFrame(columns=["code", "name", "price", "turnover", "prev_close", "board"])


def _empty_daily() -> pd.DataFrame:
    return pd.DataFrame(columns=["code", "date", "open", "high", "low", "close", "turnover", "volume"])


def normalize_snapshot_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return _empty_snapshot()
    result = frame.copy()
    result["code"] = result["code"].map(normalize_code)
    result["name"] = result["name"].astype(str)
    for column in ("price", "turnover", "prev_close"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if "board" not in result.columns:
        result["board"] = result["code"].map(infer_board)
    else:
        result["board"] = result["board"].where(result["board"].notna(), result["code"].map(infer_board))
    return result.dropna(subset=["code", "price", "prev_close"])


def normalize_daily_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return _empty_daily()
    result = frame.copy()
    result["code"] = result["code"].map(normalize_code)
    for column in ("open", "high", "low", "close", "turnover", "volume"):
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.dropna(subset=["code", "close", "turnover"])


def apply_board_filter(frame: pd.DataFrame, boards: list[Board]) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = normalize_snapshot_frame(frame) if "price" in frame.columns else normalize_daily_frame(frame)
    return result[result["code"].map(lambda code: code_in_boards(code, boards))].copy()


def exclude_edge_cases(frame: pd.DataFrame, include_st: bool = False) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    if not include_st and "name" in result.columns:
        names = result["name"].astype(str).str.upper().str.strip()
        result = result[~names.str.match(r"^(\*?ST|S\*?ST)", na=False)]
    if "turnover" in result.columns:
        result = result[result["turnover"].fillna(0) > 0]
    if "prev_close" in result.columns:
        result = result[result["prev_close"].fillna(0) > 0]
    return result.copy()


def prefilter_by_price_change(
    snapshot: pd.DataFrame,
    price_change_threshold: float,
) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot
    result = snapshot.copy()
    result = result[result["prev_close"].fillna(0) > 0]
    result["price_change_pct"] = (
        (result["price"] - result["prev_close"]) / result["prev_close"] * 100
    )
    return result[result["price_change_pct"] >= price_change_threshold].copy()


def scan(
    current: pd.DataFrame,
    prev_daily: pd.DataFrame,
    volume_ratio_threshold: float,
    price_change_threshold: float,
    include_st: bool = False,
) -> list[ScanResult]:
    """Apply final scan thresholds on preprocessed frames and return structured results."""
    # `current` and `prev_daily` are expected to be normalized and prefiltered by core.py.
    # Keep `include_st` in the signature for backward compatibility with existing callers.
    _ = include_st
    current_frame = current
    prev_frame = prev_daily
    if current_frame.empty or prev_frame.empty:
        return []

    prev_frame = prev_frame[prev_frame["turnover"].fillna(0) > 0]
    if prev_frame.empty:
        return []

    merged = current_frame.merge(
        prev_frame[["code", "close", "turnover"]],
        on="code",
        suffixes=("", "_prev"),
    )
    if merged.empty:
        return []

    merged = merged[merged["turnover_prev"].fillna(0) > 0]
    merged["volume_ratio_pct"] = merged["turnover"] / merged["turnover_prev"] * 100
    merged["price_change_pct"] = (merged["price"] - merged["close"]) / merged["close"] * 100
    filtered = merged[
        (merged["volume_ratio_pct"] >= volume_ratio_threshold)
        & (merged["price_change_pct"] >= price_change_threshold)
    ].copy()
    if filtered.empty:
        return []

    filtered = filtered.sort_values(
        by=["volume_ratio_pct", "price_change_pct"],
        ascending=[False, False],
    )
    return [_row_to_scan_result(row) for _, row in filtered.iterrows()]


def _row_to_scan_result(row: pd.Series) -> ScanResult:
    board = _coerce_board(row.get("board")) or infer_board(str(row["code"]))
    return ScanResult(
        code=str(row["code"]),
        name=str(row["name"]),
        price=float(row["price"]),
        price_change_pct=float(row["price_change_pct"]),
        volume_ratio_pct=float(row["volume_ratio_pct"]),
        turnover=float(row["turnover"]),
        prev_turnover=float(row["turnover_prev"]),
        board=board,
    )


def _coerce_board(value: Any) -> Board | None:
    if isinstance(value, Board):
        return value
    if value is None or pd.isna(value):
        return None
    try:
        return Board(str(value))
    except ValueError:
        return None
