from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from aflux import __version__
from aflux.core import run_scan
from aflux.models import ScanResponse


def create_app(
    *,
    cache_dir: str | None = None,
    source: str = "akshare",
    cors_origins: Sequence[str] | str = "*",
    rate_limit: int = 30,
) -> FastAPI:
    app = FastAPI(title="aflux-cli", version=__version__)
    origins = _parse_cors_origins(cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=origins != ["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    limiter: Limiter | None = None
    if rate_limit > 0:
        limiter = Limiter(key_func=get_remote_address)
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    def scan_endpoint(
        request: Request,
        volume_ratio: float = Query(50.0, ge=0),
        price_change: float = Query(2.0),
        board: str = Query("all"),
        include_st: bool = Query(False),
        no_cache: bool = Query(False),
    ) -> ScanResponse:
        _ = request
        try:
            return run_scan(
                volume_ratio=volume_ratio,
                price_change=price_change,
                boards=board,
                source=source,
                no_cache=no_cache,
                cache_dir=cache_dir,
                include_st=include_st,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    if limiter:
        scan_endpoint = limiter.limit(f"{rate_limit}/minute")(scan_endpoint)
    app.get("/api/v1/scan", response_model=ScanResponse)(scan_endpoint)
    return app


def _parse_cors_origins(cors_origins: Sequence[str] | str) -> list[str]:
    if isinstance(cors_origins, str):
        items = [item.strip() for item in cors_origins.split(",") if item.strip()]
    else:
        items = [str(item).strip() for item in cors_origins if str(item).strip()]
    return items or ["*"]


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    _ = request
    return JSONResponse(status_code=429, content={"detail": str(exc)})
