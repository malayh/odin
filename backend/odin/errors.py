"""Unified API error model and exception handlers."""

import logging
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from odin.logging import get_request_id

log = logging.getLogger("odin")


class OdinError(Exception):
    status: int = 500
    type: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(OdinError):
    status = 422
    type = "validation_error"


class AuthError(OdinError):
    status = 401
    type = "auth_error"


class ForbiddenError(OdinError):
    status = 403
    type = "forbidden"


class NotFoundError(OdinError):
    status = 404
    type = "not_found"


class ConflictError(OdinError):
    status = 409
    type = "conflict"


def _envelope(type_: str, message: str) -> dict:
    return {"error": {"type": type_, "message": message, "request_id": get_request_id()}}


async def odin_error_handler(request: Request, exc: Exception) -> JSONResponse:
    err = cast(OdinError, exc)
    if err.status >= 500:
        log.exception("odin_error type=%s", err.type)
    return JSONResponse(status_code=err.status, content=_envelope(err.type, err.message))


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error")
    return JSONResponse(
        status_code=500,
        content=_envelope("internal_error", "internal server error"),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OdinError, odin_error_handler)
    app.add_exception_handler(Exception, unhandled_handler)
