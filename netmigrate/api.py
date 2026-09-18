"""
FastAPI application for the NetMigrate web layer (docs/web-layer-spec.md
section 3). All eight endpoint groups live here.

Boundary rules, both from CLAUDE.md section 4 (the API contract) and from
this module's own brief:

* The engine is reached only through ``netmigrate.engine.convert`` and the
  ``.to_dict()`` method its result carries. No other name is imported from
  ``netmigrate.engine`` -- not ``VendorNotSupported``, not the parser/
  renderer registry. A conversion failure is therefore caught as a plain
  ``Exception`` rather than that specific type; the engine is frozen and
  both vendor directions are fully registered, so in practice this only
  fires on a genuinely unsupported request.
* ``Vendor`` is imported from ``netmigrate.ir`` because CLAUDE.md's own
  contract example does exactly that -- it is a plain string enum, not one
  of the IR dataclasses (DeviceConfig, Interface, ...) the web layer must
  stay away from. No dataclass from ``netmigrate.ir`` is imported here.
* Vendor auto-detection reuses ``tools.demo.detect_vendor`` rather than
  re-implementing the marker-counting logic a second time (spec section 6).
"""

from __future__ import annotations

import io
import json
import os
import sys
import uuid
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterator, Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from netmigrate import ai_fallback, deploy_sim, persistence, rule_catalog
from netmigrate.engine import convert
from netmigrate.ir import Vendor

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.demo import detect_vendor  # noqa: E402 -- reused, not reimplemented

_TEMPLATES_DIR = _ROOT / "templates"
_STATIC_DIR = _ROOT / "static"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# spec section 4: route -> template. Every page is a bare Jinja2 shell with
# no server-side context beyond `request` (base.html uses it only to
# highlight the active nav item) -- all data is fetched client-side.
_PAGE_ROUTES: dict[str, str] = {
    "/": "index.html",
    "/batch": "batch.html",
    "/devices": "devices.html",
    "/deploy": "deploy.html",
    "/dashboard": "dashboard.html",
    "/history": "history.html",
    "/settings": "settings.html",
}

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

SHORT_TO_VENDOR: dict[str, Vendor] = {"cisco": Vendor.CISCO, "huawei": Vendor.HUAWEI}
VENDOR_TO_SHORT: dict[Vendor, str] = {v: k for k, v in SHORT_TO_VENDOR.items()}

ALLOWED_BATCH_EXTENSIONS = {".cfg", ".txt", ".conf"}
MAX_BATCH_FILES = 20
MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MB, spec 3.2

# Applies to JSON request bodies only (spec section 5). The batch endpoint
# has its own, larger, explicit per-file/per-count limits (spec 3.2) that a
# blanket 2 MB body cap would contradict, so this check is scoped to
# application/json requests rather than every request.
MAX_JSON_BODY_BYTES = 2 * 1024 * 1024

MAX_BATCHES = 50  # spec 3.3: process-level dict, need not survive restart


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _resolve_vendor(code: str, text: Optional[str] = None) -> Vendor:
    """Turn a request's vendor code into a Vendor, or raise ValueError.

    ``code`` is the short form used at the API boundary ("cisco" / "huawei"),
    or "auto" (source only) to run detection over ``text`` -- spec 3.1 / 6.
    """
    if code == "auto":
        if text is None:
            raise ValueError("auto-detection requires source text")
        return detect_vendor(text)
    try:
        return SHORT_TO_VENDOR[code]
    except KeyError:
        raise ValueError(f"unknown vendor '{code}'") from None


# --------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------


def create_app(db_path: Optional[str] = None) -> FastAPI:
    """Build the FastAPI app.

    ``db_path`` lets tests point at a temporary database file directly,
    without going through the ``NETMIGRATE_DB`` environment variable (spec
    section 2: "Tests must use a temporary path -- never the real
    database.").
    """
    app = FastAPI(title="NetMigrate API")
    app.state.db_path = db_path or os.environ.get("NETMIGRATE_DB", "netmigrate.db")
    # One dict per app instance, not module-level, so tests that build
    # several apps (several temp databases) don't see each other's batches.
    app.state.batches: "OrderedDict[str, dict]" = OrderedDict()

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return _error(str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error(f"invalid request: {exc}", 400)

    @app.middleware("http")
    async def _limit_json_body_size(request: Request, call_next):
        content_type = request.headers.get("content-type", "")
        content_length = request.headers.get("content-length")
        if content_type.startswith("application/json") and content_length:
            if int(content_length) > MAX_JSON_BODY_BYTES:
                return _error("request body too large", 400)
        return await call_next(request)

    _register_routes(app)
    return app


def _get_db(request: Request) -> Iterator[Any]:
    with persistence.get_connection(request.app.state.db_path) as conn:
        yield conn


def _store_batch(app: FastAPI, batch_id: str, data: dict) -> None:
    batches: "OrderedDict[str, dict]" = app.state.batches
    batches[batch_id] = data
    while len(batches) > MAX_BATCHES:
        batches.popitem(last=False)  # evict oldest, spec 3.3


# --------------------------------------------------------------------------
# Request bodies
# --------------------------------------------------------------------------


class ConvertRequest(BaseModel):
    text: str
    source_vendor: str
    target_vendor: str
    filename: Optional[str] = None
    use_ai: bool = True


class DeviceIn(BaseModel):
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    vendor: Optional[str] = None
    os_version: Optional[str] = None
    ssh_port: Optional[int] = None
    location: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def _register_routes(app: FastAPI) -> None:
    # -- 4. pages: server-rendered Jinja2 shells --------------------------

    for path, template_name in _PAGE_ROUTES.items():

        def _make_page_route(name: str):
            def _page(request: Request) -> HTMLResponse:
                return _templates.TemplateResponse(request, name)

            return _page

        app.get(path, response_class=HTMLResponse)(_make_page_route(template_name))

    # -- 3.1 single conversion -------------------------------------------

    @app.post("/api/convert")
    def api_convert(body: ConvertRequest, conn=Depends(_get_db)):
        try:
            source = _resolve_vendor(body.source_vendor, body.text)
            target = _resolve_vendor(body.target_vendor)
        except ValueError as exc:
            return _error(str(exc), 400)

        fallback = ai_fallback.make_fallback(target) if body.use_ai else None
        try:
            result = convert(body.text, source, target, ai_fallback=fallback)
        except Exception as exc:  # noqa: BLE001 -- see module docstring
            return _error(str(exc), 400)

        payload = result.to_dict()
        conversion_id = persistence.save_conversion(conn, payload, filename=body.filename)
        payload["conversion_id"] = conversion_id
        payload["detected_source"] = VENDOR_TO_SHORT[source]
        return payload

    # -- 3.2 batch conversion ----------------------------------------------

    @app.post("/api/convert/batch")
    async def api_convert_batch(
        request: Request,
        files: list[UploadFile] = File(...),
        options: str = Form(...),
    ):
        try:
            opts_map = json.loads(options)
        except (ValueError, TypeError):
            return _error("options must be valid JSON", 400)
        if not isinstance(opts_map, dict):
            return _error("options must be a JSON object", 400)

        if len(files) > MAX_BATCH_FILES:
            return _error(f"at most {MAX_BATCH_FILES} files per batch", 400)

        # Extension and size are pre-flight guardrails against resource
        # abuse -- rejected for the whole request, before any file is
        # processed (spec 3.2). A file that fails to *convert* (bad vendor
        # option, non-UTF-8 content, an engine error) is a per-file outcome
        # instead, so the batch keeps going for the rest.
        contents: "OrderedDict[str, bytes]" = OrderedDict()
        for f in files:
            name = f.filename or ""
            ext = Path(name).suffix.lower()
            if ext not in ALLOWED_BATCH_EXTENSIONS:
                return _error(f"{name}: unsupported extension '{ext}'", 400)
            data = await f.read()
            if len(data) > MAX_FILE_BYTES:
                return _error(f"{name}: exceeds 1 MB limit", 400)
            contents[name] = data

        results: list[dict] = []
        outputs: dict[str, tuple[str, str]] = {}

        # Opened directly rather than via Depends(_get_db): this handler is
        # `async def` (it awaits UploadFile.read()), so it runs on the event
        # loop thread, while a Depends generator would be resolved in
        # FastAPI's worker threadpool -- a different OS thread, which
        # sqlite3 refuses to let a connection cross.
        with persistence.get_connection(request.app.state.db_path) as conn:
            for filename, data in contents.items():
                entry: dict[str, Any] = {"filename": filename}
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    entry.update(ok=False, error="file is not valid UTF-8 text")
                    results.append(entry)
                    continue

                file_opts = opts_map.get(filename, {})
                if not isinstance(file_opts, dict):
                    file_opts = {}

                try:
                    source = _resolve_vendor(file_opts.get("source_vendor", "auto"), text)
                    target = _resolve_vendor(file_opts.get("target_vendor", ""))
                    fallback = ai_fallback.make_fallback(target)
                    result = convert(text, source, target, ai_fallback=fallback)
                except ValueError as exc:
                    entry.update(ok=False, error=str(exc))
                    results.append(entry)
                    continue
                except Exception as exc:  # noqa: BLE001 -- one file must not abort the batch
                    entry.update(ok=False, error=f"{type(exc).__name__}: {exc}")
                    results.append(entry)
                    continue

                payload = result.to_dict()
                conversion_id = persistence.save_conversion(conn, payload, filename=filename)
                outputs[filename] = (payload["output_text"], VENDOR_TO_SHORT[target])
                entry.update(ok=True, conversion_id=conversion_id, metrics=payload["metrics"])
                results.append(entry)

        batch_id = uuid.uuid4().hex
        _store_batch(request.app, batch_id, {"outputs": outputs})
        return {"batch_id": batch_id, "results": results}

    # -- 3.3 batch ZIP download --------------------------------------------

    @app.get("/api/batch/{batch_id}/zip")
    def api_batch_zip(batch_id: str, request: Request):
        batches: "OrderedDict[str, dict]" = request.app.state.batches
        batch = batches.get(batch_id)
        if batch is None:
            return _error("unknown batch id", 404)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, (output_text, target_short) in batch["outputs"].items():
                stem = Path(filename).stem
                zf.writestr(f"{stem}_{target_short}.cfg", output_text)

        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{batch_id}.zip"'},
        )

    # -- 3.4 devices ---------------------------------------------------------

    @app.get("/api/devices")
    def api_list_devices(
        q: Optional[str] = None,
        vendor: Optional[str] = None,
        location: Optional[str] = None,
        conn=Depends(_get_db),
    ):
        return persistence.list_devices(conn, q=q, vendor=vendor, location=location)

    @app.post("/api/devices", status_code=201)
    def api_create_device(body: DeviceIn, conn=Depends(_get_db)):
        data = {k: v for k, v in body.model_dump().items() if v is not None}
        try:
            device_id = persistence.create_device(conn, data)
        except ValueError as exc:
            return _error(str(exc), 400)
        return persistence.get_device(conn, device_id)

    @app.put("/api/devices/{device_id}")
    def api_update_device(device_id: int, body: DeviceIn, conn=Depends(_get_db)):
        if persistence.get_device(conn, device_id) is None:
            return _error("device not found", 404)
        data = {k: v for k, v in body.model_dump().items() if v is not None}
        persistence.update_device(conn, device_id, data)
        return persistence.get_device(conn, device_id)

    @app.delete("/api/devices/{device_id}")
    def api_delete_device(device_id: int, conn=Depends(_get_db)):
        if not persistence.delete_device(conn, device_id):
            return _error("device not found", 404)
        return {"deleted": True, "id": device_id}

    # -- 3.5 simulated deployment (SSE) --------------------------------------

    @app.get("/api/deploy/stream")
    async def api_deploy_stream(conversion_id: int, device_id: int, request: Request):
        # Opened directly rather than via Depends(_get_db) -- see the same
        # note on api_convert_batch above; this handler is also async.
        with persistence.get_connection(request.app.state.db_path) as conn:
            conversion = persistence.get_conversion(conn, conversion_id)
            device = persistence.get_device(conn, device_id)
        if conversion is None or device is None:
            return _error("conversion or device not found", 404)

        async def event_stream():
            async for event in deploy_sim.simulate_deployment(device, conversion):
                yield deploy_sim.format_sse(event)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # -- 3.6 history -----------------------------------------------------

    @app.get("/api/conversions")
    def api_list_conversions(limit: int = 50, offset: int = 0, conn=Depends(_get_db)):
        return persistence.list_conversions(conn, limit=limit, offset=offset)

    @app.get("/api/conversions/{conversion_id}")
    def api_get_conversion(conversion_id: int, conn=Depends(_get_db)):
        record = persistence.get_conversion(conn, conversion_id)
        if record is None:
            return _error("conversion not found", 404)
        return record

    @app.get("/api/conversions/{conversion_id}/export")
    def api_export_conversion(conversion_id: int, conn=Depends(_get_db)):
        record = persistence.get_conversion(conn, conversion_id)
        if record is None:
            return _error("conversion not found", 404)
        body = json.dumps(record, indent=2, ensure_ascii=False)
        return Response(
            content=body,
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="conversion_{conversion_id}.json"'
                )
            },
        )

    @app.delete("/api/conversions/{conversion_id}")
    def api_delete_conversion(conversion_id: int, conn=Depends(_get_db)):
        if not persistence.delete_conversion(conn, conversion_id):
            return _error("conversion not found", 404)
        return {"deleted": True, "id": conversion_id}

    # -- 3.7 dashboard stats -----------------------------------------------

    @app.get("/api/stats")
    def api_stats(conn=Depends(_get_db)):
        return persistence.get_stats(conn)

    # -- 3.8 health ----------------------------------------------------------

    @app.get("/api/health")
    def api_health(request: Request):
        try:
            with persistence.get_connection(request.app.state.db_path) as conn:
                conn.execute("SELECT 1")
            database_ok = True
        except Exception:  # noqa: BLE001 -- health check must never raise
            database_ok = False

        if not os.environ.get(ai_fallback.API_KEY_ENV):
            ai_status: dict[str, Any] = {
                "enabled": False,
                "reason": "no API key configured",
            }
        else:
            fb = ai_fallback.make_fallback(Vendor.HUAWEI)
            if fb is not None:
                ai_status = {"enabled": True, "reason": None}
            else:
                ai_status = {
                    "enabled": False,
                    "reason": "AI client could not be initialised",
                }

        return {
            "status": "ok",
            "database": database_ok,
            "ai_fallback": ai_status,
            "rules": len(rule_catalog.CATALOG),
            "vendors": [v.value for v in Vendor],
        }


app = create_app()
