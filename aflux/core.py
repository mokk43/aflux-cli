from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

import pandas as pd

from aflux.cache import MarketDataCache
from aflux.datasource import DataSource, DataSourceError, get_datasource
from aflux.datasource.eastmoney_src import EastMoneySource
from aflux.market import (
    get_market_phase,
    latest_completed_trading_dates,
    now_cn,
    parse_boards,
    should_use_realtime_path,
)
from aflux.models import Board, MarketPhase, ScanResponse, ScanResult, SourceName, StockSnapshot
from aflux.scanner import (
    apply_board_filter,
    exclude_edge_cases,
    normalize_daily_frame,
    normalize_snapshot_frame,
    prefilter_by_price_change,
    scan,
)

ProgressCallback = Callable[[int, int, str], None]


def run_scan(
    volume_ratio: float = 50.0,
    price_change: float = 2.0,
    boards: list[str] | list[Board] | str | None = None,
    source: str = "akshare",
    no_cache: bool = False,
    cache_dir: str | None = None,
    include_st: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> ScanResponse:
    selected_boards = parse_boards(boards)
    cache = MarketDataCache(cache_dir)
    datasource = get_datasource(source)
    trading_calendar = _get_trading_calendar(datasource, cache, no_cache=no_cache)
    phase = get_market_phase(trading_calendar=trading_calendar)
    scan_time = now_cn()

    if should_use_realtime_path(phase):
        previous_day_offset = 1
    else:
        previous_day_offset = 2

    results = _run_scan_pipeline(
        datasource=datasource,
        cache=cache,
        trading_calendar=trading_calendar,
        selected_boards=selected_boards,
        volume_ratio=volume_ratio,
        price_change=price_change,
        no_cache=no_cache,
        include_st=include_st,
        progress_callback=progress_callback,
        source=source,
        previous_day_offset=previous_day_offset,
    )

    return ScanResponse(
        scan_time=scan_time,
        market_open=phase is MarketPhase.INTRADAY,
        market_phase=phase,
        count=len(results),
        results=results,
    )


def warm_cache(
    trading_date: str | date | None = None,
    boards: list[str] | list[Board] | str | None = None,
    source: str = "akshare",
    cache_dir: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> int:
    selected_boards = parse_boards(boards)
    cache = MarketDataCache(cache_dir)
    datasource = get_datasource(source)
    trading_calendar = _get_trading_calendar(datasource, cache, no_cache=False)
    target_date = _resolve_warm_date(trading_date, trading_calendar)

    snapshot = _fetch_realtime_snapshot(datasource, source=source)
    snapshot = apply_board_filter(snapshot, selected_boards)
    codes = snapshot["code"].drop_duplicates().tolist()
    bars = _get_daily_bars_for_codes(
        datasource=datasource,
        cache=cache,
        codes=codes,
        trading_date=target_date,
        no_cache=True,
        progress_callback=progress_callback,
    )
    return len(bars)


def _run_scan_pipeline(
    datasource: DataSource,
    cache: MarketDataCache,
    trading_calendar: list[str],
    selected_boards: list[Board],
    volume_ratio: float,
    price_change: float,
    no_cache: bool,
    include_st: bool,
    progress_callback: ProgressCallback | None,
    source: str,
    previous_day_offset: int,
) -> list[ScanResult]:
    trading_dates = latest_completed_trading_dates(trading_calendar, count=previous_day_offset)
    previous_date = trading_dates[-1]
    snapshot = _fetch_realtime_snapshot(datasource, source=source)
    _cache_realtime_snapshot(cache, snapshot)
    board_filtered = apply_board_filter(snapshot, selected_boards)
    edge_filtered = exclude_edge_cases(board_filtered, include_st=include_st)
    candidates = prefilter_by_price_change(edge_filtered, price_change)
    codes = candidates["code"].drop_duplicates().tolist()

    prev_frame = _get_daily_bars_for_codes(
        datasource=datasource,
        cache=cache,
        codes=codes,
        trading_date=previous_date,
        no_cache=no_cache,
        progress_callback=progress_callback,
    )
    return scan(
        current=candidates,
        prev_daily=prev_frame,
        volume_ratio_threshold=volume_ratio,
        price_change_threshold=price_change,
        include_st=include_st,
    )


def _get_trading_calendar(
    datasource: DataSource,
    cache: MarketDataCache,
    no_cache: bool,
) -> list[str]:
    if not no_cache:
        cached = cache.get_trading_calendar()
        if cached:
            return cached
    trading_calendar = datasource.fetch_trading_calendar()
    cache.set_trading_calendar(trading_calendar)
    return trading_calendar


def _fetch_realtime_snapshot(datasource: DataSource, source: str) -> pd.DataFrame:
    try:
        return normalize_snapshot_frame(datasource.fetch_realtime_snapshot())
    except DataSourceError:
        if SourceName(source) is not SourceName.AKSHARE:
            raise
        fallback = EastMoneySource()
        return normalize_snapshot_frame(fallback.fetch_realtime_snapshot())


def _cache_realtime_snapshot(cache: MarketDataCache, snapshot: pd.DataFrame) -> None:
    if snapshot.empty:
        return
    # Realtime snapshot cache is ephemeral by design; clear each scan run.
    cache.clear_realtime_snapshots()
    cache.upsert_realtime_snapshots(_snapshot_models(snapshot), now_cn())


def _get_daily_bars_for_codes(
    datasource: DataSource,
    cache: MarketDataCache,
    codes: list[str],
    trading_date: date,
    no_cache: bool,
    progress_callback: ProgressCallback | None,
) -> pd.DataFrame:
    unique_codes = list(dict.fromkeys(codes))
    if not unique_codes:
        return pd.DataFrame(columns=["code", "date", "open", "high", "low", "close", "turnover", "volume"])

    cached = (
        pd.DataFrame(columns=["code", "date", "open", "high", "low", "close", "turnover", "volume"])
        if no_cache
        else cache.get_daily_bars_frame(unique_codes, trading_date)
    )
    cached_codes = set(cached["code"].astype(str).tolist()) if not cached.empty else set()
    missing = [code for code in unique_codes if code not in cached_codes]
    fetched_frames: list[pd.DataFrame] = []

    total = len(missing)
    for index, code in enumerate(missing, start=1):
        if progress_callback:
            progress_callback(index - 1, total, code)
        frame = datasource.fetch_daily_bars(
            code=code,
            start=trading_date.isoformat(),
            end=trading_date.isoformat(),
        )
        normalized = normalize_daily_frame(frame)
        if not normalized.empty:
            fetched_frames.append(normalized)
            cache.upsert_daily_bars_frame(normalized)
        if progress_callback:
            progress_callback(index, total, code)

    frames: list[pd.DataFrame] = []
    if not cached.empty:
        frames.append(cached)
    frames.extend(fetched_frames)
    if not frames:
        return pd.DataFrame(columns=["code", "date", "open", "high", "low", "close", "turnover", "volume"])
    merged = pd.concat(frames, ignore_index=True)
    if merged.empty:
        return merged
    return merged.drop_duplicates(subset=["code"], keep="first").copy()


def _snapshot_models(snapshot: pd.DataFrame) -> list[StockSnapshot]:
    models: list[StockSnapshot] = []
    for _, row in snapshot.iterrows():
        models.append(
            StockSnapshot(
                code=str(row["code"]),
                name=str(row["name"]),
                price=float(row["price"]),
                turnover=float(row["turnover"]),
                prev_close=float(row["prev_close"]),
                board=row.get("board"),
            )
        )
    return models


def _resolve_warm_date(value: str | date | None, trading_calendar: list[str]) -> date:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(value)
    return latest_completed_trading_dates(trading_calendar, count=1)[0]
