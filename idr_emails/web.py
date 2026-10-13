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
from fastapi.staticfiles import StaticFiles

from . import AUDIENCES
from .pipeline import run

HERE = Path(__file__).parent
PAGE = (HERE / "page.html").read_text(encoding="utf-8")
NAV = (HERE / "nav.html").read_text(encoding="utf-8")
# Shared across IDR tools (same list in every tool repo).
NAV_TOOLS = [
    ("Translate", "http://tools.idronline.org:5000/"),
    ("Audio", "http://tools.idronline.org:5001/"),
    ("Email Collector", "http://tools.idronline.org:5002/"),
    ("Image Search", "http://api.idronline.org:5000/"),
]
NAV_ACTIVE = "Email Collector"
REPORTS = [
    ("collect_emails_log.csv", "Per-file log"),
    ("missing_names.csv", "Emails without a name"),
    ("per_file_summary.csv", "Per-file summary"),
    ("suspicious_emails.csv", "Possible typos / test addresses"),
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
# Shared stylesheet and script (same files in every tool repo).
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

esc = html.escape


def nav_html():
    links = "".join(
        f'<a href="{url}"' + (' class="active" aria-current="page"' if name == NAV_ACTIVE else "")
        + f">{esc(name)}</a>"
        for name, url in NAV_TOOLS)
    return NAV.replace("<!-- LINKS -->", links)


def page(request: Request, result_html="", again=False):
    out = PAGE.replace("<!-- NAV -->", nav_html()).replace("<!-- RESULT -->", result_html)
    if again:
        out = out.replace('<p class="card-note hidden" id="again">', '<p class="card-note" id="again">')
    return HTMLResponse(out)


def download_link(name, text, label, primary=False):
    data = base64.b64encode(text.encode("utf-8")).decode("ascii")
    cls = ' class="btn btn-download"' if primary else ""
    return f'<a{cls} download="{name}" href="data:text/csv;charset=utf-8;base64,{data}">{esc(label)}</a>'


def error(request, msg):
    return page(request, '<section class="card error-card result"><div class="done-head">'
                         '<div class="tick bad">!</div><div><h2>Could not collect emails</h2>'
                         f'<p>{esc(msg)}</p></div></div></section>')


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
    sub = " &middot; ".join(esc(x) for x in [zipfile_.filename or "", audience.title(),
                                               r.preference or "no newsletter preference"])
    stats = [(r.ok, "files read"), (r.no_name, "without a name"), (r.suspicious_count, "possible typos")]
    if fix_typos:
        stats.append((r.fixed, "typos fixed"))
    tiles = "".join(f'<div class="stat"><b>{n:,}</b><span>{esc(label)}</span></div>' for n, label in stats)

    bad = ""
    if r.bad:
        items = "".join(f"<li>{esc(f)} ({esc(d)})</li>" for f, _s, d in r.bad)
        bad = (f'<div class="warn"><b>{len(r.bad)} file(s) could not be read</b> &ndash; '
               f'their emails are not in the list:<ul>{items}</ul></div>')

    reports = "".join(download_link(n, texts[n], label) for n, label in REPORTS)
    return page(
        request,
        '<section class="card result">'
        f'<div class="done-head"><div class="tick">&#10003;</div><div><h2>{len(r.found):,} unique emails</h2>'
        f'<p>{sub}</p></div></div>'
        + download_link(out_name, texts["subscribers.csv"], f"Download {out_name}", primary=True)
        + f'<div class="stats">{tiles}</div>{bad}'
        + f'<details><summary>More reports (optional)</summary>{reports}</details>'
        + '</section>',
        again=True,
    )
