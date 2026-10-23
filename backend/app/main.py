"""FastAPI entry point with redacted errors, readiness and bounded request bodies."""

from __future__ import annotations

import os
import tempfile
import time
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.api.dashboard import router as dashboard_router
from backend.app.api.routes import router
from backend.app.core.config import Settings
from backend.app.core.logging import configure_logging
from backend.app.db.session import make_engine
from backend.app.services.application import ApplicationService
from backend.app.services.errors import ServiceError


def _error(
    scope: Scope, status: int, code: str, message: str, **extra: Any
) -> JSONResponse:
    request_id = scope.get("state", {}).get("request_id", "")
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, **extra},
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


class RequestBodyLimitMiddleware:
    """Buffer at most the configured bytes, including chunked/lengthless bodies."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        lengths = [
            value
            for key, value in scope.get("headers", [])
            if key.lower() == b"content-length"
        ]
        if lengths:
            if len(lengths) != 1 or len(lengths[0]) > 20 or not lengths[0].isdigit():
                await _error(
                    scope, 400, "invalid_content_length", "Invalid request body length"
                )(scope, receive, send)
                return
            if int(lengths[0]) > self.max_bytes:
                await _error(
                    scope,
                    413,
                    "request_too_large",
                    "Request body exceeds the configured size limit",
                )(scope, receive, send)
                return
        chunks, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                await _error(
                    scope,
                    413,
                    "request_too_large",
                    "Request body exceeds the configured size limit",
                )(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class UnexpectedErrorBoundary:
    """Keep raw application exceptions from reaching the server's error logger.

    Starlette's generic error handler re-raises after sending its response. This
    boundary sends the safe response itself, so a server cannot log the original
    exception. Once headers were sent, only a static exception escapes to let the
    server close the incomplete response; the original context is suppressed.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception:
            configure_logging().error(
                "application_error",
                extra={
                    "request_id": scope.get("state", {}).get("request_id", ""),
                    "error_code": "internal_error",
                },
            )
            if response_started:
                raise RuntimeError("Response transmission failed") from None
            try:
                await _error(
                    scope, 500, "internal_error", "An internal error occurred"
                )(scope, receive, send)
            except Exception:
                raise RuntimeError("Response transmission failed") from None


class ConfiguredRootPathMiddleware:
    """Supply the validated proxy prefix through ASGI scope.

    The reverse proxy removes this prefix before forwarding. Paths and routes
    stay unchanged while Swagger/ReDoc/OpenAPI retain their external prefix.
    """

    def __init__(self, app: ASGIApp, *, root_path: str) -> None:
        self.app, self.root_path = app, root_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.root_path and scope["type"] in {"http", "websocket"}:
            scope = {**scope, "root_path": self.root_path}
        await self.app(scope, receive, send)


class RequestLoggingMiddleware:
    """Log route templates and status, never bodies, query strings or identifiers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started, status = time.perf_counter(), 500

        async def tracked_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        finally:
            route = scope.get("route")
            method = scope.get("method", "OTHER")
            configure_logging().info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "method": (
                        method
                        if method
                        in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
                        else "OTHER"
                    ),
                    "path": getattr(route, "path", "unmatched"),
                    "status_code": status,
                    "duration_seconds": round(time.perf_counter() - started, 6),
                },
            )


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    messages = {
        "missing": "Field is required",
        "extra_forbidden": "Unexpected field",
        "json_invalid": "Malformed JSON request body",
        "literal_error": "Unsupported option",
        "string_type": "Expected a string",
        "string_pattern_mismatch": "Invalid format",
        "string_too_short": "String is shorter than allowed",
        "string_too_long": "String is longer than allowed",
        "int_type": "Expected an integer",
        "int_parsing": "Expected an integer",
        "dict_type": "Expected an object",
        "list_type": "Expected an array",
        "greater_than_equal": "Value is below the allowed range",
        "less_than_equal": "Value exceeds the allowed range",
    }
    rows = []
    for item in exc.errors():
        error_type = str(item.get("type", "invalid"))
        location = list(item.get("loc", ()))
        if error_type == "extra_forbidden":
            location = [location[0], "extra_field"] if location else ["extra_field"]
        rows.append(
            {
                "loc": location,
                "msg": messages.get(error_type, "Invalid request value"),
                "type": error_type,
            }
        )
    return rows


def create_app(settings: Settings | None = None, *, engine: Any = None) -> FastAPI:
    """Construct without connecting to PostgreSQL; failures appear in readiness."""
    configuration = settings or Settings.from_env()
    owns_engine = engine is None and bool(configuration.database_url)
    database = make_engine(configuration.database_url) if owns_engine else engine
    configure_logging()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            configuration.ensure_directories()
        except OSError:
            # Liveness remains useful when storage cannot become ready.
            pass
        yield
        if owns_engine:
            database.dispose()

    application = FastAPI(
        title="DemandIQ API",
        version="1.0.0",
        description="Single-location forecasting and assumption-driven inventory decision support. Long-running work is submitted as durable jobs.",
        lifespan=lifespan,
    )
    application.state.settings = configuration
    application.state.engine = database
    application.state.service = ApplicationService(configuration, database)

    @application.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return _error(request.scope, exc.status_code, exc.code, exc.message)

    @application.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error(
            request.scope,
            422,
            "validation_error",
            "Request validation failed",
            details=_validation_details(exc),
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        messages = {
            404: "Resource or endpoint was not found",
            405: "HTTP method is not supported",
        }
        return _error(
            request.scope,
            exc.status_code,
            "http_error",
            messages.get(exc.status_code, "The request could not be completed"),
        )

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        configure_logging().error(
            "application_error",
            extra={
                "request_id": getattr(request.state, "request_id", ""),
                "error_code": "internal_error",
            },
        )
        return _error(
            request.scope, 500, "internal_error", "An internal error occurred"
        )

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return _error(
            request.scope, 503, "database_unavailable", "The database is unavailable"
        )

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "application": "DemandIQ"}

    @application.get("/ready", tags=["system"])
    def ready() -> JSONResponse:
        try:
            if application.state.engine is None:
                raise RuntimeError
            with application.state.engine.connect() as connection:
                if connection.execute(text("SELECT 1")).scalar_one() != 1:
                    raise RuntimeError
                if (
                    connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one()
                    != "0002_application"
                ):
                    raise RuntimeError
            for directory in (configuration.data_dir, configuration.artifact_dir):
                descriptor, filename = tempfile.mkstemp(
                    prefix=".demandiq-ready-", dir=directory
                )
                os.close(descriptor)
                os.unlink(filename)
        except Exception:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return JSONResponse({"status": "ready"})

    @application.get("/config", tags=["system"])
    def public_configuration() -> dict[str, Any]:
        return {
            **configuration.safe_config(),
            "features": {
                "durable_jobs": True,
                "datasets": True,
                "training": True,
                "forecasts": True,
                "inventory_scenarios": True,
                "csv_exports": True,
            },
        }

    application.include_router(router)
    application.include_router(dashboard_router)
    application.add_middleware(
        RequestBodyLimitMiddleware, max_bytes=configuration.max_request_bytes
    )
    application.add_middleware(UnexpectedErrorBoundary)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(configuration.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key"],
        expose_headers=["Location", "X-Request-ID", "Content-Disposition"],
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(
        ConfiguredRootPathMiddleware, root_path=configuration.api_root_path
    )
    return application


app = create_app()
