"""Web app tests via FastAPI's TestClient (synthetic data only)."""

import base64
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


def post(files, data=None):
    return client.post("/", files=files, data=data or {})


def test_form_page():
    r = client.get("/")
    assert r.status_code == 200 and 'name="zipfile"' in r.text


def test_upload_returns_subscribers_csv():
    z = make_zip({"a/b.csv": "Email,First Name,Last Name\nAda@Example.com,ada,lovelace\n",
                  "notes.pdf": b"%PDF-1.4"})
    r = post({"zipfile": ("in.zip", z, "application/zip")})
    assert r.status_code == 200
    out = downloads(r.text)
    lines = out["subscribers.csv"].splitlines()
    assert lines[0] == ",".join(HEADER)
    assert lines[1] == f"ada@example.com,Ada,Lovelace,{PREF}"
    assert {"collect_emails_log.csv", "missing_names.csv", "per_file_summary.csv",
            "suspicious_emails.csv"} <= set(out)
    assert "skipped or failed" in r.text and "notes.pdf" in r.text


def test_fix_typos_and_exclude():
    z = make_zip({"a.csv": "email\nann@gmial.com\nold@example.com\nnew@example.com\n"})
    r = post({"zipfile": ("in.zip", z), "exclude": ("existing.csv", b"email\nold@example.com\n")},
             {"fix_typos": "true"})
    emails = [l.split(",")[0] for l in downloads(r.text)["subscribers.csv"].splitlines()[1:]]
    assert emails == ["ann@gmail.com", "new@example.com"]


def test_empty_optional_exclude_field_is_ignored():
    z = make_zip({"a.csv": "email\nx@example.com\n"})
    r = post({"zipfile": ("in.zip", z), "exclude": ("", b"")})
    assert "x@example.com" in downloads(r.text)["subscribers.csv"]


@pytest.mark.parametrize("files, message", [
    ({"zipfile": ("in.zip", b"not a zip")}, "not a valid zip"),
    ({"zipfile": ("in.zip", make_zip({"a.csv": "email\nx@example.com\n"})),
      "exclude": ("old.xlsx", b"not excel")}, "Could not read the exclude file"),
])
def test_errors_are_shown(files, message):
    r = post(files)
    assert r.status_code == 200 and message in r.text and "subscribers.csv" not in downloads(r.text)


def test_login_when_configured(monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "idr")
    monkeypatch.setenv("APP_PASSWORD", "secret")
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("idr", "wrong")).status_code == 401
    assert client.get("/", auth=("idr", "secret")).status_code == 200
