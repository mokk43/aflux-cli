# Repository Guidelines

- Repo: [https://github.com/mokk43/aflux-cli.git](https://github.com/mokk43/aflux-cli.git)
- Real-time CLI and HTTP scanner for China A-share abnormal turnover and price momentum.

## Project Structure & Module Organization

- Source: `aflux/` — single Python package, flat module layout.
  - `cli.py` — Typer CLI entry point, argument parsing, progress rendering.
  - `server.py` — FastAPI HTTP server (`aflux serve`); JWT auth, scan timeout worker, SPA static mount.
  - `core.py` — Shared orchestration (`run_scan()`, `warm_cache()`); both CLI and server call into this.
  - `scanner.py` — Pure filter/calculation logic (volume-ratio, price-change).
  - `models.py` — Pydantic models shared by CLI and API (`ScanResult`, `ScanResponse`, `AuthRequest`, `AuthResponse`, `HealthResponse`, `BoardInfo`, `BoardsResponse`, etc.).
  - `settings.py` — `pydantic-settings` `BaseSettings` loading from `.env` (access code, JWT secret, token expiry, scan timeout).
  - `market.py` — Market hours, trading calendar, board classification.
  - `cache.py` — SQLite cache layer (`~/.aflux/cache/market_data.db`).
  - `output.py` — Rich table, CSV, JSON formatting.
  - `pull_daily_stock_quotes.py` — Tushare-based extractor to backfill/refresh local `daily_stock_quotes` in SQLite when online datasource calls are unavailable.
  - `refresh_stock_basic.py` — Tushare-based extractor to refresh `stock_basic` reference table in SQLite.
  - `vol_boom.py` — Local SQLite screening tool for volume-surge candidates (uses daily quotes + stock basic).
  - `hot_sectors.py` — Sector hotspot analysis script (Tushare multi-endpoint aggregation).
  - `datasource/` — Data source abstraction (Protocol-based).
    - `akshare_src.py` — AKShare implementation (primary).
    - `eastmoney_src.py` — East Money HTTP API (fallback).
  - `db_schema/` — SQLite schema SQL files for local extraction database bootstrap (`daily_stock_quotes.sql`, `stock_info.sql`).
- Frontend: `web/` — SvelteKit SPA (`adapter-static`) + Tailwind CSS v4.
  - Built output (`web/build/`) is served by FastAPI at `/` when present.
  - Dev: Vite dev server on :5173 proxies `/api` to FastAPI on :8000.
- Docs: `docs/` — Architecture documentation, web-app plan.
- Config: `pyproject.toml` — single source of truth for deps, metadata, ruff config, entry point.
- `.env.example` — template for environment variables (`AFLUX_ACCESS_CODE`, `AFLUX_TOKEN_SECRET`, etc.).
- `Makefile` — `build-web`, `dev`, `serve`, `clean` targets.

**Cross-cutting rules:**

- `core.py` is the shared brain; **never** put I/O formatting logic there.
- `cli.py` and `server.py` are thin entry points — they parse input and render output only.
- All Pydantic models live in `models.py`. **Never** define ad-hoc dicts for API responses.
- Turnover values are **always normalized to 元** at the datasource layer before caching or computation.

## API Endpoints

- `GET /health` — public, returns `HealthResponse`.
- `POST /api/v1/auth` — passcode login, returns JWT. Rate limited (default 5/min per IP).
- `GET /api/v1/boards` — public, returns available boards from `market.ALL_BOARDS`.
- `GET /api/v1/scan` — requires Bearer JWT. Runs scan in isolated worker process with timeout (default 120s). Rate limited (default 30/min per IP).
- `GET/POST/… /api/*` — catch-all returns JSON 404 for unknown API routes.
- `GET /` (and all non-API paths) — SPA static files from `web/build/` with `index.html` fallback.

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
- Run server with custom web dir: `aflux serve --web-dir web/build`
- Cache warm: `aflux cache warm -b star,chinext`
- Initialize local extraction DB schema:
  - `sqlite3 shares_stat.db < db_schema/stock_info.sql`
  - `sqlite3 shares_stat.db < db_schema/daily_stock_quotes.sql`
- Refresh stock basic data (fallback tooling): `python aflux/refresh_stock_basic.py --db shares_stat.db`
- Pull daily quotes (fallback tooling): `python aflux/pull_daily_stock_quotes.py --db shares_stat.db`
- Run local volume-surge screening: `python aflux/vol_boom.py --db shares_stat.db`
- Build frontend: `make build-web` (or `cd web && npm ci && npm run build`)
- Dev (API + frontend): `make dev`
- Clean frontend: `make clean`
- If deps are missing, run `pip install -e .` then retry once.

**Test env setup** (when tests are added):

```bash
source ~/.zshrc
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

- **Never commit:** secrets, API keys, `.env` files, real portfolio data, production cache databases.
- Config via environment: `AFLUX_ACCESS_CODE`, `AFLUX_TOKEN_SECRET`, `AFLUX_TOKEN_EXPIRE_MINUTES`, `AFLUX_SCAN_TIMEOUT_SECONDS`. See `.env.example`.
- `settings.py` loads config via `pydantic-settings`; `.env` file is read automatically.
- Auth: passcode-based login issues JWT; protected endpoints require `Authorization: Bearer <token>`.
- Cache directory: `~/.aflux/cache/` (created at runtime, not checked in).
- Placeholder convention: use obviously fake stock codes/values in docs and examples.

## Agent-Specific Notes

- Verify answers in code; do not guess API field names or AKShare function signatures.
- **Never** edit `__pycache__/`, `node_modules/`, `.svelte-kit/`, or vendored dependencies.
- AKShare API can be flaky; always handle `requests`/`httpx` exceptions gracefully.
- If AKShare/East Money endpoints are unstable or unavailable, prefer the SQLite fallback path (`shares_stat.db`) populated by `pull_daily_stock_quotes.py` and `refresh_stock_basic.py`.
- SQLite cache rows for closed trading days are immutable — never update them.
- `shares_stat.db` is a local working database and must stay git-ignored.
- The `DataSource` protocol in `datasource/__init__.py` defines the contract; new data sources must implement all three methods.
- Extraction scripts in `aflux/*.py` are operational tools; do not move their business logic into `cli.py` / `server.py`.
- When running scans during market hours (9:30-15:00 Beijing, weekdays), the realtime path is used; off-market hours use the historical path — both go through `core.run_scan()`.
- Board classification is prefix-based (e.g., `688xxx` = STAR). See `market.py` for the canonical mapping.
- Progress bars render to stderr only; stdout must remain clean for JSON/CSV output.
- Server scan endpoint runs `run_scan()` in a spawned worker process with configurable timeout; do not call `run_scan()` directly in the request handler.
- SPA mount uses `SpaStaticFiles` subclass that falls back to `index.html` for non-API, non-health paths.
