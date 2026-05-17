from __future__ import annotations

import asyncio
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from multiprocessing import get_context
from multiprocessing.queues import Queue
from pathlib import Path
from queue import Empty

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from aflux import __version__
from aflux.core import run_scan
from aflux.market import ALL_BOARDS
from aflux.models import (
    AuthRequest,
    AuthResponse,
    BoardInfo,
    BoardsResponse,
    HealthResponse,
    ScanResponse,
)
from aflux.settings import get_settings

TOKEN_ALGORITHM = "HS256"
security = HTTPBearer(auto_error=False)
SECURITY_DEPENDENCY = Depends(security)
SCAN_WORKER_START_METHOD = "spawn"


def create_app(
    *,
    cache_dir: str | None = None,
    source: str = "akshare",
    cors_origins: Sequence[str] | str = "*",
    rate_limit: int = 30,
    auth_rate_limit: int = 5,
    web_dir: str | None = None,
) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="aflux-cli", version=__version__)
    origins = _parse_cors_origins(cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=origins != ["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    limiter: Limiter | None = None
    if rate_limit > 0 or auth_rate_limit > 0:
        limiter = Limiter(key_func=get_remote_address)
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    def require_user(
        credentials: HTTPAuthorizationCredentials | None = SECURITY_DEPENDENCY,
    ) -> str:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            payload = jwt.decode(
                credentials.credentials,
                settings.token_secret,
                algorithms=[TOKEN_ALGORITHM],
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        subject = payload.get("sub")
        if subject != "user":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token subject.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return str(subject)

    user_dependency = Depends(require_user)

    def auth_endpoint(request: Request, body: AuthRequest) -> AuthResponse:
        _ = request
        if not secrets.compare_digest(body.code, settings.access_code):
            raise HTTPException(status_code=401, detail="Invalid access code.")
        expires_delta = timedelta(minutes=settings.token_expire_minutes)
        expires_at = datetime.now(tz=UTC) + expires_delta
        token = jwt.encode(
            {"sub": "user", "exp": expires_at},
            settings.token_secret,
            algorithm=TOKEN_ALGORITHM,
        )
        return AuthResponse(token=token, expires_in=int(expires_delta.total_seconds()))

    if limiter and auth_rate_limit > 0:
        auth_endpoint = limiter.limit(f"{auth_rate_limit}/minute")(auth_endpoint)
    app.post("/api/v1/auth", response_model=AuthResponse)(auth_endpoint)

    @app.get("/api/v1/boards", response_model=BoardsResponse)
    def boards() -> BoardsResponse:
        return BoardsResponse(
            boards=[BoardInfo(id=board, label=board.value.upper()) for board in ALL_BOARDS]
        )

    async def scan_endpoint(
        request: Request,
        volume_ratio: float = Query(50.0, ge=0),
        price_change: float = Query(2.0),
        board: str = Query("all"),
        include_st: bool = Query(False),
        no_cache: bool = Query(False),
        current_user: str = user_dependency,
    ) -> ScanResponse:
        _ = request, current_user
        try:
            return await asyncio.to_thread(
                _run_scan_with_timeout,
                timeout_seconds=settings.scan_timeout_seconds,
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
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="Scan timed out.") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    if limiter and rate_limit > 0:
        scan_endpoint = limiter.limit(f"{rate_limit}/minute")(scan_endpoint)
    app.get("/api/v1/scan", response_model=ScanResponse)(scan_endpoint)

    @app.api_route("/api", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def api_not_found(path: str = "") -> None:
        _ = path
        raise HTTPException(status_code=404, detail="API route not found.")

    _mount_web_app(app, web_dir)
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


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not _is_backend_path(path):
                return await super().get_response("index.html", scope)
            raise


def _mount_web_app(app: FastAPI, web_dir: str | None) -> None:
    directory = Path(web_dir) if web_dir else Path(__file__).resolve().parents[1] / "web" / "build"
    if not directory.is_dir():
        return
    app.mount("/", SpaStaticFiles(directory=directory, html=True), name="web")


def _is_backend_path(path: str) -> bool:
    normalized = f"/{path.lstrip('/')}"
    return normalized == "/health" or normalized.startswith("/api/")


def _run_scan_with_timeout(
    *,
    timeout_seconds: int,
    volume_ratio: float,
    price_change: float,
    boards: str,
    source: str,
    no_cache: bool,
    cache_dir: str | None,
    include_st: bool,
) -> ScanResponse:
    context = get_context(SCAN_WORKER_START_METHOD)
    queue: Queue[tuple[str, str]] = context.Queue(maxsize=1)
    process = context.Process(
        target=_scan_worker,
        kwargs={
            "queue": queue,
            "volume_ratio": volume_ratio,
            "price_change": price_change,
            "boards": boards,
            "source": source,
            "no_cache": no_cache,
            "cache_dir": cache_dir,
            "include_st": include_st,
        },
    )
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join()
        raise TimeoutError("Scan timed out.")

    try:
        message = queue.get(timeout=1)
    except Empty as exc:
        raise RuntimeError(f"Scan worker exited with code {process.exitcode}.") from exc

    if not _is_worker_message(message):
        raise RuntimeError("Scan worker returned an invalid response.")

    status_name, payload = message
    if status_name == "ok":
        return ScanResponse.model_validate_json(payload)
    if status_name == "value_error":
        raise ValueError(payload)
    raise RuntimeError(payload)


def _is_worker_message(value: object) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], str)
    )


def _scan_worker(
    *,
    queue: Queue[tuple[str, str]],
    volume_ratio: float,
    price_change: float,
    boards: str,
    source: str,
    no_cache: bool,
    cache_dir: str | None,
    include_st: bool,
) -> None:
    try:
        response = run_scan(
            volume_ratio=volume_ratio,
            price_change=price_change,
            boards=boards,
            source=source,
            no_cache=no_cache,
            cache_dir=cache_dir,
            include_st=include_st,
        )
    except ValueError as exc:
        queue.put(("value_error", str(exc)))
    except Exception as exc:
        queue.put(("error", str(exc)))
    else:
        queue.put(("ok", response.model_dump_json()))
