# Project Filetree

_Auto-maintained by `/filetree:update`. Each entry carries a content hash; mismatched hashes indicate stale summaries._

## (root)/

- `.env.example` — Template for required environment variables: access code, JWT secret, token expiry, and scan timeout. <!--hash:c81c558f-->
- `.gitignore` — Standard Python gitignore excluding bytecode, builds, env files, cache dirs, SQLite databases, and IDE artifacts. <!--hash:78d3dc16-->
- `AGENTS.md` — Complete repository guidelines for AI agents: project structure, conventions, API endpoints, commands, and security rules. <!--hash:4257d6fc-->
- `CLAUDE.md` — Complete repository guidelines for AI agents: project structure, conventions, API endpoints, commands, and security rules. <!--hash:4257d6fc-->
- `LICENSE` — Apache License 2.0 full legal text governing use, reproduction, and distribution of the project. <!--hash:261eeb9e-->
- `Makefile` — Convenience targets: frontend build (npm ci + build), dev server with API proxying, production serve, and cleanup. <!--hash:e7217d80-->
- `README.md` — Project tagline: real-time Python CLI scanner for China A-share abnormal volume and price momentum. <!--hash:a3ae0754-->
- `pyproject.toml` — Project metadata, dependencies, build system configuration, and linting rules for the aflux-cli package. <!--hash:bfb8c60d-->

## aflux/

- `.gitignore` — Package-level gitignore excluding CSV files and an architecture review HTML artifact. <!--hash:59036a04-->
- `__init__.py` — Package init declaring version 0.1.0 for the A-share turnover and momentum scanner package. <!--hash:475cbad4-->
- `cache.py` — SQLite cache layer for daily bars, realtime snapshots, and trading calendar; stores data under ~/.aflux/cache. <!--hash:1f589fbd-->
- `cli.py` — Typer CLI entry point; defines scan, cache-warm, and serve commands with argument parsing and output dispatch. <!--hash:cf3c224b-->
- `core.py` — Shared orchestration for the scan pipeline and cache warming; delegates to datasource, cache, and scanner modules. <!--hash:36f2af6d-->
- `hot_sectors.py` — Standalone sector hotspot analysis script; aggregates Tushare data into a Markdown research brief. <!--hash:062636df-->
- `market.py` — Market calendar and board classification utilities; detects market phase, maps code prefixes to boards, and resolves trading dates. <!--hash:1597ecc0-->
- `models.py` — Pydantic models and enumerations for boards, market phases, scan results, API request/response schemas, and stock snapshots. <!--hash:8bbe7b09-->
- `output.py` — Output formatting for scan results as Rich tables, CSV, or JSON to stdout or export files. <!--hash:1fa7423c-->
- `pull_daily_stock_quotes.py` — Tushare-based script to pull daily stock quotes into a SQLite table with date resolution and retry logic. <!--hash:dfcad559-->
- `refresh_stock_basic.py` — Fetches A-share stock basic info from Tushare Pro and refreshes the local SQLite stock_basic reference table. <!--hash:49039b84-->
- `scanner.py` — Pure filter and calculation logic for the volume-ratio and price-change two-stage scan pipeline. <!--hash:c377b5ad-->
- `server.py` — FastAPI HTTP server providing JWT-auth endpoints, scan worker with timeout, rate limiting, and SPA static file serving. <!--hash:9d2e5867-->
- `settings.py` — Loads runtime configuration (access code, JWT secret, timeouts) from environment variables and .env via pydantic-settings. <!--hash:9901614f-->
- `vol_boom.py` — Local SQLite screening tool that finds volume-surge candidates by comparing daily quotes across two trading days. <!--hash:de6e9468-->
- `volume_price.py` — Standalone CLI analyzer that classifies volume-price relationship patterns from a single stock's local CSV history. <!--hash:0583dc95-->

## aflux/datasource/

- `__init__.py` — DataSource protocol definition and factory; specifies the contract for snapshot, daily bars, and trading calendar fetching. <!--hash:5adf88cc-->
- `akshare_src.py` — AKShare datasource implementation; fetches realtime snapshots, daily bars, and trading calendars via the AKShare library. <!--hash:dd8d6875-->
- `eastmoney_src.py` — East Money realtime snapshot source with retry logic; delegates historical daily bars and calendar to AKShare. <!--hash:96afd589-->

## db_schema/

- `daily_stock_quotes.sql` — SQL schema defining the daily_stock_quotes table for A-share OHLCV daily bar data with indexes. <!--hash:2e97fa92-->
- `stock_info.sql` — SQL schema defining the stock_basic reference table for Tushare stock metadata with lookup indexes. <!--hash:7b7daa2a-->

## docs/

- `Volume–Price Relationship CLI Analyzer.md` — PRD specifying the standalone volume-price classifier: classification rules, CLI interface, and output schema. <!--hash:67907124-->
- `architecture.md` — High-level architecture documentation covering project layout, layered design, data flow pipelines, and key decisions. <!--hash:cf04157d-->
- `volume–price-relationship.md` — Reference guide for classic volume-price relationship patterns in A-shares, covering trends, consolidations, and breakout signals. <!--hash:d610c5c5-->
- `web-app-plan.md` — Three-phase plan for the aflux web application: SvelteKit SPA, FastAPI backend, auth, scan dashboard, and PWA. <!--hash:9c9be19f-->

## examples/

- `volume_price_sample.csv` — Sample CSV input for the volume-price relationship analyzer with daily price and volume data. <!--hash:478e89fa-->

## tests/

- `test_volume_price.py` — Unit tests for volume-price pattern classification logic and CSV input validation. <!--hash:e1a67309-->

## web/

- `package.json` — Node.js package manifest for the SvelteKit frontend with Vite, Tailwind CSS, and TypeScript tooling. <!--hash:3d6cf5d6-->
- `svelte.config.js` — SvelteKit build configuration; sets static adapter to output into build/ directory with index.html fallback. <!--hash:fede5485-->
- `tsconfig.json` — TypeScript project configuration; extends SvelteKit defaults with strict mode, bundler resolution, and source maps. <!--hash:43447105-->
- `vite.config.ts` — Vite dev server configuration; enables Tailwind CSS and SvelteKit plugins and proxies /api and /health to backend on :8000. <!--hash:f7360972-->

## web/src/

- `app.css` — Global stylesheet with Tailwind CSS imports, dark mode support, and base typography for the SPA. <!--hash:1b25e9a0-->
- `app.d.ts` — TypeScript ambient declarations for the SvelteKit App namespace with extendable type interfaces. <!--hash:1975813f-->
- `app.html` — Root HTML shell for the SvelteKit SPA with viewport meta, PWA manifest link, and favicon. <!--hash:766d0f20-->

## web/src/routes/

- `+layout.svelte` — Root SvelteKit layout with auth guard, dark/light theme toggle, offline banner, and service worker registration. <!--hash:e3ae036a-->
- `+layout.ts` — Root SvelteKit layout config; enables static prerendering and disables server-side rendering for SPA mode. <!--hash:ceccaaf6-->
- `+page.svelte` — Login page; collects passcode via form, authenticates against the API, and redirects to /scan on success. <!--hash:98c90cbb-->

## web/src/routes/scan/

- `+page.svelte` — Main scan dashboard; renders filter sidebar, status bar, sortable results table with mobile cards, auto-refresh, and CSV/JSON export. <!--hash:3746bf02-->

## web/static/

- `manifest.json` — PWA web app manifest; declares app name, standalone display mode, theme/background colors, and favicon icon. <!--hash:5c03faab-->
- `service-worker.js` — PWA service worker; precaches shell assets on install and serves cached fallback for non-API requests when offline. <!--hash:3a8c9f31-->
