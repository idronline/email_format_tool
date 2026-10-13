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
    # audience has no default: the placeholder is selected and the field is required
    assert '<option value="" selected disabled>' in r.text and 'name="audience" required' in r.text


def test_navbar_links_use_request_host():
    r = TestClient(app, base_url="http://tools.idronline.org:5002").get("/")
    for port in (5000, 5001, 5002):
        assert f'href="//tools.idronline.org:{port}/"' in r.text
    assert 'href="//tools.idronline.org:5002/" class="active"' in r.text


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


def test_login_when_configured(monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "idr")
    monkeypatch.setenv("APP_PASSWORD", "secret")
    assert client.get("/").status_code == 401
    assert client.get("/").headers["www-authenticate"] == 'Basic realm="IDR tools"'
    assert client.get("/", auth=("idr", "wrong")).status_code == 401
    assert client.get("/", auth=("idr", "secret")).status_code == 200
