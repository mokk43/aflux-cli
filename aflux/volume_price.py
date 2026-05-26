from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TextIO

REQUIRED_COLUMNS = ("date", "close", "volume")
CSV_OUTPUT_COLUMNS = [
    "code",
    "name",
    "date_range_start",
    "date_range_end",
    "latest_date",
    "primary_type",
    "signals",
    "confidence",
    "metric_latest_close",
    "metric_latest_volume",
    "metric_previous_close",
    "metric_latest_price_change_pct",
    "metric_recent_price_change_pct",
    "metric_prior_avg_volume",
    "metric_latest_volume_ratio",
    "metric_sideways_range_pct",
    "metric_position_range",
    "metric_position_state",
    "metric_full_input_high",
    "metric_full_input_low",
    "interpretation",
    "risk_note",
]

PRIMARY_INTERPRETATION = {
    "天量天价": (
        "价格与成交量同步创全样本新高，量价共振处于阶段性强势。",
        "高换手后波动可能放大，需防范冲高回落风险。",
    ),
    "地量地价": (
        "价格与成交量同步处于全样本低位，市场参与度偏低。",
        "低活跃度阶段方向不明，后续仍需等待量能确认。",
    ),
    "顶背离": (
        "价格创新高但成交量未同步创新高，资金跟随力度减弱。",
        "背离后延续上行的稳定性下降，短线回撤风险抬升。",
    ),
    "底背离": (
        "价格创新低但成交量未同步创新低，抛压边际缓和。",
        "背离仅代表结构改善信号，仍需后续止跌与放量确认。",
    ),
    "向上放量突破": (
        "最新价突破近端区间高点且量能放大，突破动能较明确。",
        "若后续量能无法延续，突破有效性可能下降。",
    ),
    "向下放量破位": (
        "最新价跌破近端区间低点且量能放大，空头动能占优。",
        "放量破位后下行波动可能延续，需关注反抽失败风险。",
    ),
    "缩量横盘": (
        "价格在窄区间运行且量能收缩，市场处于观望状态。",
        "缩量横盘阶段方向不确定，突破前容易反复震荡。",
    ),
    "放量横盘": (
        "价格横盘而量能明显放大，显示区间内存在较强换手。",
        "放量横盘可对应吸筹或派发，需结合后续突破方向判定。",
    ),
    "放量上涨": (
        "近期价格上行且最新量能放大，趋势强度相对积极。",
        "若后续量能回落或涨幅放缓，趋势强度可能减弱。",
    ),
    "缩量上涨": (
        "近期价格上行但最新量能收缩，延续性偏依赖存量资金。",
        "持续缩量可能削弱上行弹性，需关注后续放量确认。",
    ),
    "放量滞涨": (
        "量能放大而价格整体趋平，反映多空分歧增大。",
        "若后续仍难突破，区间上沿压力可能增强。",
    ),
    "放量下跌": (
        "近期价格走弱且量能放大，下行压力偏强。",
        "放量下跌阶段波动风险更高，短线承接不稳。",
    ),
    "缩量下跌": (
        "近期价格走弱但量能收缩，抛压较前期有所减弱。",
        "缩量下跌不代表立即反转，仍需观察企稳证据。",
    ),
    "底部放量": (
        "低位区域出现放量且最新日未明显走弱，存在承接迹象。",
        "单次信号稳定性有限，需结合后续走势确认筑底质量。",
    ),
    "不明确": (
        "当前量价信号偏中性或互相冲突，暂未形成清晰主导关系。",
        "信息优势不足时误判概率更高，宜继续跟踪后续数据。",
    ),
}


class VolumePriceError(ValueError):
    """Raised when user input or analyzer configuration is invalid."""


@dataclass(frozen=True)
class PriceVolumeRow:
    date: date
    close: float
    volume: float


@dataclass(frozen=True)
class AnalyzeConfig:
    lookback: int = 5
    volume_expand_ratio: float = 1.5
    volume_shrink_ratio: float = 0.8
    price_flat_pct: float = 2.0
    sideways_range_pct: float = 3.0
    position_threshold_pct: float = 5.0

    def validate(self) -> None:
        if self.lookback < 5:
            raise VolumePriceError("lookback must be >= 5")
        if self.volume_expand_ratio <= 0:
            raise VolumePriceError("volume-expand-ratio must be > 0")
        if self.volume_shrink_ratio <= 0:
            raise VolumePriceError("volume-shrink-ratio must be > 0")
        if self.price_flat_pct < 0:
            raise VolumePriceError("price-flat-pct must be >= 0")
        if self.sideways_range_pct < 0:
            raise VolumePriceError("sideways-range-pct must be >= 0")
        if self.position_threshold_pct < 0:
            raise VolumePriceError("position-threshold-pct must be >= 0")


@dataclass(frozen=True)
class LoadedInput:
    rows: list[PriceVolumeRow]
    code: str
    name: str


def _round1(value: float) -> float:
    rounded = round(value, 1)
    return 0.0 if rounded == -0.0 else rounded


def _parse_float(raw_value: str, *, field: str, row_number: int) -> float:
    value = raw_value.strip()
    if not value:
        raise VolumePriceError(f"row {row_number}: missing {field}")
    try:
        return float(value)
    except ValueError as exc:
        raise VolumePriceError(f"row {row_number}: invalid {field} '{raw_value}'") from exc


def _parse_date(raw_value: str, *, row_number: int) -> date:
    value = raw_value.strip()
    if not value:
        raise VolumePriceError(f"row {row_number}: missing date")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise VolumePriceError(
            f"row {row_number}: invalid date '{raw_value}' (expected YYYY-MM-DD)"
        ) from exc


def load_csv_input(path: Path) -> LoadedInput:
    if not path.exists():
        raise VolumePriceError(f"input file not found: {path}")

    rows: list[PriceVolumeRow] = []
    seen_dates: set[date] = set()
    code_values: set[str] = set()
    name_values: set[str] = set()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise VolumePriceError("CSV header is missing")

        missing_columns = [
            column for column in REQUIRED_COLUMNS if column not in reader.fieldnames
        ]
        if missing_columns:
            missing = ", ".join(missing_columns)
            raise VolumePriceError(f"missing required columns: {missing}")

        has_code = "code" in reader.fieldnames
        has_name = "name" in reader.fieldnames

        for row_number, row in enumerate(reader, start=2):
            raw_date = row.get("date") or ""
            raw_close = row.get("close") or ""
            raw_volume = row.get("volume") or ""

            parsed_date = _parse_date(raw_date, row_number=row_number)
            if parsed_date in seen_dates:
                raise VolumePriceError(
                    f"row {row_number}: duplicate date '{parsed_date.isoformat()}'"
                )
            seen_dates.add(parsed_date)

            close = _parse_float(raw_close, field="close", row_number=row_number)
            if close <= 0:
                raise VolumePriceError(f"row {row_number}: close must be > 0")

            volume = _parse_float(raw_volume, field="volume", row_number=row_number)
            if volume <= 0:
                raise VolumePriceError(f"row {row_number}: volume must be > 0")

            rows.append(PriceVolumeRow(date=parsed_date, close=close, volume=volume))

            if has_code:
                value = (row.get("code") or "").strip()
                if value:
                    code_values.add(value)
            if has_name:
                value = (row.get("name") or "").strip()
                if value:
                    name_values.add(value)

    if not rows:
        raise VolumePriceError("CSV has no data rows")

    if len(code_values) > 1:
        raise VolumePriceError(
            "CSV contains multiple stock codes; only one stock is supported"
        )
    if len(name_values) > 1:
        raise VolumePriceError(
            "CSV contains multiple stock names; only one stock is supported"
        )

    rows.sort(key=lambda item: item.date)

    code = next(iter(code_values), "")
    name = next(iter(name_values), "")
    return LoadedInput(rows=rows, code=code, name=name)


def _build_signals(
    *,
    lookback: int,
    price_trend: str,
    volume_state: str,
    sideways: bool,
    upward_breakout: bool,
    downward_breakdown: bool,
    position_state: str,
    bottom_volume: bool,
) -> list[str]:
    signals: list[str] = []

    trend_signal = {
        "rising": f"近{lookback}日价格偏强",
        "falling": f"近{lookback}日价格偏弱",
        "flat": f"近{lookback}日价格横向整理",
    }[price_trend]
    signals.append(trend_signal)

    if volume_state == "expand":
        signals.append("最新成交量显著放大")
    elif volume_state == "shrink":
        signals.append("最新成交量明显收缩")
    else:
        signals.append("最新成交量变化中性")

    if sideways:
        signals.append("近端区间波动较窄")

    if upward_breakout:
        signals.append("放量向上突破近端区间")
    if downward_breakdown:
        signals.append("放量向下跌破近端区间")

    if position_state == "high_area":
        signals.append("价格位于全样本高位区域")
    elif position_state == "low_area":
        signals.append("价格位于全样本低位区域")

    if bottom_volume:
        signals.append("低位放量且最新日未显著走弱")

    return signals


def _determine_primary_type(
    *,
    is_full_high: bool,
    is_full_low: bool,
    is_full_max_volume: bool,
    is_full_min_volume: bool,
    sideways: bool,
    upward_breakout: bool,
    downward_breakdown: bool,
    price_trend: str,
    volume_state: str,
    bottom_volume: bool,
) -> str:
    if is_full_high and is_full_max_volume:
        return "天量天价"
    if is_full_low and is_full_min_volume:
        return "地量地价"
    if is_full_high and not is_full_max_volume:
        return "顶背离"
    if is_full_low and not is_full_min_volume:
        return "底背离"

    if upward_breakout:
        return "向上放量突破"
    if downward_breakdown:
        return "向下放量破位"
    if sideways and volume_state == "shrink":
        return "缩量横盘"
    if sideways and volume_state == "expand":
        return "放量横盘"

    if bottom_volume:
        return "底部放量"
    if price_trend == "rising" and volume_state == "expand":
        return "放量上涨"
    if price_trend == "rising" and volume_state == "shrink":
        return "缩量上涨"
    if price_trend == "flat" and volume_state == "expand":
        return "放量滞涨"
    if price_trend == "falling" and volume_state == "expand":
        return "放量下跌"
    if price_trend == "falling" and volume_state == "shrink":
        return "缩量下跌"

    return "不明确"


def _position_state(
    *, latest_close: float, full_high: float, full_low: float, threshold_pct: float
) -> str:
    high_area = latest_close >= full_high * (1 - threshold_pct / 100)
    low_area = latest_close <= full_low * (1 + threshold_pct / 100)
    is_full_high = latest_close == full_high
    is_full_low = latest_close == full_low

    if high_area and low_area:
        if is_full_high and not is_full_low:
            return "high_area"
        if is_full_low and not is_full_high:
            return "low_area"
        return "middle_area"
    if high_area:
        return "high_area"
    if low_area:
        return "low_area"
    return "middle_area"


def analyze_rows(
    rows: list[PriceVolumeRow],
    *,
    code: str,
    name: str,
    config: AnalyzeConfig,
) -> dict[str, object]:
    config.validate()

    if len(rows) < 6:
        raise VolumePriceError("at least 6 valid rows are required")
    if len(rows) < config.lookback + 1:
        raise VolumePriceError(
            f"lookback {config.lookback} requires at least {config.lookback + 1} rows"
        )

    latest = rows[-1]
    previous = rows[-2]
    prior_lookback_rows = rows[-(config.lookback + 1) : -1]
    first_prior_lookback_close = prior_lookback_rows[0].close

    latest_price_change_pct = ((latest.close - previous.close) / previous.close) * 100
    recent_price_change_pct = (
        (latest.close - first_prior_lookback_close) / first_prior_lookback_close
    ) * 100

    prior_avg_volume = sum(item.volume for item in prior_lookback_rows) / config.lookback
    latest_volume_ratio = latest.volume / prior_avg_volume

    closes_for_sideways = [item.close for item in prior_lookback_rows]
    closes_for_sideways.append(latest.close)
    sideways_range_pct = (
        (max(closes_for_sideways) - min(closes_for_sideways))
        / min(closes_for_sideways)
        * 100
    )

    if recent_price_change_pct > config.price_flat_pct:
        price_trend = "rising"
    elif recent_price_change_pct < -config.price_flat_pct:
        price_trend = "falling"
    else:
        price_trend = "flat"

    if latest_volume_ratio >= config.volume_expand_ratio:
        volume_state = "expand"
    elif latest_volume_ratio <= config.volume_shrink_ratio:
        volume_state = "shrink"
    else:
        volume_state = "neutral"

    sideways = sideways_range_pct <= config.sideways_range_pct

    full_input_high = max(item.close for item in rows)
    full_input_low = min(item.close for item in rows)
    full_input_max_volume = max(item.volume for item in rows)
    full_input_min_volume = min(item.volume for item in rows)

    is_full_high = latest.close == full_input_high
    is_full_low = latest.close == full_input_low
    is_full_max_volume = latest.volume == full_input_max_volume
    is_full_min_volume = latest.volume == full_input_min_volume

    position_state = _position_state(
        latest_close=latest.close,
        full_high=full_input_high,
        full_low=full_input_low,
        threshold_pct=config.position_threshold_pct,
    )

    prior_lookback_closes = [item.close for item in prior_lookback_rows]
    upward_breakout = (
        latest.close > max(prior_lookback_closes)
        and latest_volume_ratio >= config.volume_expand_ratio
    )
    downward_breakdown = (
        latest.close < min(prior_lookback_closes)
        and latest_volume_ratio >= config.volume_expand_ratio
    )

    bottom_volume = (
        position_state == "low_area"
        and price_trend in {"falling", "flat"}
        and latest_price_change_pct >= -config.price_flat_pct
        and volume_state == "expand"
        and not is_full_low
    )

    primary_type = _determine_primary_type(
        is_full_high=is_full_high,
        is_full_low=is_full_low,
        is_full_max_volume=is_full_max_volume,
        is_full_min_volume=is_full_min_volume,
        sideways=sideways,
        upward_breakout=upward_breakout,
        downward_breakdown=downward_breakdown,
        price_trend=price_trend,
        volume_state=volume_state,
        bottom_volume=bottom_volume,
    )

    evidence_signals = _build_signals(
        lookback=config.lookback,
        price_trend=price_trend,
        volume_state=volume_state,
        sideways=sideways,
        upward_breakout=upward_breakout,
        downward_breakdown=downward_breakdown,
        position_state=position_state,
        bottom_volume=bottom_volume,
    )

    signals = [signal for signal in evidence_signals if signal not in {"", primary_type}]

    if primary_type == "不明确":
        confidence = "low"
    elif len(signals) >= 2:
        confidence = "high"
    else:
        confidence = "medium"

    interpretation, risk_note = PRIMARY_INTERPRETATION[primary_type]

    result: dict[str, object] = {
        "code": code,
        "name": name,
        "date_range": {
            "start": rows[0].date.isoformat(),
            "end": rows[-1].date.isoformat(),
        },
        "latest_date": latest.date.isoformat(),
        "primary_type": primary_type,
        "signals": signals,
        "confidence": confidence,
        "metrics": {
            "latest_close": latest.close,
            "latest_volume": latest.volume,
            "previous_close": previous.close,
            "latest_price_change_pct": _round1(latest_price_change_pct),
            "recent_price_change_pct": _round1(recent_price_change_pct),
            "prior_avg_volume": prior_avg_volume,
            "latest_volume_ratio": _round1(latest_volume_ratio),
            "sideways_range_pct": _round1(sideways_range_pct),
            "position_range": "full_input",
            "position_state": position_state,
            "full_input_high": full_input_high,
            "full_input_low": full_input_low,
        },
        "interpretation": interpretation,
        "risk_note": risk_note,
    }
    return result


def flatten_result_for_csv(result: dict[str, object]) -> dict[str, object]:
    date_range = result["date_range"]
    metrics = result["metrics"]
    signals = result["signals"]

    assert isinstance(date_range, dict)
    assert isinstance(metrics, dict)
    assert isinstance(signals, list)

    return {
        "code": result["code"],
        "name": result["name"],
        "date_range_start": date_range["start"],
        "date_range_end": date_range["end"],
        "latest_date": result["latest_date"],
        "primary_type": result["primary_type"],
        "signals": ";".join(str(item) for item in signals),
        "confidence": result["confidence"],
        "metric_latest_close": metrics["latest_close"],
        "metric_latest_volume": metrics["latest_volume"],
        "metric_previous_close": metrics["previous_close"],
        "metric_latest_price_change_pct": metrics["latest_price_change_pct"],
        "metric_recent_price_change_pct": metrics["recent_price_change_pct"],
        "metric_prior_avg_volume": metrics["prior_avg_volume"],
        "metric_latest_volume_ratio": metrics["latest_volume_ratio"],
        "metric_sideways_range_pct": metrics["sideways_range_pct"],
        "metric_position_range": metrics["position_range"],
        "metric_position_state": metrics["position_state"],
        "metric_full_input_high": metrics["full_input_high"],
        "metric_full_input_low": metrics["full_input_low"],
        "interpretation": result["interpretation"],
        "risk_note": result["risk_note"],
    }


def write_json(result: dict[str, object], output: TextIO) -> None:
    json.dump(result, output, ensure_ascii=False, indent=2)
    output.write("\n")


def write_csv(result: dict[str, object], output: TextIO) -> None:
    row = flatten_result_for_csv(result)
    writer = csv.DictWriter(output, fieldnames=CSV_OUTPUT_COLUMNS)
    writer.writeheader()
    writer.writerow(row)


def write_table(result: dict[str, object], output: TextIO) -> None:
    metrics = result["metrics"]
    signals = result["signals"]

    assert isinstance(metrics, dict)
    assert isinstance(signals, list)

    rows: list[tuple[str, str]] = [
        ("Code", str(result["code"] or "-")),
        ("Name", str(result["name"] or "-")),
        (
            "Date Range",
            f"{result['date_range']['start']} -> {result['date_range']['end']}",
        ),
        ("Latest Date", str(result["latest_date"])),
        ("Primary Type", str(result["primary_type"])),
        ("Signals", ", ".join(str(item) for item in signals) or "-"),
        ("Confidence", str(result["confidence"])),
        ("Latest Close", f"{float(metrics['latest_close']):.2f}"),
        ("Latest Volume", f"{float(metrics['latest_volume']):.2f}"),
        ("Latest Price Change %", f"{float(metrics['latest_price_change_pct']):.1f}"),
        ("Latest Volume Ratio", f"{float(metrics['latest_volume_ratio']):.1f}"),
        ("Recent Price Change %", f"{float(metrics['recent_price_change_pct']):.1f}"),
        ("Sideways Range %", f"{float(metrics['sideways_range_pct']):.1f}"),
        ("Position State", str(metrics["position_state"])),
        ("Interpretation", str(result["interpretation"])),
        ("Risk Note", str(result["risk_note"])),
    ]

    label_width = max(len(label) for label, _ in rows)
    for label, value in rows:
        output.write(f"{label:<{label_width}} : {value}\n")


def emit_stdout(result: dict[str, object], output_format: str, output: TextIO) -> None:
    if output_format == "json":
        write_json(result, output)
        return
    if output_format == "csv":
        write_csv(result, output)
        return
    if output_format == "table":
        write_table(result, output)
        return
    raise VolumePriceError(f"unsupported format: {output_format}")


def export_result(result: dict[str, object], export_path: Path) -> None:
    _validate_export_path(export_path)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    with export_path.open("w", encoding="utf-8", newline="") as handle:
        if export_path.suffix.lower() == ".json":
            write_json(result, handle)
        else:
            write_csv(result, handle)


def _validate_export_path(export_path: Path) -> None:
    suffix = export_path.suffix.lower()
    if suffix not in {".json", ".csv"}:
        raise VolumePriceError("unsupported export extension; use .json or .csv")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze volume-price relationship from a local CSV."
    )
    parser.add_argument("input", help="CSV file path with date, close, volume columns")
    parser.add_argument(
        "--format",
        choices=("table", "json", "csv"),
        default="table",
        help="stdout output format",
    )
    parser.add_argument("--export", help="Export path (.json or .csv)", default=None)
    parser.add_argument("--lookback", type=int, default=5)
    parser.add_argument("--volume-expand-ratio", type=float, default=1.5)
    parser.add_argument("--volume-shrink-ratio", type=float, default=0.8)
    parser.add_argument("--price-flat-pct", type=float, default=2.0)
    parser.add_argument("--sideways-range-pct", type=float, default=3.0)
    parser.add_argument("--position-threshold-pct", type=float, default=5.0)
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    export_path = Path(args.export) if args.export else None

    config = AnalyzeConfig(
        lookback=args.lookback,
        volume_expand_ratio=args.volume_expand_ratio,
        volume_shrink_ratio=args.volume_shrink_ratio,
        price_flat_pct=args.price_flat_pct,
        sideways_range_pct=args.sideways_range_pct,
        position_threshold_pct=args.position_threshold_pct,
    )
    if export_path:
        _validate_export_path(export_path)

    loaded = load_csv_input(Path(args.input))
    result = analyze_rows(
        loaded.rows,
        code=loaded.code,
        name=loaded.name,
        config=config,
    )

    emit_stdout(result, args.format, sys.stdout)

    if export_path:
        export_result(result, export_path)

    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except (VolumePriceError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive guardrail
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
