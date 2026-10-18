from pathlib import Path

from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health").json()
    assert r["ok"] and set(r["models"]) == {"DDR4", "DDR5"}


def test_ram_verdict():
    r = client.get("/api/verdict", params={"title": "KINGSTON RAM DDR5(6000) 32GB (16GBX2) FURY BEAST", "price": 15900}).json()
    assert r["covered"] and r["product"]["generation"] == "DDR5" and r["capacity_gb"] == 32
    assert r["verdict"] in {"under", "fair", "over"} and r["dashboard"].startswith("/dashboard?product=DDR5")


def test_gpu_is_trend_only_and_other_products_not_covered():
    g = client.get("/api/verdict", params={"title": "การ์ดจอ MSI RTX 4070 SUPER 12GB GDDR6X", "price": 25000}).json()
    assert g["covered"] and g["verdict"] is None and g["product"]["model"] == "RTX 4070 SUPER"
    assert client.get("/api/verdict", params={"title": "เสื้อยืด", "price": 199}).json() == {"covered": False}
    assert client.get("/api/verdict", params={"title": "NVMe SSD 1TB", "price": 1990}).json() == {"covered": False}


def test_series_and_no_cors_by_default():
    r = client.get("/api/series", params={"product": "DDR4"}, headers={"Origin": "https://shopee.co.th"})
    assert "access-control-allow-origin" not in r.headers
    body = r.json()
    assert body["expected"][-1]["date"] > body["actual"][-1]["date"]
    assert client.get("/api/series", params={"product": "SSD"}).status_code == 422


def test_dashboard_served_and_static_traversal_blocked():
    assert client.get("/dashboard").status_code == 200
    assert client.get("/static/..%2Fapp.py").status_code == 404
    assert client.get("/static/fonts/fonts.css").status_code == 200


def test_model_reloads_when_export_is_replaced(tmp_path, monkeypatch):
    import os
    import pandas as pd
    import api.app as demo_app

    full = pd.read_parquet(Path(__file__).resolve().parent / "fixtures" / "export" / "price_daily.parquet")
    monkeypatch.setattr(demo_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(demo_app, "_fv", None)
    monkeypatch.setattr(demo_app, "_fv_signature", None)
    path = tmp_path / "price_daily.parquet"
    full[full["date"] < "2026-06-01"].to_parquet(path)
    before = client.get("/api/health").json()["chip_last_date"]
    assert before < "2026-06-01"

    full.to_parquet(path)
    os.utime(path, ns=(path.stat().st_mtime_ns + 10**9,) * 2)   # coarse-mtime filesystems
    assert client.get("/api/health").json()["chip_last_date"] > before

    path.write_bytes(b"not parquet")   # a broken upload keeps serving the last good model
    os.utime(path, ns=(path.stat().st_mtime_ns + 2 * 10**9,) * 2)
    assert client.get("/api/health").status_code == 200


def test_without_data_every_data_endpoint_answers_503(tmp_path, monkeypatch):
    import api.app as demo_app
    from cai.assessment import SnapshotStore
    monkeypatch.setattr(demo_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(demo_app, "_fv", None)
    monkeypatch.setattr(demo_app, "_fv_signature", None)
    monkeypatch.setattr(demo_app, "_snapshots", SnapshotStore(tmp_path / "assessment_snapshot.json"))
    health = client.get("/api/health")
    assert health.status_code == 503 and health.json()["ok"] is False and health.json()["data_dir"] == str(tmp_path)
    page_error = client.get("/api/v2/assessment", params={"title": "DDR4 16GB"}).json()["detail"]
    assert str(tmp_path) not in page_error and "DATA_DIR" not in page_error   # paths stay in the log
    assert client.get("/api/v2/assessment", params={"title": "DDR4 16GB", "price": 1400}).status_code == 503
    assert client.get("/api/series", params={"product": "DDR4"}).status_code == 503
    assert client.get("/api/verdict", params={"title": "DDR5 32GB", "price": 15900}).status_code == 503


def test_news_judge_is_attached_only_for_scored_judged_categories(tmp_path, monkeypatch):
    import json as _json
    import os
    import api.app as demo_app
    judge = {"schema_version": 1, "generated_at": "2026-10-18T03:00:00+00:00", "news_month": "2026-10",
             "items": {"DDR5": {"status": "SCORED", "direction": "UP", "pressure": 0.62, "articles_judged": 20,
                                "as_of_month": "2026-10", "target_month": "2026-11", "evidence": []},
                       "GPU": {"status": "NO_TEXT", "direction": None, "pressure": None, "articles_judged": 0}},
             "limitations": []}
    path = tmp_path / "judge.json"
    path.write_text(_json.dumps(judge))
    monkeypatch.setattr(demo_app, "_judge", demo_app.JudgeStore(path))
    assert demo_app.news_judge({"category": "RAM", "generation": "DDR5"})["pressure"] == 0.62
    assert demo_app.news_judge({"category": "RAM", "generation": "DDR4"}) is None
    assert demo_app.news_judge({"category": "GPU", "model": "RTX 5070"}) is None
    path.write_text("{broken")   # a bad update keeps the last good file
    os.utime(path, ns=(path.stat().st_mtime_ns + 10**9,) * 2)
    assert demo_app.news_judge({"category": "RAM", "generation": "DDR5"})["direction"] == "UP"
    monkeypatch.setattr(demo_app, "_judge", demo_app.JudgeStore(tmp_path / "missing.json"))
    assert demo_app.news_judge({"category": "RAM", "generation": "DDR5"}) is None
