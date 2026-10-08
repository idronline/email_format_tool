"""Minimal web front end: upload a zip, download subscribers.csv.

Run:  uvicorn idr_emails.web:app --host 0.0.0.0 --port 5002

Uploads are processed in a temporary folder that is deleted at once; results are
embedded in the response page, so nothing with personal data is kept on the server.
Set APP_USERNAME and APP_PASSWORD to require a browser login (HTTP basic auth).
"""

import base64
import html
import os
import secrets
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .pipeline import run

PAGE = (Path(__file__).parent / "page.html").read_text(encoding="utf-8")
REPORTS = [
    ("collect_emails_log.csv", "Per-file log"),
    ("missing_names.csv", "Emails without a name"),
    ("per_file_summary.csv", "Per-file summary"),
    ("suspicious_emails.csv", "Suspicious addresses"),
]

basic = HTTPBasic(auto_error=False)


def check_login(creds: HTTPBasicCredentials | None = Depends(basic)):
    user, pw = os.environ.get("APP_USERNAME"), os.environ.get("APP_PASSWORD")
    if not user or not pw:
        return  # login not configured
    ok = creds is not None and secrets.compare_digest(creds.username, user) \
        and secrets.compare_digest(creds.password, pw)
    if not ok:
        raise HTTPException(401, "Login required", headers={"WWW-Authenticate": "Basic"})


app = FastAPI(title="IDR Email Collector", docs_url=None, redoc_url=None, openapi_url=None,
              dependencies=[Depends(check_login)])


def page(result_html=""):
    return HTMLResponse(PAGE.replace("<!-- RESULT -->", result_html))


def download_link(name, text, label, primary=False):
    data = base64.b64encode(text.encode("utf-8")).decode("ascii")
    cls = "btn btn-success btn-lg btn-block mb-3" if primary else "d-block mb-1"
    return (f'<a class="{cls}" download="{name}" '
            f'href="data:text/csv;charset=utf-8;base64,{data}">{html.escape(label)}</a>')


def error(msg):
    return page(f'<div class="alert alert-danger mt-4">{html.escape(msg)}</div>')


@app.get("/", response_class=HTMLResponse)
def index():
    return page()


@app.post("/", response_class=HTMLResponse)
def process(zipfile_: UploadFile = File(..., alias="zipfile"),
            exclude: UploadFile | None = File(None),
            fix_typos: bool = Form(False)):
    with tempfile.TemporaryDirectory(prefix="idr_emails_") as tmp:
        zpath = Path(tmp) / "input.zip"
        with open(zpath, "wb") as fh:
            shutil.copyfileobj(zipfile_.file, fh)
        if not zipfile.is_zipfile(zpath):
            return error(f"{zipfile_.filename} is not a valid zip file.")

        excludes = []
        if exclude is not None and exclude.filename:
            epath = Path(tmp) / ("exclude" + Path(exclude.filename).suffix.lower())
            with open(epath, "wb") as fh:
                shutil.copyfileobj(exclude.file, fh)
            excludes.append(epath)

        try:
            r = run(zpath, excludes, fix_typos)
        except ValueError as exc:
            return error(f"Could not read the exclude file: {exc}")
        texts = r.csv_texts()

    lines = [
        ("Files read OK", r.ok),
        ("Unique emails", len(r.found)),
        ("Without a name", r.no_name),
        ("Suspicious", r.suspicious_count),
    ]
    if fix_typos:
        lines.append(("Typos fixed", r.fixed))
    if excludes:
        lines.append(("Excluded (already on list)", r.excluded))
    rows = "".join(f"<tr><td>{html.escape(k)}</td><td class='text-right'>{v}</td></tr>" for k, v in lines)

    bad = ""
    if r.bad:
        items = "".join(f"<li><b>{html.escape(s)}</b> {html.escape(f)} &ndash; {html.escape(d)}</li>"
                        for f, s, d in r.bad)
        bad = (f'<div class="alert alert-warning small"><b>{len(r.bad)} file(s) skipped or failed</b>'
               f'<ul class="mb-0 pl-3">{items}</ul></div>')

    reports = "".join(download_link(n, texts[n], label) for n, label in REPORTS)
    return page(
        '<hr class="mt-5"><h4 class="mb-3">Result</h4>'
        f'<table class="table table-sm">{rows}</table>{bad}'
        + download_link("subscribers.csv", texts["subscribers.csv"], "Download subscribers.csv", primary=True)
        + f'<p class="mb-1 mt-3 text-muted">Reports</p>{reports}<div class="mb-5"></div>'
    )

