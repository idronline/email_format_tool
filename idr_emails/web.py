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

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import AUDIENCES
from .pipeline import run

PAGE = (Path(__file__).parent / "page.html").read_text(encoding="utf-8")
NAV = (Path(__file__).parent / "nav.html").read_text(encoding="utf-8")
# Shared across IDR tools (same list in every tool repo).
NAV_TOOLS = [("Translate", 5000), ("Audio", 5001), ("Email Collector", 5002)]
NAV_ACTIVE = "Email Collector"
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
        raise HTTPException(401, "Login required", headers={"WWW-Authenticate": 'Basic realm="IDR tools"'})


app = FastAPI(title="IDR Email Collector", docs_url=None, redoc_url=None, openapi_url=None,
              dependencies=[Depends(check_login)])


def nav_html(request: Request):
    host = html.escape(request.url.hostname or "localhost")
    links = "".join(
        f'<a href="//{host}:{port}/"' + (' class="active" aria-current="page"' if name == NAV_ACTIVE else "")
        + f">{html.escape(name)}</a>"
        for name, port in NAV_TOOLS)
    return NAV.replace("<!-- LINKS -->", links)


def page(request: Request, result_html=""):
    return HTMLResponse(PAGE.replace("<!-- NAV -->", nav_html(request)).replace("<!-- RESULT -->", result_html))


def download_link(name, text, label, primary=False):
    data = base64.b64encode(text.encode("utf-8")).decode("ascii")
    cls = "btn btn-success btn-lg btn-block mb-3" if primary else "d-block mb-1"
    return (f'<a class="{cls}" download="{name}" '
            f'href="data:text/csv;charset=utf-8;base64,{data}">{html.escape(label)}</a>')


def error(request, msg):
    return page(request, f'<div class="alert alert-danger mt-4">{html.escape(msg)}</div>')


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return page(request)


@app.post("/", response_class=HTMLResponse)
def process(request: Request,
            zipfile_: UploadFile = File(..., alias="zipfile"),
            fix_typos: bool = Form(False),
            audience: str = Form("")):
    if audience not in AUDIENCES:
        return error(request, "Please choose who the list is for: English or Hindi.")
    with tempfile.TemporaryDirectory(prefix="idr_emails_") as tmp:
        zpath = Path(tmp) / "input.zip"
        with open(zpath, "wb") as fh:
            shutil.copyfileobj(zipfile_.file, fh)
        if not zipfile.is_zipfile(zpath):
            return error(request, f"{zipfile_.filename} is not a valid zip file.")
        r = run(zpath, fix_typos=fix_typos, audience=audience)
        texts = r.csv_texts()

    out_name = f"subscribers_{audience}.csv"
    preference = r.preference or "empty (Hindi)"
    lines = [
        ("Zip file", zipfile_.filename),
        ("Audience", audience.title()),
        ("Newsletter Preference", preference),
        ("Files read", r.ok),
        ("Emails without a name", r.no_name),
        ("Possible typos / test addresses", r.suspicious_count),
    ]
    if fix_typos:
        lines.append(("Typos fixed", r.fixed))
    rows = "".join(f"<tr><td>{html.escape(k)}</td><td class='text-right'>{html.escape(str(v))}</td></tr>"
                   for k, v in lines)

    bad = ""
    if r.bad:
        items = "".join(f"<li>{html.escape(f)} &ndash; {html.escape(d)}</li>" for f, s, d in r.bad)
        bad = (f'<div class="alert alert-warning small"><b>{len(r.bad)} file(s) could not be read</b> '
               f'(their emails are not in the list):<ul class="mb-0 pl-3 mt-1">{items}</ul></div>')

    reports = "".join(download_link(n, texts[n], label) for n, label in REPORTS)
    return page(
        request,
        f'<div class="alert alert-success"><b>Done: {len(r.found)} unique emails.</b></div>'
        + download_link(out_name, texts["subscribers.csv"], f"Download {out_name}", primary=True)
        + bad
        + f'<table class="table table-sm mt-3">{rows}</table>'
        + '<details class="mb-4"><summary class="text-muted">More reports (optional)</summary>'
        + f'<div class="mt-2">{reports}</div></details>'
        + '<hr class="mb-4"><p class="text-muted">Process another zip:</p>'
    )
