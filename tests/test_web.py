"""Web app tests via FastAPI's TestClient (synthetic data only)."""

import base64
import csv
import io
import re

import pytest
from fastapi.testclient import TestClient

from conftest import HEADER, PREF, make_zip
from idr_emails.web import app

client = TestClient(app)


def downloads(html):
    """{filename: decoded text} for every embedded download link."""
    return {name: base64.b64decode(data).decode("utf-8")
            for name, data in re.findall(r'download="([^"]+)" href="data:text/csv;charset=utf-8;base64,([^"]+)"', html)}


def rows(text):
    return list(csv.reader(io.StringIO(text)))


def post(files, data=None):
    return client.post("/", files=files, data=data or {})


ZIP = make_zip({"a.csv": "email\nx@example.com\n"})


def test_form_page():
    r = client.get("/")
    assert r.status_code == 200 and 'name="zipfile"' in r.text
    assert 'name="exclude"' not in r.text  # dropped from the web form
    # audience has no default: two radio buttons, none checked, a choice is required
    assert 'name="audience" id="aud-en" value="english" required' in r.text
    assert 'value="hindi"' in r.text and "checked" not in r.text


def test_shared_static_files_are_served():
    assert "--red:#DF373B" in client.get("/static/idr-tools.css").text
    assert "data-working" in client.get("/static/idr-tools.js").text


def test_navbar_links_to_all_tools():
    r = client.get("/")
    for path in ("translate", "audio", "emails"):
        assert f'href="https://tools.idronline.org/{path}/"' in r.text
    assert 'href="https://api.idronline.org/image-search/">Image Search</a>' in r.text
    assert 'href="https://tools.idronline.org/emails/" class="active"' in r.text
    assert "Sign out" not in r.text  # login is off when no password is set


def test_english_upload():
    z = make_zip({"a/b.csv": "Email,First Name,Last Name\nAda@Example.com,ada,lovelace\n",
                  "notes.pdf": b"%PDF-1.4"})
    r = post({"zipfile": ("in.zip", z, "application/zip")}, {"audience": "english"})
    assert r.status_code == 200
    out = downloads(r.text)
    text = out["subscribers_english.csv"]
    assert rows(text) == [HEADER, ["ada@example.com", "Ada", "Lovelace", PREF]]
    assert text.splitlines()[1] == 'ada@example.com,Ada,Lovelace,"The IDR Weekly,Off The Record"'
    assert {"collect_emails_log.csv", "missing_names.csv", "per_file_summary.csv",
            "suspicious_emails.csv"} <= set(out)
    assert "could not be read" in r.text and "notes.pdf" in r.text


def test_hindi_upload_has_empty_preference():
    out = downloads(post({"zipfile": ("in.zip", ZIP)}, {"audience": "hindi"}).text)
    assert rows(out["subscribers_hindi.csv"]) == [HEADER, ["x@example.com", "", "", ""]]


def test_fix_typos():
    z = make_zip({"a.csv": "email\nann@gmial.com\nnew@example.com\n"})
    r = post({"zipfile": ("in.zip", z)}, {"audience": "english", "fix_typos": "true"})
    emails = [row[0] for row in rows(downloads(r.text)["subscribers_english.csv"])[1:]]
    assert emails == ["ann@gmail.com", "new@example.com"]


@pytest.mark.parametrize("data", [{}, {"audience": ""}, {"audience": "tamil"}])
def test_audience_is_required(data):
    r = post({"zipfile": ("in.zip", ZIP)}, data)
    assert r.status_code == 200 and "Please choose who the list is for" in r.text
    assert not downloads(r.text)


def test_bad_zip_is_reported():
    r = post({"zipfile": ("in.zip", b"not a zip")}, {"audience": "english"})
    assert "not a valid zip" in r.text and not downloads(r.text)


@pytest.fixture
def login_on(monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "idr")
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("SECRET_KEY", "test-key")


def test_login_page_flow(login_on):
    c = TestClient(app, follow_redirects=False)
    r = c.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/"
    assert c.post("/", files={"zipfile": ("in.zip", ZIP)}, data={"audience": "english"}).status_code == 303
    page = c.get("/login?next=/")
    assert page.status_code == 200 and 'name="password"' in page.text and 'href="static/idr-tools.css"' in page.text

    bad = c.post("/login", data={"username": "idr", "password": "nope", "next": "/"})
    assert bad.status_code == 401 and "not right" in bad.text and "idr_login" not in bad.cookies

    ok = c.post("/login", data={"username": "idr", "password": "secret", "next": "/"})
    assert ok.status_code == 303 and ok.headers["location"] == "/"
    assert "idr_login" in ok.cookies and "httponly" in ok.headers["set-cookie"].lower()
    r = c.get("/")
    assert r.status_code == 200 and 'href="logout">Sign out' in r.text

    out = c.get("/logout")
    assert out.status_code == 303 and out.headers["location"] == "/login"
    c.cookies.clear()
    assert c.get("/").status_code == 303


def test_login_behind_nginx_prefix(login_on):
    c = TestClient(app, base_url="https://tools.idronline.org", follow_redirects=False)
    h = {"X-Forwarded-Prefix": "/emails"}
    r = c.get("/", headers=h)
    assert r.headers["location"] == "/emails/login?next=/emails/"
    ok = c.post("/login", headers=h, data={"username": "idr", "password": "secret", "next": "/emails/"})
    assert ok.headers["location"] == "/emails/"
    assert "secure" in ok.headers["set-cookie"].lower()  # https -> cookie only sent over https
    # never redirect off-site after login
    evil = c.post("/login", headers=h, data={"username": "idr", "password": "secret", "next": "//evil.example/"})
    assert evil.headers["location"] == "/emails/"


def test_password_change_signs_everyone_out(login_on, monkeypatch):
    c = TestClient(app, follow_redirects=False)
    c.post("/login", data={"username": "idr", "password": "secret", "next": "/"})
    assert c.get("/").status_code == 200
    monkeypatch.setenv("APP_PASSWORD", "new-secret")
    assert c.get("/").status_code == 303


def test_static_files_need_no_login(login_on):
    assert client.get("/static/idr-tools.css").status_code == 200
