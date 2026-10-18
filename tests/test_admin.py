"""Admin panel: the extra password, the numbers it shows, and the usage log."""

import os
import time

import pytest
from fastapi.testclient import TestClient

from idr_emails import admin, idr_usage

NOW = time.time()
DAY = 86400


SEARCH_EVENTS = [
    {"ts": NOW - 3600, "tool": "hindi-search", "ok": 1, "seconds": 1.4, "error": None,
     "details": {"mode": "dev", "kind": "search", "results": 90, "keyword_match": True}},
    {"ts": NOW - 4000, "tool": "hindi-search", "ok": 1, "seconds": 0.8, "error": None,
     "details": {"mode": "roman", "kind": "year", "results": 80, "keyword_match": True}},
    {"ts": NOW - 5000, "tool": "hindi-search", "ok": 0, "seconds": 2.0, "error": "RuntimeError: Typesense search failed",
     "details": {}},
    {"ts": NOW - 40 * DAY, "tool": "hindi-search", "ok": 1, "seconds": 1.0, "error": None,
     "details": {"mode": "dev", "kind": "search", "results": 90, "keyword_match": True}},
]
SEARCH_QUERIES = {"top": [["2026", 36], ["हिंसा", 11]], "few_matches": [["articles about nrega", 1, 3]],
                  "few_matches_limit": 5, "hidden": 2}
SEARCH_HEALTH = {"version": {"commit": "def5678", "date": "2026-10-18 09:00", "subject": "x"}, "articles": 981,
                 "typesense_docs": 981, "qdrant_articles": 979, "qdrant_chunks": 22620,
                 "refresh": {"at": "2026-10-10 19:14", "ok": True, "outcome": "rebuilt", "articles": 981,
                             "added": 5, "removed": 0, "failed_step": None, "error": None},
                 "eval": {"file": "after4.json", "at": "2026-10-14 08:00",
                          "sets": [{"set": "known_item", "metric": "mrr", "value": 0.97, "n": 15}]},
                 "labels": {"total": 3, "trainable": 2, "needed": 200}, "ranker": "ranker_v2",
                 "weights_learned": False, "memory": {"used_pct": 72, "free_gb": 2.2},
                 "disk_used_pct": 70, "disk_free_gb": 9.1}


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
    monkeypatch.setattr(admin, "fetch_search", lambda url, since, days: (SEARCH_EVENTS, SEARCH_QUERIES, SEARCH_HEALTH, None))
    monkeypatch.delenv("ENGLISH_SEARCH_USAGE_URL", raising=False)
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


def test_tools_tab_has_no_search(client):
    unlock(client)
    t = client.get("/").text
    assert "Uses per day" in t and 'href="search?days=30"' in t       # tab link keeps the period
    assert "articles about nrega" not in t and "Typesense search failed" not in t
    assert "email address or phone number" not in t                    # tools keep counts only


def test_search_tab(client):
    unlock(client)
    t = client.get("/search?days=7").text
    assert "Hindi search" in t and "hindi.idronline.org" in t
    assert 'class="on" aria-current="page">Search' in t and "Last 7 days" in t
    assert "articles about nrega" in t and "हिंसा" in t                # query lists
    assert "2 searches not shown" in t                                 # privacy filter note
    assert "Typesense search failed" in t                              # its own problems table
    assert "def5678" in t and "979" in t and "differs" in t           # health: version, index mismatch
    assert "2 <span" in t and "/ 200" in t                             # labels towards the ranker
    assert "English search" in t and "Not connected yet" in t          # English listed, not fetched
    assert "email address or phone number" in t                        # privacy line in the header


def test_search_tab_shows_english_once_connected(client, monkeypatch):
    monkeypatch.setenv("ENGLISH_SEARCH_USAGE_URL", "https://example.org/api/usage")
    unlock(client)
    t = client.get("/search").text
    assert t.count("No searches failed") + t.count("Typesense search failed") >= 2 and "Not connected yet" not in t


def test_search_tab_needs_the_admin_password(client):
    r = client.get("/search")
    assert "Admin password" in r.text and "Hindi search" not in r.text


def test_hindi_search_summary():
    s = admin.summarize_search(SEARCH_EVENTS, SEARCH_QUERIES, 30, "Hindi search", now=NOW)
    assert s["searches"] == 2 and s["failed"] == 1 and s["before"] == 1 and s["change"] == 100
    assert s["median_seconds"] == 1.4
    assert dict(s["kinds"]) == {"Topic or words": 1, "A year": 1}
    assert dict(s["modes"]) == {"Hindi script": 1, "English letters": 1}
    assert s["problems"][0]["tool"] == "Hindi search" and s["problems"][0]["count"] == 1
    assert sum(d["total"] for d in s["chart"]) == 2


def test_missing_search_feed_is_shown_not_fatal(client, monkeypatch):
    monkeypatch.setattr(admin, "fetch_search", lambda url, since, days: ([], None, None, "it timed out"))
    unlock(client)
    r = client.get("/search")
    assert r.status_code == 200
    assert "Hindi search numbers are missing: it timed out" in r.text
    assert "No answer from the search server" in r.text
