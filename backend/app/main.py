import logging
import os
import re
import threading
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .cache import ImageCache
from .service import PreviewError, create_preview
from .epochs import SnapshotCache, search_metadata
from .epoch_frames import SequenceCache, select_products, create_frames, POLICY

log = logging.getLogger(__name__)


class CoordinateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    ra: Annotated[float, Field(ge=0, lt=360, description="ICRS RA in decimal degrees")]
    dec: Annotated[float, Field(ge=-90, le=90, description="ICRS Dec in decimal degrees")]
    radius_deg: Annotated[float, Field(gt=0, le=5 / 60, description="SIA search circle radius in degrees, independent of cutout size")]


class PreviewRequest(CoordinateRequest):
    cutout_profile: Literal["small", "medium"] = "small"
    detector: Annotated[int, Field(ge=1, le=6, description="SPHEREx detector; omit or null for Auto")] | None = None


class PreviewResponse(BaseModel):
    key: str
    image_url: str
    inverted_image_url: str
    expires_in_seconds: int
    metadata: dict[str, Any]


class EpochSearchRequest(CoordinateRequest):
    collections: Annotated[list[Literal["spherex_dr1", "spherex_qr3"]], Field(min_length=1, max_length=2)] = ["spherex_dr1", "spherex_qr3"]
    detectors: Annotated[list[Annotated[int, Field(ge=1, le=6)]], Field(min_length=1, max_length=6)] | None = None
    time_range_mjd: Annotated[list[float], Field(min_length=2, max_length=2)] | None = None
    limit: Annotated[int, Field(ge=1, le=200)] = 100
    cursor: Annotated[str, Field(min_length=1, max_length=160)] | None = None

    @field_validator("collections", "detectors")
    @classmethod
    def unique_filters(cls, value):
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Filters must not contain duplicates")
        return sorted(value) if value is not None else None

    @field_validator("time_range_mjd")
    @classmethod
    def ordered_time(cls, value):
        if value is not None and value[0] > value[1]:
            raise ValueError("MJD start must not exceed end")
        return value


class EpochFramesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    search_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    product_ids: Annotated[list[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]], Field(min_length=2, max_length=3)]

    @field_validator("product_ids")
    @classmethod
    def unique_products(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Select distinct products")
        return value


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
    app.state.epoch_cache = SnapshotCache()
    app.state.sequence_cache = SequenceCache()

    @app.exception_handler(PreviewError)
    async def preview_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo raw non-finite input values into JSON.
        errors = [{"loc": list(e["loc"]), "type": e["type"], "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_input", "message": "Check RA, Dec, and the search radius (radius_deg).", "details": errors}})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/preview", response_model=PreviewResponse)
    def preview(payload: PreviewRequest, request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        if not app.state.preview_lock.acquire(blocking=False):
            return JSONResponse(status_code=503, headers={"Retry-After": "5"},
                                content={"error": {"code": "busy", "message": "Image processing is busy. Retry later."}})
        try:
            options = {} if payload.detector is None else {"detector": payload.detector}
            if payload.cutout_profile != "small":
                options["cutout_profile"] = payload.cutout_profile
            black, white, metadata = create_preview(payload.ra, payload.dec, payload.radius_deg, **options)
            key = app.state.image_cache.put(black, white)
            return {"key": key,
                    "image_url": str(request.url_for("get_image", key=key)),
                    "inverted_image_url": str(request.url_for("get_image", key=key + "-inverse")),
                    "expires_in_seconds": app.state.image_cache.ttl, "metadata": metadata}
        except PreviewError:
            raise
        except Exception as exc:
            log.exception("Unexpected preview processing error")
            raise PreviewError(500, "internal_error", "Image processing failed. Retry later.") from exc
        finally:
            app.state.preview_lock.release()

    @app.get("/api/images/{key}.png", name="get_image")
    def get_image(key: str):
        if not re.fullmatch(r"[0-9a-f]{32}(?:-inverse)?", key):
            raise PreviewError(404, "image_not_found", "The image is missing or has expired. Search again.")
        image = app.state.image_cache.get(key)
        if image is None:
            raise PreviewError(404, "image_not_found", "The image is missing or has expired. Search again.")
        return Response(content=image, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/epochs/search")
    def epochs_search(payload: EpochSearchRequest):
        query = payload.model_dump(exclude={"limit", "cursor"})
        query["collections"] = sorted(query["collections"])
        cache = app.state.epoch_cache
        if payload.cursor is not None:
            snapshot, offset = cache.resume(payload.cursor, query)
            return cache.page(snapshot, offset, payload.limit)
        snapshot = cache.find(query)
        if snapshot is not None:
            return cache.page(snapshot, 0, payload.limit)
        if not app.state.preview_lock.acquire(blocking=False):
            return JSONResponse(status_code=503, headers={"Retry-After": "5"},
                                content={"error": {"code": "busy", "message": "A search or image processing task is already running. Retry later."}})
        try:
            snapshot = cache.find(query)
            if snapshot is None:
                snapshot = cache.put(search_metadata(query))
            return cache.page(snapshot, 0, payload.limit)
        except PreviewError:
            raise
        except Exception as exc:
            log.exception("Unexpected epoch metadata search error")
            raise PreviewError(500, "internal_error", "The multi-epoch metadata search failed. Retry later.") from exc
        finally:
            app.state.preview_lock.release()

    @app.post("/api/epoch-frames")
    def epoch_frames(payload: EpochFramesRequest, request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        snapshot = app.state.epoch_cache.get(payload.search_id)
        selected = select_products(snapshot, payload.product_ids)
        selection = (POLICY, payload.search_id, tuple(payload.product_ids))
        cache = app.state.sequence_cache

        def urls(result):
            return {**result, "frames": [{**frame,
                "image_url": str(request.url_for("get_epoch_artifact", sid=result["sequence_id"], name=f'{frame["index"]}.png')) if frame["status"] != "failed" else None,
                "data_url": str(request.url_for("get_epoch_artifact", sid=result["sequence_id"], name=f'{frame["index"]}.npz')) if frame["status"] != "failed" else None}
                for frame in result["frames"]]}

        result = cache.find(selection)
        if result is not None:
            return urls(result)
        if not app.state.preview_lock.acquire(blocking=False):
            return JSONResponse(status_code=503, headers={"Retry-After": "5"},
                                content={"error": {"code": "busy", "message": "Image processing is busy; retry later."}})
        try:
            result = cache.find(selection)
            if result is None:
                result, blobs = create_frames(snapshot, selected)
                result = cache.put(selection, result, blobs)
            return urls(result)
        except PreviewError:
            raise
        except Exception as exc:
            log.exception("Unexpected epoch frame error")
            raise PreviewError(500, "internal_error", "Epoch frame processing failed.") from exc
        finally:
            app.state.preview_lock.release()

    @app.get("/api/epoch-frames/{sid}/{name}", name="get_epoch_artifact")
    def get_epoch_artifact(sid: str, name: str):
        if not re.fullmatch(r"[0-9a-f]{32}",sid) or not re.fullmatch(r"[0-2]\.(png|npz)",name):
            raise PreviewError(404,"frame_not_found","Frame artifact not found or expired.")
        blob = app.state.sequence_cache.blob(sid,name)
        if blob is None:
            raise PreviewError(404,"frame_not_found","Frame artifact not found or expired.")
        return Response(blob,media_type="image/png" if name.endswith(".png") else "application/octet-stream",headers={"Cache-Control":"no-store"})

    return app


app = create_app()
