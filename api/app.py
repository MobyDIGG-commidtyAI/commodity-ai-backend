"""Demo API + dashboard for the Chrome extension.

  GET /api/verdict?title=...&price=...   what the extension asks on a product page
  GET /api/series?product=DDR5|DDR4|GPU  lines for the dashboard
  GET /dashboard?product=...&price=...   the single dashboard page (static, fetches the two endpoints)

Reads only the export files (DATA_DIR, default data/export), so the same image runs on Railway, a VPS or
Cloud Run; on GCP DATA_DIR points at the bucket mount and both files reload when the refresh job replaces them.
TH_MARKUP sets the Thai-over-US price ratio (uncalibrated, default 1.0). CORS_ORIGINS is a comma-separated
allow-list; empty (the default) sends no CORS headers, which is all the extension and dashboard need.
run: PYTHONPATH=src uvicorn api.app:app --reload
"""
from __future__ import annotations

import os
import pathlib
import threading

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from cai.fairvalue import FairValue
from cai.product import parse_title
from cai.assessment import SnapshotStore, assess

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", ROOT / "data" / "export"))
TH_MARKUP = float(os.environ.get("TH_MARKUP", "1.0"))
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
STATIC = pathlib.Path(__file__).resolve().parent / "static"

app = FastAPI(title="Commodity AI demo", docs_url="/api/docs")
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
        except Exception:
            if _fv is None:
                raise
        return _fv


@app.get("/api/health")
def health() -> dict:
    f = fv()
    snapshot = _snapshots.load()
    return {"ok": True, "chip_last_date": f.chip.index[-1].strftime("%Y-%m-%d"), "markup": TH_MARKUP,
            "dataset_version": snapshot["dataset_version"] if snapshot else None,
            "dataset_asof": snapshot["asof"] if snapshot else None, "assessment_warning": _snapshots.error,
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
        raise HTTPException(503, "Assessment dataset unavailable. Build the local snapshot first.")
    try:
        result = assess(snapshot, title, price, product=product, model=model, capacity_gb=capacity_gb,
                        confirmed=confirmed, ambiguous=ambiguous,
                        title_source=title_source, price_source=price_source,
                        variant_title=variant_title, variant_label=variant_label)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result["dataset_warning"] = _snapshots.error
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
