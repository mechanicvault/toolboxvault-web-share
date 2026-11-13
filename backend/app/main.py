"""Application factory.

This module does exactly one job: create the FastAPI app and wire in the
module routers collected from the module registry. It must stay small.
All domain logic lives in app/modules/<name>/; all universal concerns live
in app/core/.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.modules.billing.admin_routes import router as billing_admin_router
from app.modules.core.admin_announcements import (
    router as announcements_admin_router,
)
from app.modules.core.admin_routes import router as core_admin_router
from app.modules.core.insurer_admin_routes import (
    router as insurer_admin_router,
)
from app.modules.core.roadmap_routes import (
    admin_router as roadmap_admin_router,
)
from app.modules.core.roadmap_routes import (
    public_router as roadmap_public_router,
)
from app.modules.core.module_routes import admin_router
from app.modules.dealers.admin_routes import router as dealers_admin_router
from app.modules.support.routes import admin_router as support_admin_router
from app.modules.dealers.routes import public_router as dealers_public_router
from app.modules.registry import iter_enabled_modules, validate_feature_modules

logger = logging.getLogger(__name__)


def _sanitize_validation_errors(value):
    """Recursively render validation-error details JSON-safe,
    preserving the {type, loc, msg, input, ...} shape: bytes are
    decoded with replacement characters (the raw body may not be
    UTF-8 — that is exactly the D-06 crash), tuples become lists,
    and anything else unserializable is stringified."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): _sanitize_validation_errors(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_validation_errors(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def create_app() -> FastAPI:
    # Fail closed: the shipped default jwt_secret is public knowledge (it is
    # printed in config.py). Booting with it would let anyone forge tokens
    # for any account, so refuse to start until a real secret is configured.
    if settings.jwt_secret == "change-me":
        raise RuntimeError(
            "JWT_SECRET is still the default 'change-me' value. "
            "Set a real JWT_SECRET in the environment/.env before starting."
        )

    # Module-graph validation (module doctrine, owner 2026-10-18):
    # a broken feature graph — unknown dependency, cycle — is LOUD
    # here and in the operator matrix, and the offending modules are
    # blocked by the control service, but it never stops the site
    # from booting. The rest of the system keeps serving.
    for problem in validate_feature_modules():
        logger.error("Module graph problem: %s", problem)

    app = FastAPI(title="Toolbox Vault API", version="0.1.0")

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """The house 422, hardened (deep audit round 2, D-06):
        FastAPI's default handler json-encodes the error details,
        whose `input` can embed the RAW REQUEST BODY — a malformed
        multipart body posted to a JSON endpoint carries bytes
        that are not valid UTF-8, the encoder crashed on them, and
        the client got a 500 instead of the 422. Here the default
        encoding runs first, so every currently-working 422 body
        stays byte-identical; only when encoding itself fails do
        we fall back to a sanitized rendering of the same shape
        (bytes decoded lossily, anything unserializable stringified).
        A validation failure must never surface as a 500."""
        try:
            detail = jsonable_encoder(exc.errors())
        except Exception:
            detail = _sanitize_validation_errors(exc.errors())
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in iter_enabled_modules():
        app.include_router(
            module.router,
            prefix=module.route_prefix,
            tags=[module.name],
        )

    # Operator surface (module control). Not a registry module: it is
    # part of core's plumbing, mounted at its own prefix.
    app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
    # Core's panel surface (users, bans, settings, audit) shares it.
    app.include_router(core_admin_router, prefix="/api/admin", tags=["admin"])
    # Billing's operator surface (codes, grants) shares the prefix.
    app.include_router(billing_admin_router, prefix="/api/admin", tags=["admin"])
    # Dealers' operator surface (the directory) shares the prefix.
    app.include_router(dealers_admin_router, prefix="/api/admin", tags=["admin"])
    # Insurers' operator surface (directory + affiliation
    # verification, wave 3) shares the prefix.
    app.include_router(insurer_admin_router, prefix="/api/admin", tags=["admin"])
    app.include_router(roadmap_admin_router, prefix="/api/admin", tags=["admin"])
    # Feature announcements (release machinery, 2026-11-08): the
    # composer + history share the prefix; their gate is the
    # user-manager rung (god + moderator admin), enforced per
    # route inside the router.
    app.include_router(
        announcements_admin_router, prefix="/api/admin", tags=["admin"]
    )
    # Support desk (support module): the operator face of the
    # ticket system shares the prefix.
    app.include_router(support_admin_router, prefix="/api/admin", tags=["admin"])
    app.include_router(
        roadmap_public_router, prefix="/api/core", tags=["core"]
    )
    # Dealers' anonymous window (Find-an-Agent public twin): NOT
    # behind the module gate or auth — read-only by construction.
    app.include_router(
        dealers_public_router, prefix="/api/dealers/public", tags=["dealers"]
    )

    return app


app = create_app()
