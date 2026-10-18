"""Demo API + dashboard for the Chrome extension.

  GET /api/verdict?title=...&price=...   what the extension asks on a product page
  GET /api/series?product=DDR5|DDR4|GPU  lines for the dashboard
  GET /dashboard?product=...&price=...   the single dashboard page (static, fetches the two endpoints)

Reads only the export that commodity-ai-caller publishes: on Cloud Run DATA_DIR is the bucket mount
(/mnt/tank/export) and both files reload when the refresh job replaces them. No data ships with this repo; locally
set DATA_DIR to a copy of the bucket export. Without it every data endpoint answers 503 instead of guessing.
TH_MARKUP sets the Thai-over-US price ratio (uncalibrated, default 1.0). CORS_ORIGINS is a comma-separated
allow-list; empty (the default) sends no CORS headers, which is all the extension and dashboard need.
run: PYTHONPATH=src uvicorn api.app:app --reload
"""
from __future__ import annotations

import logging
import os
import pathlib
import threading
import tomllib

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from cai.fairvalue import FairValue
from cai.product import parse_title
from cai.assessment import SnapshotStore, assess

# Details go to the server log (Cloud Run Logging); visitors get a short message.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cai.api")
UNAVAILABLE = "Price data is updating. Please try again in a few minutes."

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", ROOT / "data" / "export"))
TH_MARKUP = float(os.environ.get("TH_MARKUP", "1.0"))
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
STATIC = pathlib.Path(__file__).resolve().parent / "static"

app = FastAPI(title="Commodity AI demo", version=tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"], docs_url="/api/docs")
# The extension calls the API from its service worker (host_permissions, exempt from CORS) and the dashboard
# is same-origin, so CORS is opt-in for other web clients only.
if CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET"], allow_headers=["*"])

_fv: FairValue | None = None
_fv_signature = None
_fv_lock = threading.Lock()
_snapshots = SnapshotStore(DATA_DIR / "assessment_snapshot.json")


def fv() -> FairValue:
    """Fair-value model, refitted when the refresh job replaces price_daily.parquet (same check as SnapshotStore).
    A file that fails to load keeps the last good model."""
    global _fv, _fv_signature
    path = DATA_DIR / "price_daily.parquet"
    with _fv_lock:
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if signature != _fv_signature:
                _fv, _fv_signature = FairValue(pd.read_parquet(path)), signature
        except Exception as exc:
            if _fv is None:
                log.error("price data unavailable: no readable price_daily.parquet in DATA_DIR=%s (%s: %s)",
                          DATA_DIR, type(exc).__name__, exc)
                raise HTTPException(503, UNAVAILABLE) from exc
            log.warning("kept the last good price model; reload of %s failed (%s: %s)", path, type(exc).__name__, exc)
        return _fv


@app.get("/api/health")
def health():
    # Deployer check: ok + dataset_version when the bucket export is connected; details are in the log.
    try:
        f = fv()
    except HTTPException:
        return JSONResponse({"ok": False, "error": "price data not connected", "data_dir": str(DATA_DIR)}, status_code=503)
    snapshot = _snapshots.load()
    if not snapshot:
        log.error("assessment snapshot unavailable in DATA_DIR=%s: %s", DATA_DIR, _snapshots.error)
        return JSONResponse({"ok": False, "error": "assessment snapshot not connected", "data_dir": str(DATA_DIR)}, status_code=503)
    return {"ok": True, "chip_last_date": f.chip.index[-1].strftime("%Y-%m-%d"), "markup": TH_MARKUP,
            "dataset_version": snapshot["dataset_version"], "dataset_asof": snapshot["asof"], "assessment_warning": _snapshots.error,
            "models": {g: {"r2": round(m.r2, 3), "lag_weeks": m.lag_weeks, "n_months": m.n} for g, m in f.models.items()}}


@app.get("/api/v2/assessment")
def assessment(
    title: str = Query(..., max_length=500),
    price: float | None = Query(None, gt=0, allow_inf_nan=False),
    product: str | None = Query(None, pattern="^(DDR4|DDR5|NVME|SATA|GPU)$"),
    model: str | None = Query(None, max_length=100),
    capacity_gb: int | None = Query(None, gt=0, le=16000),
    confirmed: bool = False,
    ambiguous: bool = False,
    title_source: str | None = Query(None, max_length=40),
    price_source: str | None = Query(None, max_length=40),
    variant_title: str | None = Query(None, max_length=500),
    variant_label: str | None = Query(None, max_length=200),
) -> dict:
    snapshot = _snapshots.load()
    if not snapshot:
        log.error("assessment unavailable: no valid assessment_snapshot.json in DATA_DIR=%s (%s)", DATA_DIR, _snapshots.error)
        raise HTTPException(503, UNAVAILABLE)
    try:
        result = assess(snapshot, title, price, product=product, model=model, capacity_gb=capacity_gb,
                        confirmed=confirmed, ambiguous=ambiguous,
                        title_source=title_source, price_source=price_source,
                        variant_title=variant_title, variant_label=variant_label)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if _snapshots.error:
        log.warning("serving the last verified snapshot; newer file rejected: %s", _snapshots.error)
    result["dataset_warning"] = "Showing the last verified dataset; a newer update is being checked." if _snapshots.error else None
    return result


@app.get("/api/verdict")
def verdict(title: str = Query(..., max_length=500), price: float | None = Query(None, gt=0)) -> dict:
    product = parse_title(title)
    if product is None or product["category"] not in {"RAM", "GPU"}:
        return {"covered": False}
    if product["category"] == "GPU":
        t = fv().gpu_trend()
        t.pop("series")
        return {"covered": True, "product": product, **t, "price_thb": price,
                "dashboard": f"/dashboard?product=GPU&model={product['model']}" + (f"&price={price:g}" if price else "")}
    out = {"covered": True, "product": product,
           "dashboard": f"/dashboard?product={product['generation']}&gb={product['capacity_gb']}" + (f"&price={price:g}" if price else "")}
    if price:
        out.update(fv().verdict(product["generation"], product["capacity_gb"], price, markup=TH_MARKUP))
    return out


@app.get("/api/series")
def series(product: str = Query("DDR5", pattern="^(DDR5|DDR4|GPU)$")) -> dict:
    f = fv()
    if product == "GPU":
        return f.gpu_trend()
    m = f.models[product]
    return {"product": product, **f.curve(product, markup=TH_MARKUP), "markup": TH_MARKUP, "markup_calibrated": False,
            "usdthb": round(f.usdthb(), 3), "lag_weeks": m.lag_weeks, "r2": round(m.r2, 3),
            "chip_last_date": f.chip.index[-1].strftime("%Y-%m-%d")}


@app.get("/dashboard")
def dashboard() -> FileResponse:
    return FileResponse(STATIC / "dashboard.html")


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse("/dashboard?product=DDR5&gb=32")


@app.get("/static/{name:path}")
def static(name: str) -> FileResponse:
    path = (STATIC / name).resolve()
    if not path.is_relative_to(STATIC.resolve()) or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)
