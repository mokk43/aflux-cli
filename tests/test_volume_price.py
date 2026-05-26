from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from aflux.volume_price import (
    AnalyzeConfig,
    PriceVolumeRow,
    VolumePriceError,
    analyze_rows,
    export_result,
    flatten_result_for_csv,
    load_csv_input,
)


class VolumePriceClassifierTest(unittest.TestCase):
    def _rows(self, closes: list[float], volumes: list[float]) -> list[PriceVolumeRow]:
        self.assertEqual(len(closes), len(volumes))
        rows: list[PriceVolumeRow] = []
        for index, (close, volume) in enumerate(zip(closes, volumes, strict=True), start=1):
            rows.append(
                PriceVolumeRow(
                    date=date(2026, 1, index),
                    close=close,
                    volume=volume,
                )
            )
        return rows

    def _classify(
        self,
        closes: list[float],
        volumes: list[float],
        lookback: int = 5,
    ) -> dict[str, object]:
        rows = self._rows(closes, volumes)
        return analyze_rows(
            rows,
            code="600000",
            name="样本",
            config=AnalyzeConfig(lookback=lookback),
        )

    def test_fangliang_shangzhang(self) -> None:
        result = self._classify(
            [10.0, 11.5, 10.8, 10.9, 11.0, 11.2],
            [100.0, 260.0, 105.0, 115.0, 120.0, 240.0],
        )
        self.assertEqual(result["primary_type"], "放量上涨")

    def test_suoliang_shangzhang(self) -> None:
        result = self._classify(
            [10.0, 11.5, 10.8, 10.9, 11.0, 11.2],
            [100.0, 200.0, 150.0, 140.0, 130.0, 100.0],
        )
        self.assertEqual(result["primary_type"], "缩量上涨")

    def test_fangliang_zhizhang(self) -> None:
        result = self._classify(
            [10.0, 10.6, 10.3, 9.9, 10.2, 10.1],
            [100.0, 120.0, 110.0, 100.0, 90.0, 220.0],
        )
        self.assertEqual(result["primary_type"], "放量滞涨")

    def test_fangliang_xiadie(self) -> None:
        result = self._classify(
            [10.0, 9.8, 9.7, 9.6, 9.5, 9.6],
            [100.0, 140.0, 130.0, 120.0, 110.0, 220.0],
        )
        self.assertEqual(result["primary_type"], "放量下跌")

    def test_suoliang_xiadie(self) -> None:
        result = self._classify(
            [10.0, 9.8, 9.7, 9.6, 9.5, 9.6],
            [200.0, 180.0, 170.0, 160.0, 150.0, 100.0],
        )
        self.assertEqual(result["primary_type"], "缩量下跌")

    def test_dibu_fangliang(self) -> None:
        result = self._classify(
            [10.0, 9.6, 9.3, 9.0, 9.1, 9.2],
            [100.0, 110.0, 120.0, 130.0, 90.0, 200.0],
        )
        self.assertEqual(result["primary_type"], "底部放量")

    def test_tianliang_tianjia(self) -> None:
        result = self._classify(
            [10.0, 10.2, 10.1, 10.3, 10.4, 10.6],
            [100.0, 110.0, 120.0, 130.0, 140.0, 200.0],
        )
        self.assertEqual(result["primary_type"], "天量天价")

    def test_diliang_dijia(self) -> None:
        result = self._classify(
            [10.5, 10.4, 10.3, 10.2, 10.1, 9.9],
            [200.0, 190.0, 180.0, 170.0, 160.0, 100.0],
        )
        self.assertEqual(result["primary_type"], "地量地价")

    def test_dingbeili(self) -> None:
        result = self._classify(
            [10.0, 10.2, 10.3, 10.4, 10.5, 10.6],
            [100.0, 300.0, 200.0, 190.0, 180.0, 170.0],
        )
        self.assertEqual(result["primary_type"], "顶背离")

    def test_dibeili(self) -> None:
        result = self._classify(
            [10.5, 10.3, 10.2, 10.1, 10.0, 9.8],
            [100.0, 90.0, 80.0, 70.0, 60.0, 120.0],
        )
        self.assertEqual(result["primary_type"], "底背离")

    def test_suoliang_hengpan(self) -> None:
        result = self._classify(
            [10.0, 10.2, 10.1, 10.15, 10.05, 10.1],
            [200.0, 180.0, 170.0, 160.0, 150.0, 100.0],
        )
        self.assertEqual(result["primary_type"], "缩量横盘")

    def test_fangliang_hengpan(self) -> None:
        result = self._classify(
            [10.0, 10.2, 10.1, 10.15, 10.05, 10.1],
            [100.0, 110.0, 120.0, 100.0, 90.0, 220.0],
        )
        self.assertEqual(result["primary_type"], "放量横盘")

    def test_upward_breakout_confirmation(self) -> None:
        result = self._classify(
            [12.0, 10.0, 10.1, 10.0, 10.2, 10.1, 10.5],
            [90.0, 90.0, 95.0, 100.0, 100.0, 110.0, 180.0],
            lookback=5,
        )
        self.assertEqual(result["primary_type"], "向上放量突破")

    def test_downward_breakdown_confirmation(self) -> None:
        result = self._classify(
            [8.0, 10.5, 10.4, 10.3, 10.2, 10.1, 9.8],
            [90.0, 100.0, 95.0, 92.0, 90.0, 88.0, 170.0],
            lookback=5,
        )
        self.assertEqual(result["primary_type"], "向下放量破位")

    def test_csv_flatten_signals_delimiter(self) -> None:
        result = self._classify(
            [10.0, 11.5, 10.8, 10.9, 11.0, 11.2],
            [100.0, 260.0, 105.0, 115.0, 120.0, 240.0],
        )
        flattened = flatten_result_for_csv(result)
        self.assertIn(";", flattened["signals"])


class VolumePriceValidationTest(unittest.TestCase):
    def _write_csv(self, path: Path, headers: list[str], rows: list[list[str]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)

    def test_missing_required_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.csv"
            self._write_csv(path, ["date", "close"], [["2026-01-01", "10"]])
            with self.assertRaisesRegex(VolumePriceError, "missing required columns"):
                load_csv_input(path)

    def test_duplicate_dates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.csv"
            self._write_csv(
                path,
                ["date", "close", "volume"],
                [["2026-01-01", "10", "100"], ["2026-01-01", "11", "120"]],
            )
            with self.assertRaisesRegex(VolumePriceError, "duplicate date"):
                load_csv_input(path)

    def test_bad_date_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.csv"
            self._write_csv(path, ["date", "close", "volume"], [["2026/01/01", "10", "100"]])
            with self.assertRaisesRegex(VolumePriceError, "expected YYYY-MM-DD"):
                load_csv_input(path)

    def test_non_numeric_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.csv"
            self._write_csv(path, ["date", "close", "volume"], [["2026-01-01", "abc", "100"]])
            with self.assertRaisesRegex(VolumePriceError, "invalid close"):
                load_csv_input(path)

    def test_non_numeric_volume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.csv"
            self._write_csv(path, ["date", "close", "volume"], [["2026-01-01", "10", "abc"]])
            with self.assertRaisesRegex(VolumePriceError, "invalid volume"):
                load_csv_input(path)

    def test_missing_cell_value_reports_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.csv"
            self._write_csv(path, ["date", "close", "volume"], [["2026-01-01", "10"]])
            with self.assertRaisesRegex(VolumePriceError, "missing volume"):
                load_csv_input(path)

    def test_close_must_be_positive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.csv"
            self._write_csv(path, ["date", "close", "volume"], [["2026-01-01", "0", "100"]])
            with self.assertRaisesRegex(VolumePriceError, "close must be > 0"):
                load_csv_input(path)

    def test_volume_must_be_positive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.csv"
            self._write_csv(path, ["date", "close", "volume"], [["2026-01-01", "10", "0"]])
            with self.assertRaisesRegex(VolumePriceError, "volume must be > 0"):
                load_csv_input(path)

    def test_lookback_too_small(self) -> None:
        rows = [
            PriceVolumeRow(date=date(2026, 1, day), close=10 + day, volume=100 + day)
            for day in range(1, 7)
        ]
        with self.assertRaisesRegex(VolumePriceError, "lookback must be >= 5"):
            analyze_rows(rows, code="", name="", config=AnalyzeConfig(lookback=4))

    def test_lookback_must_be_less_than_row_count(self) -> None:
        rows = [
            PriceVolumeRow(date=date(2026, 1, day), close=10 + day, volume=100 + day)
            for day in range(1, 7)
        ]
        with self.assertRaisesRegex(VolumePriceError, "requires at least"):
            analyze_rows(rows, code="", name="", config=AnalyzeConfig(lookback=6))

    def test_unsupported_export_extension(self) -> None:
        result = {
            "code": "",
            "name": "",
            "date_range": {"start": "2026-01-01", "end": "2026-01-06"},
            "latest_date": "2026-01-06",
            "primary_type": "不明确",
            "signals": [],
            "confidence": "low",
            "metrics": {
                "latest_close": 10.0,
                "latest_volume": 100.0,
                "previous_close": 10.0,
                "latest_price_change_pct": 0.0,
                "recent_price_change_pct": 0.0,
                "prior_avg_volume": 100.0,
                "latest_volume_ratio": 1.0,
                "sideways_range_pct": 0.0,
                "position_range": "full_input",
                "position_state": "middle_area",
                "full_input_high": 10.0,
                "full_input_low": 10.0,
            },
            "interpretation": "",
            "risk_note": "",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(VolumePriceError, "unsupported export extension"):
                export_result(result, Path(temp_dir) / "out.txt")

    def test_extra_columns_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ok.csv"
            self._write_csv(
                path,
                ["date", "close", "volume", "extra", "code", "name"],
                [
                    ["2026-01-01", "10", "100", "x", "600000", "样本"],
                    ["2026-01-02", "10.1", "101", "y", "600000", "样本"],
                    ["2026-01-03", "10.2", "102", "z", "600000", "样本"],
                    ["2026-01-04", "10.3", "103", "z", "600000", "样本"],
                    ["2026-01-05", "10.4", "104", "z", "600000", "样本"],
                    ["2026-01-06", "10.5", "105", "z", "600000", "样本"],
                ],
            )
            loaded = load_csv_input(path)
            self.assertEqual(len(loaded.rows), 6)
            self.assertEqual(loaded.code, "600000")
            self.assertEqual(loaded.name, "样本")


if __name__ == "__main__":
    unittest.main()
