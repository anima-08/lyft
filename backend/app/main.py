import hashlib
import logging
import sqlite3
import threading
from contextlib import asynccontextmanager
from time import perf_counter

import litellm
from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .database import Database
from .failover import parse_failure_header
from .llm_gateway import AllProvidersUnavailable, LLMGateway
from .schemas import ChatRequest, ChatResponse, HealthResponse, HistoryResponse, SessionId

logger = logging.getLogger(__name__)
SESSION_LOCKS = tuple(threading.Lock() for _ in range(256))


def session_lock(session_id: str) -> threading.Lock:
    digest = hashlib.sha256(session_id.encode("utf-8")).digest()
    return SESSION_LOCKS[digest[0]]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_runtime()

    litellm.telemetry = False
    litellm.suppress_debug_info = True

    database = Database(settings)
    gateway = LLMGateway(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        application.state.cache_enabled = gateway.configure_cache()
        yield

    application = FastAPI(
        title="Lyftr AI API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.database = database
    application.state.gateway = gateway
    application.state.cache_enabled = False
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        details = [
            {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content=jsonable_encoder({"detail": details}))

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @application.exception_handler(sqlite3.Error)
    async def database_exception_handler(request: Request, exc: sqlite3.Error):
        logger.error("Database operation failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled request error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    @application.get("/health", response_model=HealthResponse)
    def health():
        if not database.is_reachable():
            raise HTTPException(status_code=503, detail="database unavailable")
        if not settings.llm_api_keys or not application.state.cache_enabled:
            raise HTTPException(status_code=503, detail="service is not ready")
        return HealthResponse(
            status="ok",
            keys_configured=len(settings.llm_api_keys),
            cache_enabled=application.state.cache_enabled,
        )

    @application.post("/chat", response_model=ChatResponse)
    def chat(payload: ChatRequest, request: Request):
        started_at = perf_counter()
        simulation_header = request.headers.get("X-Simulate-Failure")
        key_ids = [f"key_{index}" for index in range(1, len(settings.llm_api_keys) + 1)]
        try:
            simulated_failures = parse_failure_header(
                simulation_header, key_ids, settings.enable_failure_simulation
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with session_lock(payload.session_id):
            stored_prompt = database.get_session_prompt(payload.session_id)
            history = database.get_messages(payload.session_id)
            system_prompt = payload.system_prompt or stored_prompt or settings.default_system_prompt
            messages = [
                {"role": "system", "content": system_prompt},
                *({"role": item["role"], "content": item["content"]} for item in history),
                {"role": "user", "content": payload.message},
            ]

            try:
                result = gateway.complete(messages, simulated_failures)
            except AllProvidersUnavailable as exc:
                raise HTTPException(status_code=503, detail="all providers unavailable") from exc

            latency_ms = max(0, round((perf_counter() - started_at) * 1000))
            metadata = {
                "resolution_source": result.resolution_source,
                "model": result.model,
                "latency_ms": latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "key_id": result.key_id,
                "fallback_attempts": result.fallback_attempts,
            }
            database.save_exchange(
                payload.session_id,
                system_prompt,
                payload.message,
                result.reply,
                metadata,
            )

        return ChatResponse(session_id=payload.session_id, reply=result.reply, metadata=metadata)

    @application.get("/sessions/{session_id}/messages", response_model=HistoryResponse, response_model_exclude_none=True)
    def session_messages(session_id: SessionId = Path(...)):
        with session_lock(session_id):
            if not database.session_exists(session_id):
                raise HTTPException(status_code=404, detail="session not found")
            messages = database.get_messages(session_id)
        return HistoryResponse(session_id=session_id, messages=messages)

    return application


app = create_app()
