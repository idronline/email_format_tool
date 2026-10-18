"""Admin panel: the extra password, the numbers it shows, and the usage log."""

import os
import time

import pytest
from fastapi.testclient import TestClient

from idr_emails import admin, idr_usage

NOW = time.time()
DAY = 86400


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-secret")
    monkeypatch.setenv("SECRET_KEY", "test-key")
    if os.path.exists(idr_usage.DB_PATH):
        os.remove(idr_usage.DB_PATH)
    monkeypatch.setattr(admin, "fetch_image_search", lambda since: ([
        {"ts": NOW - 3600, "tool": "image-search", "ok": 1, "seconds": 1.2, "error": None,
         "details": {"mode": "upload", "matches": 2, "found": True, "best": "Near match"}},
        {"ts": NOW - 7200, "tool": "image-search", "ok": 1, "seconds": 0.9, "error": None,
         "details": {"mode": "link", "matches": 0, "found": False, "best": None}},
    ], {"disk_used_pct": 70, "disk_free_gb": 9.1, "searchable_images": 8639,
        "indexer": {"is_running": 0}, "weekly_update": {"at": "2026-10-11 22:41", "ok": True, "message": "OK"},
        "version": {"commit": "abc1234", "date": "2026-10-14 10:00", "subject": "x"}}, None))
    monkeypatch.setattr(admin, "local_health", lambda: {
        "tools": [{"name": "Translate", "up": True, "version": None}, {"name": "Audio", "up": False, "version": None}],
        "disk_used_pct": 60, "disk_free_gb": 20.0, "alerts": {}})
    return TestClient(admin.app)


def unlock(client):
    r = client.post("/unlock", data={"password": "admin-secret"}, follow_redirects=False)
    assert r.status_code == 303
    return r


def test_panel_is_off_without_admin_password(client, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD")
    assert client.get("/").status_code == 404


def test_needs_the_normal_sign_in_first(client, monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "idr")
    monkeypatch.setenv("APP_PASSWORD", "team")
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_asks_for_the_admin_password(client):
    r = client.get("/")
    assert r.status_code == 200 and "Admin password" in r.text and "Uses per day" not in r.text
    r = client.post("/unlock", data={"password": "wrong"})
    assert r.status_code == 401 and "not right" in r.text


def test_dashboard_after_unlock(client):
    idr_usage.record("translate", seconds=8, language="hi", size_kb=40)
    idr_usage.record("translate", seconds=9, language="mr", size_kb=10)
    idr_usage.record("audio", ok=False, seconds=3, error="No basic male voice is available for kn-IN.",
                     language="kn-IN", voice="male")
    idr_usage.record("emails", seconds=2, audience="english", emails=120, files_read=3, unreadable=1, fix_typos=True)
    unlock(client)
    r = client.get("/")
    assert r.status_code == 200
    t = r.text
    assert "Uses per day" in t and "How the tools are used" in t and "Problems" in t and "Health" in t
    assert "No basic male voice" in t                     # problems table
    assert "to Hindi" in t and "to Marathi" in t          # translate breakdown
    assert "120" in t and "8,639" in t                    # emails collected, searchable images
    assert "not answering" in t                           # Audio health
    assert "abc1234" in t


def test_lock_forgets_the_admin_password(client):
    unlock(client)
    assert "Uses per day" in client.get("/").text
    client.get("/lock")
    assert "Admin password" in client.get("/").text


def test_changing_admin_password_locks_everyone_out(client, monkeypatch):
    unlock(client)
    monkeypatch.setenv("ADMIN_PASSWORD", "new-secret")
    assert "Admin password" in client.get("/").text


def ev(tool, days_ago, ok=True, **details):
    return {"ts": NOW - days_ago * DAY, "tool": tool, "ok": 1 if ok else 0, "seconds": 5, "details": details,
            "error": None if ok else "boom"}


def test_summary_counts_change_and_problems():
    events = sorted([ev("translate", 40, language="hi"),                    # previous period
                     ev("translate", 2, language="hi"), ev("translate", 1, language="hi"),
                     ev("audio", 1, ok=False, language="hi-IN"), ev("audio", 0.1, language="hi-IN", minutes=2.5,
                                                                    voice="female")],
                    key=lambda e: e["ts"])
    s = admin.summarize(events, 30, now=NOW)
    tiles = {t["key"]: t for t in s["tiles"]}
    assert tiles["translate"]["uses"] == 2 and tiles["translate"]["change"] == 100
    assert tiles["audio"]["uses"] == 2 and tiles["audio"]["failed"] == 1 and tiles["audio"]["change"] is None
    assert s["usage"]["translate"]["languages"] == [("Hindi", 2)]
    assert s["usage"]["audio"]["minutes"] == 2.5
    assert s["problems"][0]["tool"] == "Audio" and s["problems"][0]["count"] == 1
    assert len(s["chart"]) == 30 and sum(d["total"] for d in s["chart"]) == 4
    assert s["recent"][0]["tool"] == "Audio"             # newest first


def test_usage_log_and_export_token(monkeypatch, tmp_path):
    db = str(tmp_path / "u.db")
    idr_usage.record("translate", path=db, language="hi")
    idr_usage.record("audio", ok=False, error="x" * 900, path=db)
    rows = idr_usage.events_since(0, path=db)
    assert [r["tool"] for r in rows] == ["translate", "audio"] and len(rows[1]["error"]) == 500
    assert idr_usage.events_since(0, path=str(tmp_path / "none.db")) == []
    idr_usage.record("translate", path="/nonexistent/dir/u.db")           # never raises
    monkeypatch.setenv("SECRET_KEY", "k")
    assert idr_usage.token_ok(idr_usage.export_token()) and not idr_usage.token_ok("guess")
    monkeypatch.delenv("SECRET_KEY")
    assert idr_usage.export_token() is None and not idr_usage.token_ok("")
