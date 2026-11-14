import logging
import os
import re
import threading
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .cache import ImageCache
from .service import PreviewError, create_preview

log = logging.getLogger(__name__)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    ra: Annotated[float, Field(ge=0, lt=360, description="ICRS RA in decimal degrees")]
    dec: Annotated[float, Field(ge=-90, le=90, description="ICRS Dec in decimal degrees")]
    radius_deg: Annotated[float, Field(gt=0, le=5 / 60, description="SIA circle radius in degrees; cutout remains 3arcmin")]


class PreviewResponse(BaseModel):
    key: str
    image_url: str
    inverted_image_url: str
    expires_in_seconds: int
    metadata: dict[str, Any]


def origins_from_env():
    origins = [o.strip() for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500,http://localhost:5173").split(",") if o.strip()]
    for origin in origins:
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query or parts.fragment or parts.username or parts.password:
            raise ValueError("CORS_ORIGINS must contain comma-separated HTTP(S) origins without paths or trailing slashes")
    return origins


def create_app():
    app = FastAPI(title="NASA SPHEREx Preview API", version="0.2.0")
    app.add_middleware(CORSMiddleware, allow_origins=origins_from_env(),
                       allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["Content-Type"], expose_headers=["Retry-After"])
    app.state.image_cache = ImageCache()
    app.state.preview_lock = threading.Lock()

    @app.exception_handler(PreviewError)
    async def preview_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo raw non-finite input values into JSON.
        errors = [{"loc": list(e["loc"]), "type": e["type"], "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_input", "message": "請檢查 RA、Dec 與 radius_deg。", "details": errors}})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/preview", response_model=PreviewResponse)
    def preview(payload: PreviewRequest, request: Request):
        if not app.state.preview_lock.acquire(blocking=False):
            return JSONResponse(status_code=503, headers={"Retry-After": "5"},
                                content={"error": {"code": "busy", "message": "影像處理中，請稍後重試。"}})
        try:
            black, white, metadata = create_preview(payload.ra, payload.dec, payload.radius_deg)
            key = app.state.image_cache.put(black, white)
            return {"key": key,
                    "image_url": str(request.url_for("get_image", key=key)),
                    "inverted_image_url": str(request.url_for("get_image", key=key + "-inverse")),
                    "expires_in_seconds": app.state.image_cache.ttl, "metadata": metadata}
        except PreviewError:
            raise
        except Exception as exc:
            log.exception("Unexpected preview processing error")
            raise PreviewError(500, "internal_error", "影像處理失敗，請稍後重試。") from exc
        finally:
            app.state.preview_lock.release()

    @app.get("/api/images/{key}.png", name="get_image")
    def get_image(key: str):
        if not re.fullmatch(r"[0-9a-f]{32}(?:-inverse)?", key):
            raise PreviewError(404, "image_not_found", "影像不存在或已到期，請重新查詢。")
        image = app.state.image_cache.get(key)
        if image is None:
            raise PreviewError(404, "image_not_found", "影像不存在或已到期，請重新查詢。")
        return Response(content=image, media_type="image/png", headers={"Cache-Control": "no-store"})

    return app


app = create_app()
