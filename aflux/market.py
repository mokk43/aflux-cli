from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from aflux.models import Board, MarketPhase

CN_TZ = ZoneInfo("Asia/Shanghai")

BOARD_PREFIXES: dict[Board, tuple[str, ...]] = {
    Board.STAR: ("688",),
    Board.CHINEXT: ("300", "301"),
    Board.SME: ("002",),
    Board.BSE: ("82", "83", "87", "88"),
    Board.MAIN: ("600", "601", "603", "000", "001"),
}

ALL_BOARDS = tuple(Board)


def normalize_code(code: str) -> str:
    """Return the six-digit stock code from common market-prefixed forms."""
    cleaned = str(code).strip().upper()
    for prefix in ("SH", "SZ", "BJ"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    return cleaned[-6:].zfill(6)


def infer_board(code: str) -> Board | None:
    normalized = normalize_code(code)
    for board, prefixes in BOARD_PREFIXES.items():
        if normalized.startswith(prefixes):
            return board
    return None


def parse_boards(value: str | list[str] | tuple[str, ...] | None) -> list[Board]:
    if value is None:
        return list(ALL_BOARDS)

    if isinstance(value, str):
        raw_items = [item.strip().lower() for item in value.split(",") if item.strip()]
    else:
        raw_items = [str(item).strip().lower() for item in value if str(item).strip()]

    if not raw_items or "all" in raw_items:
        return list(ALL_BOARDS)

    boards: list[Board] = []
    for item in raw_items:
        try:
            board = Board(item)
        except ValueError as exc:
            valid = ", ".join(board.value for board in ALL_BOARDS)
            raise ValueError(f"Unsupported board '{item}'. Valid boards: {valid}") from exc
        if board not in boards:
            boards.append(board)
    return boards


def code_in_boards(code: str, boards: list[Board] | tuple[Board, ...]) -> bool:
    board = infer_board(code)
    return board in boards if board else False


def now_cn() -> datetime:
    return datetime.now(tz=CN_TZ)


def _ensure_cn_time(value: datetime | None) -> datetime:
    if value is None:
        return now_cn()
    if value.tzinfo is None:
        return value.replace(tzinfo=CN_TZ)
    return value.astimezone(CN_TZ)


def _calendar_dates(trading_calendar: list[str] | list[date] | None) -> set[date] | None:
    if not trading_calendar:
        return None
    dates: set[date] = set()
    for item in trading_calendar:
        if isinstance(item, date):
            dates.add(item)
        else:
            dates.add(date.fromisoformat(str(item)))
    return dates


def is_trading_day(day: date, trading_calendar: list[str] | list[date] | None = None) -> bool:
    calendar = _calendar_dates(trading_calendar)
    if calendar is not None:
        return day in calendar
    return day.weekday() < 5


def get_market_phase(
    when: datetime | None = None,
    trading_calendar: list[str] | list[date] | None = None,
) -> MarketPhase:
    current = _ensure_cn_time(when)
    if not is_trading_day(current.date(), trading_calendar):
        return MarketPhase.OFF_MARKET

    current_time = current.time()
    if time(9, 15) <= current_time < time(9, 30):
        return MarketPhase.PREMARKET_AUCTION
    if time(9, 30) <= current_time <= time(15, 0):
        return MarketPhase.INTRADAY
    return MarketPhase.OFF_MARKET


def should_use_realtime_path(phase: MarketPhase) -> bool:
    return phase in {MarketPhase.PREMARKET_AUCTION, MarketPhase.INTRADAY}


def latest_completed_trading_dates(
    trading_calendar: list[str] | list[date],
    when: datetime | None = None,
    count: int = 2,
) -> list[date]:
    """Return the latest completed trading dates, newest first."""
    current = _ensure_cn_time(when)
    calendar = sorted(_calendar_dates(trading_calendar) or set())
    if not calendar:
        raise ValueError("Trading calendar is empty.")

    include_today = current.time() > time(15, 0)
    cutoff = current.date() if include_today else current.date()

    dates = [
        item
        for item in calendar
        if item < cutoff or (include_today and item == current.date())
    ]
    if len(dates) < count:
        raise ValueError(f"Need at least {count} completed trading dates.")
    return list(reversed(dates[-count:]))
