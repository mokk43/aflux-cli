from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Board(StrEnum):
    STAR = "star"
    CHINEXT = "chinext"
    SME = "sme"
    MAIN = "main"
    BSE = "bse"


class MarketPhase(StrEnum):
    PREMARKET_AUCTION = "premarket_auction"
    INTRADAY = "intraday"
    OFF_MARKET = "off_market"


class SourceName(StrEnum):
    AKSHARE = "akshare"
    EASTMONEY = "eastmoney"


class OutputFormat(StrEnum):
    AUTO = "auto"
    TABLE = "table"
    CSV = "csv"
    JSON = "json"


class StockSnapshot(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    code: str
    name: str
    price: float
    turnover: float = Field(ge=0, description="Current turnover normalized to yuan.")
    prev_close: float
    board: Board | None = None


class DailyBar(BaseModel):
    code: str
    date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float
    turnover: float = Field(ge=0, description="Turnover normalized to yuan.")
    volume: int | None = None


class ScanResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    code: str
    name: str
    price: float
    price_change_pct: float
    volume_ratio_pct: float
    turnover: float = Field(ge=0, description="Current turnover normalized to yuan.")
    prev_turnover: float = Field(ge=0, description="Previous turnover normalized to yuan.")
    board: Board | None = None


class ScanResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    scan_time: datetime
    market_open: bool
    market_phase: MarketPhase
    count: int
    results: list[ScanResult]


class ErrorResponse(BaseModel):
    error: str
