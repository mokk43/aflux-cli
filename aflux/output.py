from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import TextIO

from rich.console import Console
from rich.table import Table

from aflux.models import ScanResponse


CSV_FIELDS = [
    "code",
    "name",
    "price",
    "price_change_pct",
    "volume_ratio_pct",
    "turnover",
    "prev_turnover",
    "board",
]


def format_turnover(value: float) -> str:
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.0f}"


def render_table(response: ScanResponse, console: Console | None = None) -> None:
    console = console or Console()
    table = Table(title=f"A-Share Scan Results ({response.count})")
    table.add_column("Code", style="cyan", no_wrap=True)
    table.add_column("Name", no_wrap=True)
    table.add_column("Board", no_wrap=True)
    table.add_column("Price", justify="right")
    table.add_column("Change%", justify="right")
    table.add_column("VolumeRatio%", justify="right")
    table.add_column("Turnover", justify="right")

    for item in response.results:
        table.add_row(
            item.code,
            item.name,
            str(item.board or ""),
            f"{item.price:.2f}",
            f"{item.price_change_pct:.2f}",
            f"{item.volume_ratio_pct:.2f}",
            format_turnover(item.turnover),
        )

    console.print(table)


def write_json(response: ScanResponse, file: TextIO | None = None) -> None:
    file = file or sys.stdout
    file.write(response.model_dump_json(indent=2))
    file.write("\n")


def write_csv(response: ScanResponse, file: TextIO | None = None) -> None:
    file = file or sys.stdout
    writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for item in response.results:
        writer.writerow(item.model_dump(mode="json"))


def export_response(response: ScanResponse, export_path: str | Path, output_format: str | None = None) -> None:
    path = Path(export_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = (output_format or path.suffix.lstrip(".")).lower()
    if fmt not in {"json", "csv"}:
        raise ValueError("Export format must be json or csv.")

    with path.open("w", encoding="utf-8", newline="") as file:
        if fmt == "json":
            payload = json.loads(response.model_dump_json())
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        else:
            write_csv(response, file)
