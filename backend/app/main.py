import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__, scheduler
from .config import get_settings
from .notify import mqtt
from .routers import alarms, analytics, auth, devices, storage, system, users

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("smartdisk.api")

_VALIDATION_MESSAGES = {
    "missing": "obavezno polje",
    "string_too_short": "prekratka vrednost",
    "string_too_long": "predugačka vrednost",
    "too_long": "previše stavki",
    "int_parsing": "mora biti ceo broj",
    "greater_than_equal": "vrednost je premala",
    "less_than_equal": "vrednost je prevelika",
    "literal_error": "nedozvoljena vrednost",
    "bool_parsing": "mora biti da/ne",
    "json_invalid": "neispravan JSON",
}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    log.info("SmartDisk %s se pokreće", __version__)
    await scheduler.start()
    try:
        await mqtt.restart()
    except Exception:
        log.exception("MQTT veza nije pokrenuta")
    yield
    await mqtt.stop()
    scheduler.stop()


app = FastAPI(
    title="SmartDisk API",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    parts = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
        message = str(err.get("msg", ""))
        if err.get("type") == "value_error":
            message = message.removeprefix("Value error, ")
        else:
            message = _VALIDATION_MESSAGES.get(str(err.get("type")), message)
        parts.append(f"{field}: {message}" if field else message)
    return JSONResponse(status_code=422, content={"detail": "Neispravan unos – " + "; ".join(parts)})


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(devices.router)
app.include_router(system.router)
app.include_router(storage.router)
app.include_router(analytics.router)
app.include_router(alarms.router)
