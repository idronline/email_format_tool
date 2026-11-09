"""Minimal web front end: upload a zip, download subscribers.csv.

Run:  uvicorn idr_emails.web:app --host 0.0.0.0 --port 5002
      (behind nginx at /emails/:  --host 127.0.0.1, nginx sends X-Forwarded-Prefix /emails)

Uploads are processed in a temporary folder that is deleted at once; results are
embedded in the response page. When beehiiv is set up (BEEHIIV_API_KEY), the collected
emails and names are also kept in memory for up to an hour for the "Add to beehiiv"
card (beehiiv_web.py) - never on disk.
Set APP_USERNAME and APP_PASSWORD to require the shared IDR tools login (see login.py).
"""

import base64
import html
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import AUDIENCES, beehiiv_web
from .idr_usage import record as record_usage
from .login import login_enabled, make_routes, require_login
from .pipeline import run

HERE = Path(__file__).parent
PAGE = (HERE / "page.html").read_text(encoding="utf-8")
NAV = (HERE / "nav.html").read_text(encoding="utf-8")
# Shared across IDR tools (same list in every tool repo).
NAV_TOOLS = [
    ("Translate", "https://tools.idronline.org/translate/"),
    ("Audio", "https://tools.idronline.org/audio/"),
    ("Email Collector", "https://tools.idronline.org/emails/"),
    ("Image Search", "https://tools.idronline.org/image-search/"),
]
NAV_ACTIVE = "Email Collector"
REPORTS = [
    ("collect_emails_log.csv", "Per-file log", "हर फ़ाइल का लॉग"),
    ("missing_names.csv", "Emails without a name", "बिना नाम वाले ईमेल"),
    ("per_file_summary.csv", "Per-file summary", "हर फ़ाइल का सारांश"),
    ("suspicious_emails.csv", "Possible typos / test addresses", "संभावित गलतियां / टेस्ट ईमेल"),
]

app = FastAPI(title="IDR Email Collector", docs_url=None, redoc_url=None, openapi_url=None)
# Shared stylesheet and script (same files in every tool repo).
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

esc = html.escape


def bi(en, hi):
    """English text with its Hindi line underneath (styled by .hi in idr-tools.css)."""
    return f'{esc(en)}<span class="hi" lang="hi">{esc(hi)}</span>'


def nav_html():
    links = "".join(
        f'<a href="{url}"' + (' class="active" aria-current="page"' if name == NAV_ACTIVE else "")
        + f">{esc(name)}</a>"
        for name, url in NAV_TOOLS)
    signout = f'<a class="idr-nav-signout" href="logout">{bi("Sign out", "साइन आउट")}</a>' if login_enabled() else ""
    return NAV.replace("<!-- LINKS -->", links).replace("<!-- SIGNOUT -->", signout)


app.include_router(make_routes(nav_html))
app.include_router(beehiiv_web.router)


# How beehiiv is updated - a side card next to the form (below it on narrow screens).
BEEHIIV_RULES = [
    ("Nothing changes in beehiiv until you press the button under your result.",
     "जब तक आप नतीजे के नीचे वाला बटन नहीं दबाते, beehiiv में कुछ नहीं बदलता।"),
    ("New English subscribers get both newsletters, The IDR Weekly and Off The Record, along with their names.",
     "नए English सब्सक्राइबर्स को दोनों न्यूज़लेटर मिलते हैं, The IDR Weekly और Off The Record, साथ में उनका नाम भी जुड़ता है।"),
    ("New Hindi subscribers are added with their names.",
     "नए Hindi सब्सक्राइबर्स उनके नाम के साथ जुड़ते हैं।"),
    ("No welcome or confirmation email is sent. New subscribers are active right away.",
     "कोई वेलकम या कन्फ़र्मेशन ईमेल नहीं जाता। नए सब्सक्राइबर्स तुरंत एक्टिव हो जाते हैं।"),
    ("People already on the list keep their newsletter choices. Only their first and last names are updated, "
     "and only when the list has a different name. A blank name never replaces a saved one.",
     "जो लोग पहले से लिस्ट में हैं, उनकी न्यूज़लेटर पसंद नहीं बदलती। सिर्फ़ उनका नाम अपडेट होता है, वह भी तभी जब लिस्ट में "
     "नाम अलग हो। खाली नाम से पुराना नाम नहीं मिटता।"),
    ("People who unsubscribed are never added back.",
     "जिन्होंने अनसब्सक्राइब किया है, उन्हें दोबारा नहीं जोड़ा जाता।"),
]


def beehiiv_aside():
    items = "".join(f"<li>{bi(en, hi)}</li>" for en, hi in BEEHIIV_RULES)
    return f"""
      <style>
        .side-card{{background:var(--white);border:1px solid #e2e2e2;border-radius:12px;padding:1.25rem 1.3rem;margin-top:1.25rem;
                   box-shadow:0 2px 10px rgba(0,0,0,.06)}}
        .side-card h2{{font-size:1.05rem;margin:0 0 .7rem;line-height:1.3}}
        .side-card h2 .hi{{font-family:var(--hindi-serif);font-size:.85em;font-weight:700;color:var(--black)}}
        .side-card ul{{margin:0;padding-left:1.1rem;font-size:.88rem}}
        .side-card li{{margin-bottom:.65rem}}
        .side-card li .hi{{font-size:.82rem;margin-top:.1rem}}
        /* narrow screens: show it after the form, not before */
        @media (max-width:1319px){{main{{display:flex;flex-direction:column}} .side-card{{order:1}}}}
        /* wide screens: float into the empty space right of the form; flow-root keeps the page tall enough */
        @media (min-width:1320px){{main{{display:flow-root}}
          .side-card{{float:right;width:300px;margin:1.25rem -324px 1rem 0}}}}
      </style>
      <aside class="side-card" aria-label="How beehiiv is updated">
        <h2>How beehiiv is updated<span class="hi" lang="hi">beehiiv कैसे अपडेट होता है</span></h2>
        <ul>{items}</ul>
      </aside>
"""


def page(request: Request, result_html="", again=False):
    out = PAGE.replace("<!-- NAV -->", nav_html()).replace("<!-- RESULT -->", result_html)
    if beehiiv_web.enabled():
        out = out.replace("    <main>\n", "    <main>\n" + beehiiv_aside(), 1)
    if again:
        out = out.replace('<p class="card-note hidden" id="again">', '<p class="card-note" id="again">')
    return HTMLResponse(out)


def download_link(name, text, label, label_hi, primary=False):
    data = base64.b64encode(text.encode("utf-8")).decode("ascii")
    if primary:
        return (f'<a class="btn btn-download" download="{name}" href="data:text/csv;charset=utf-8;base64,{data}">'
                f'{bi(label, label_hi)}</a>')
    return (f'<a download="{name}" href="data:text/csv;charset=utf-8;base64,{data}">'
            f'{esc(label)} &middot; <span lang="hi">{esc(label_hi)}</span></a>')


def error(request, msg):
    return page(request, '<section class="card error-card result"><div class="done-head">'
                         f'<div class="tick bad">!</div><div><h2>{bi("Could not collect emails", "ईमेल इकट्ठा नहीं हो सके")}</h2>'
                         f'<p>{esc(msg)}</p></div></div></section>')


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def index(request: Request):
    return page(request)


@app.post("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
def process(request: Request,
            zipfile_: UploadFile = File(..., alias="zipfile"),
            fix_typos: bool = Form(False),
            audience: str = Form("")):
    started = time.time()
    if audience not in AUDIENCES:
        return error(request, "Please choose who the list is for: English or Hindi. · कृपया चुनें कि लिस्ट किसके लिए है: English या Hindi।")
    with tempfile.TemporaryDirectory(prefix="idr_emails_") as tmp:
        zpath = Path(tmp) / "input.zip"
        with open(zpath, "wb") as fh:
            shutil.copyfileobj(zipfile_.file, fh)
        size_kb = round(zpath.stat().st_size / 1024)
        if not zipfile.is_zipfile(zpath):
            record_usage("emails", ok=False, seconds=time.time() - started, error="not a valid zip file",
                         audience=audience, size_kb=size_kb)
            return error(request, f"{zipfile_.filename} is not a valid zip file. · यह सही zip फ़ाइल नहीं है।")
        try:
            r = run(zpath, fix_typos=fix_typos, audience=audience)
            texts = r.csv_texts()
        except Exception as e:
            record_usage("emails", ok=False, seconds=time.time() - started, error=str(e) or type(e).__name__,
                         audience=audience, size_kb=size_kb)
            raise
    # counts only - never the addresses themselves
    record_usage("emails", seconds=time.time() - started, audience=audience, size_kb=size_kb,
                 files_read=r.ok, unreadable=len(r.bad), emails=len(r.found), no_name=r.no_name,
                 possible_typos=r.suspicious_count, fix_typos=bool(fix_typos))

    out_name = f"subscribers_{audience}.csv"
    sub = " &middot; ".join(esc(x) for x in [zipfile_.filename or "", audience.title(),
                                               r.preference or "no newsletter preference"])
    stats = [(r.ok, "files read", "फ़ाइलें पढ़ी गईं"), (r.no_name, "without a name", "बिना नाम के"),
             (r.suspicious_count, "possible typos", "संभावित गलतियां")]
    if fix_typos:
        stats.append((r.fixed, "typos fixed", "गलतियां ठीक हुईं"))
    tiles = "".join(f'<div class="stat"><b>{n:,}</b><span>{bi(label, hi)}</span></div>' for n, label, hi in stats)

    bad = ""
    if r.bad:
        items = "".join(f"<li>{esc(f)} ({esc(d)})</li>" for f, _s, d in r.bad)
        bad = (f'<div class="warn"><b>{len(r.bad)} file(s) could not be read</b> &ndash; '
               f'their emails are not in the list.<span class="hi" lang="hi">{len(r.bad)} फ़ाइलें पढ़ी नहीं जा सकीं, '
               f'उनके ईमेल लिस्ट में नहीं हैं।</span><ul>{items}</ul></div>')

    reports = "".join(download_link(n, texts[n], label, hi) for n, label, hi in REPORTS)
    return page(
        request,
        '<section class="card result">'
        f'<div class="done-head"><div class="tick">&#10003;</div><div><h2>{bi(f"{len(r.found):,} unique emails", f"{len(r.found):,} यूनिक ईमेल")}</h2>'
        f'<p>{sub}</p></div></div>'
        + download_link(out_name, texts["subscribers.csv"], f"Download {out_name}", f"{out_name} डाउनलोड करें", primary=True)
        + f'<div class="stats">{tiles}</div>{bad}'
        + f'<details><summary>More reports (optional) &middot; <span lang="hi">और रिपोर्ट (ज़रूरी नहीं)</span></summary>{reports}</details>'
        + '</section>'
        + (beehiiv_web.card(beehiiv_web.remember(audience, [(e, v["first"], v["last"]) for e, v in sorted(r.found.items())]),
                            audience, len(r.found))
           if beehiiv_web.enabled() and r.found else ""),
        again=True,
    )
