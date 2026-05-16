from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeRemainingColumn

from aflux.core import ProgressCallback, run_scan, warm_cache
from aflux.models import OutputFormat
from aflux.output import export_response, render_table, write_csv, write_json

app = typer.Typer(no_args_is_help=True)
cache_app = typer.Typer(no_args_is_help=True)
app.add_typer(cache_app, name="cache")

stderr_console = Console(stderr=True)


@app.command()
def scan(
    volume_ratio: float = typer.Option(
        50.0,
        "--volume-ratio",
        "-v",
        help="Min current_turnover / prev_turnover * 100.",
    ),
    price_change: float = typer.Option(
        2.0,
        "--price-change",
        "-p",
        help="Min price change percentage versus previous close.",
    ),
    board: str = typer.Option(
        "all",
        "--board",
        "-b",
        help="Comma-separated boards: star,chinext,sme,main,bse.",
    ),
    output_format: str = typer.Option(
        OutputFormat.AUTO.value,
        "--format",
        "-f",
        help="Output format: auto, table, csv, json.",
    ),
    export: Path | None = typer.Option(
        None,
        "--export",
        "-e",
        help="Export results to CSV or JSON. Format is inferred from extension.",
    ),
    source: str = typer.Option(
        "akshare",
        "--source",
        "-s",
        help="Data source: akshare or eastmoney.",
    ),
    cache_dir: Path | None = typer.Option(
        None,
        "--cache-dir",
        help="SQLite cache directory.",
    ),
    include_st: bool = typer.Option(
        False,
        "--include-st",
        help="Include ST/*ST stocks.",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Skip cache and force fresh downloads.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Show debug logging.",
    ),
) -> None:
    requested_fmt = _parse_output_format(output_format)
    fmt = _resolve_output_format(requested_fmt)
    show_progress = fmt == OutputFormat.TABLE and sys.stdout.isatty()

    try:
        with _progress(show_progress) as progress_callback:
            response = run_scan(
                volume_ratio=volume_ratio,
                price_change=price_change,
                boards=board,
                source=source,
                no_cache=no_cache,
                cache_dir=str(cache_dir) if cache_dir else None,
                include_st=include_st,
                progress_callback=progress_callback,
            )
        if export:
            export_format = (
                None
                if requested_fmt in {OutputFormat.AUTO, OutputFormat.TABLE}
                else requested_fmt.value
            )
            export_response(
                response,
                export,
                export_format,
            )
        _emit_scan_response(response, fmt)
    except Exception as exc:
        _handle_error(exc, fmt=fmt, verbose=verbose)


@cache_app.command("warm")
def cache_warm(
    date_: str | None = typer.Option(
        None,
        "--date",
        help="Date to warm, YYYY-MM-DD. Defaults to latest completed trading day.",
    ),
    board: str = typer.Option(
        "all",
        "--board",
        "-b",
        help="Comma-separated boards: star,chinext,sme,main,bse.",
    ),
    source: str = typer.Option(
        "akshare",
        "--source",
        "-s",
        help="Data source: akshare or eastmoney.",
    ),
    cache_dir: Path | None = typer.Option(
        None,
        "--cache-dir",
        help="SQLite cache directory.",
    ),
) -> None:
    try:
        with _progress(sys.stderr.isatty()) as progress_callback:
            count = warm_cache(
                trading_date=date_,
                boards=board,
                source=source,
                cache_dir=str(cache_dir) if cache_dir else None,
                progress_callback=progress_callback,
            )
        stderr_console.print(f"Warmed {count} daily bars.")
    except Exception as exc:
        _handle_error(exc, fmt=OutputFormat.TABLE, verbose=False)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(8000, "--port", help="Bind port."),
    cors_origin: str = typer.Option(
        "*",
        "--cors-origin",
        help="Allowed CORS origins, comma-separated.",
    ),
    cache_dir: Path | None = typer.Option(
        None,
        "--cache-dir",
        help="SQLite cache directory.",
    ),
    source: str = typer.Option(
        "akshare",
        "--source",
        "-s",
        help="Data source: akshare or eastmoney.",
    ),
    rate_limit: int = typer.Option(
        30,
        "--rate-limit",
        help="Max requests per minute per IP. Use 0 to disable.",
    ),
) -> None:
    import uvicorn

    from aflux.server import create_app

    server_app = create_app(
        cache_dir=str(cache_dir) if cache_dir else None,
        source=source,
        cors_origins=cors_origin,
        rate_limit=rate_limit,
    )
    uvicorn.run(server_app, host=host, port=port)


def _emit_scan_response(response, fmt: OutputFormat) -> None:
    if fmt == OutputFormat.JSON:
        write_json(response)
    elif fmt == OutputFormat.CSV:
        write_csv(response)
    else:
        render_table(response)


def _parse_output_format(value: str) -> OutputFormat:
    try:
        return OutputFormat(value.lower())
    except ValueError as exc:
        valid = ", ".join(item.value for item in OutputFormat)
        raise ValueError(f"Unsupported output format '{value}'. Valid formats: {valid}") from exc


def _resolve_output_format(requested: OutputFormat) -> OutputFormat:
    if requested == OutputFormat.AUTO:
        return OutputFormat.TABLE if sys.stdout.isatty() else OutputFormat.JSON
    return requested


def _handle_error(exc: Exception, fmt: OutputFormat, verbose: bool) -> None:
    if verbose:
        stderr_console.print_exception()
    elif fmt == OutputFormat.JSON:
        typer.echo(json.dumps({"error": str(exc)}, ensure_ascii=False), err=True)
    else:
        stderr_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(1)


class _progress:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.progress: Progress | None = None
        self.task_id: TaskID | None = None

    def __enter__(self) -> ProgressCallback | None:
        if not self.enabled:
            return None
        self.progress = Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=stderr_console,
            transient=True,
        )
        self.progress.__enter__()
        return self.update

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.progress:
            self.progress.__exit__(exc_type, exc, traceback)

    def update(self, completed: int, total: int, code: str) -> None:
        if not self.progress or total <= 0:
            return
        if self.task_id is None:
            self.task_id = self.progress.add_task("Fetching daily bars", total=total)
        self.progress.update(
            self.task_id,
            completed=completed,
            description=f"Fetching {code}",
        )


if __name__ == "__main__":
    app()
