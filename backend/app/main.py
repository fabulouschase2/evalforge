"""EvalForge AI FastAPI application."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.base import Base, SessionLocal, engine
from app.api.routes import (
    analytics,
    api_keys,
    auth,
    client_portal,
    collection,
    datasets,
    demo,
    evaluations,
    exports,
    golden_tasks,
    media,
    misc,
    notifications,
    organizations,
    projects,
    quality,
    qualifications,
    reviews,
    rubrics,
    submissions,
    tasks,
    external,
)

logger = logging.getLogger("evalforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    env = settings.environment.strip().lower()
    if env == "production":
        # Production: never auto-create tables; require migrations to be current.
        from app.core.startup_checks import run_production_startup_checks
        run_production_startup_checks(engine)
    else:
        # Dev convenience: create tables when they don't exist. Production uses Alembic.
        Base.metadata.create_all(bind=engine)
    # v3: external API request logging + webhook delivery worker
    from app.core import api_auth
    api_auth.bind_session_factory(SessionLocal)
    from app.services import webhooks
    webhooks.start_worker(SessionLocal)
    logger.info("EvalForge AI backend ready (env=%s)", env)
    yield
    from app.services import webhooks as _wh
    _wh.stop_worker()


app = FastAPI(
    title=f"{settings.app_name} API",
    version=settings.app_version,
    description=(
        "AI evaluation and quality assurance platform. Automate objective checks, expose "
        "uncertainty, preserve human judgment, and make evaluation decisions reproducible."
    ),
    lifespan=lifespan,
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def external_api_request_log(request: Request, call_next):
    """Audit every external API call (credential, method, path, status)."""
    response = await call_next(request)
    cred_id = getattr(request.state, "api_credential_id", None)
    if cred_id is not None and request.url.path.startswith("/api/ext/"):
        from app.core import api_auth
        api_auth.log_api_request(cred_id, request.method, request.url.path, response.status_code)
    return response

for router in (auth.router, organizations.router, client_portal.router, client_portal.admin_router,
               client_portal.publish_router, projects.router, collection.router, datasets.router, rubrics.router,
               evaluations.router, reviews.router, tasks.router, submissions.router, quality.router,
               golden_tasks.router, golden_tasks.quality_router,
               qualifications.router, qualifications.grading_router, qualifications.worker_router,
               media.router, media.tasks_router, media.exports_router,
               api_keys.router, api_keys.webhook_router, external.router,
               notifications.router, exports.router, analytics.router, misc.router, demo.router):
    app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Safe error handling: never leak internals; keep messages structured.
    errors = []
    for err in exc.errors():
        errors.append({
            "field": ".".join(str(p) for p in err.get("loc", []) if p != "body"),
            "message": err.get("msg", "Invalid value."),
        })
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": errors},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. The incident has been logged."},
    )


@app.get("/api/health")
def health():
    """Readiness: database connectivity + migration state."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        migrations: dict = {"checked": False}
        if settings.environment.strip().lower() == "production":
            from app.core.startup_checks import get_head_revision, get_stored_revision
            stored = get_stored_revision(engine)
            head = get_head_revision()
            migrations = {"stored": stored, "head": head, "up_to_date": stored == head}
        return {"status": "ok", "app": settings.app_name, "version": settings.app_version,
                "environment": settings.environment, "database": "reachable", "migrations": migrations}
    except Exception:
        return {"status": "degraded", "database": "unreachable"}


@app.get("/api/health/live")
def liveness():
    """Liveness: the process is up (no database dependency)."""
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}
