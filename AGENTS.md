# Repository Guidelines

- Repo: https://github.com/mokk43/aflux-cli.git
- Real-time CLI and HTTP scanner for China A-share abnormal turnover and price momentum.

## Project Structure & Module Organization

- Source: `aflux/` — single Python package, flat module layout.
  - `cli.py` — Typer CLI entry point, argument parsing, progress rendering.
  - `server.py` — FastAPI HTTP server (`aflux serve`).
  - `core.py` — Shared orchestration (`run_scan()`, `warm_cache()`); both CLI and server call into this.
  - `scanner.py` — Pure filter/calculation logic (volume-ratio, price-change).
  - `models.py` — Pydantic models shared by CLI and API (`ScanResult`, `ScanResponse`, etc.).
  - `market.py` — Market hours, trading calendar, board classification.
  - `cache.py` — SQLite cache layer (`~/.aflux/cache/market_data.db`).
  - `output.py` — Rich table, CSV, JSON formatting.
  - `datasource/` — Data source abstraction (Protocol-based).
    - `akshare_src.py` — AKShare implementation (primary).
    - `eastmoney_src.py` — East Money HTTP API (fallback).
- Docs: `docs/` — Architecture documentation.
- Config: `pyproject.toml` — single source of truth for deps, metadata, ruff config, entry point.

**Cross-cutting rules:**
- `core.py` is the shared brain; **never** put I/O formatting logic there.
- `cli.py` and `server.py` are thin entry points — they parse input and render output only.
- All Pydantic models live in `models.py`. **Never** define ad-hoc dicts for API responses.
- Turnover values are **always normalized to 元** at the datasource layer before caching or computation.

## Documentation Conventions

- Architecture docs live in `docs/architecture.md`.
- Internal links: root-relative paths.
- Domain vocabulary:
  - "turnover" = 成交额 (in 元, not 成交量/shares).
  - "volume ratio" = `current_turnover / prev_turnover * 100` (percentage).
  - "board" = market segment (STAR/ChiNext/SME/Main/BSE).

## Build, Test, and Development Commands

- Runtime: **Python 3.11+**
- Build system: Hatchling (`hatchling.build`)
- Package manager: pip (no lockfile; deps listed in `pyproject.toml`)
- Install (editable): `pip install -e .`
- Install (production): `pip install .`
- Lint: `ruff check aflux/`
- Lint fix: `ruff check --fix aflux/`
- Format check: `ruff format --check aflux/`
- Format fix: `ruff format aflux/`
- Run CLI: `aflux scan -v 80 -p 3 -b star,chinext`
- Run server: `aflux serve --port 8000`
- Cache warm: `aflux cache warm -b star,chinext`
- If deps are missing, run `pip install -e .` then retry once.

**Test env setup** (when tests are added):
```bash
source ~/workspace/buildingai/bin/activate
```

## Coding Style & Naming Conventions

- Language: **Python 3.11+** with `from __future__ import annotations`.
- Formatting: ruff format (`ruff format aflux/`), line-length 100.
- Linting: ruff (`ruff check aflux/`), rules: E, F, I, UP, B.
- Typing: use type hints everywhere; prefer `X | None` over `Optional[X]`.
- File size: keep modules under ~300 LOC; split when it improves clarity.
- Naming:
  - Modules: `snake_case.py`
  - Classes: `PascalCase` (Pydantic models, Typer apps)
  - Functions/vars: `snake_case`
  - CLI flags: `--kebab-case`
  - Board names in code: lowercase (`star`, `chinext`, `sme`, `main`, `bse`)
- Comments: brief comments for tricky logic only; docstrings on public functions.
- Anti-patterns:
  - **Never** use `Any` type without explicit justification.
  - **Never** put business logic in `cli.py` or `server.py` — delegate to `core.py`.
  - **Never** return raw dicts from scan functions — use Pydantic models.
  - **Never** mix stdout diagnostic output with JSON data — diagnostics go to stderr.
  - **Never** hardcode turnover units — normalize to 元 at the datasource boundary.

## Commit & Pull Request Guidelines

- Message style: concise, action-oriented (e.g., "add cache warm command", "fix off-market date resolution").
- Grouping: related changes together; no bundled unrelated refactors.

## Security & Configuration

- **Never commit:** secrets, API keys, real portfolio data, production cache databases.
- Cache directory: `~/.aflux/cache/` (created at runtime, not checked in).
- Environment variables: none required for basic operation; data sources use public APIs.
- Placeholder convention: use obviously fake stock codes/values in docs and examples.

## Agent-Specific Notes

- Verify answers in code; do not guess API field names or AKShare function signatures.
- **Never** edit `__pycache__/` or vendored dependencies.
- AKShare API can be flaky; always handle `requests`/`httpx` exceptions gracefully.
- SQLite cache rows for closed trading days are immutable — never update them.
- The `DataSource` protocol in `datasource/__init__.py` defines the contract; new data sources must implement all three methods.
- When running scans during market hours (9:30-15:00 Beijing, weekdays), the realtime path is used; off-market hours use the historical path — both go through `core.run_scan()`.
- Board classification is prefix-based (e.g., `688xxx` = STAR). See `market.py` for the canonical mapping.
- Progress bars render to stderr only; stdout must remain clean for JSON/CSV output.
