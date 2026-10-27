"""Admin panel for the IDR tools: how often and how each tool is used, problems, health.

Run:  uvicorn idr_emails.admin:app --host 127.0.0.1 --port 5003
      (behind nginx at /admin/, which sends X-Forwarded-Prefix /admin)

Not linked anywhere. Opening it needs the normal IDR tools sign-in and then the admin
password (ADMIN_PASSWORD in ~/idr-tools.env); without ADMIN_PASSWORD the panel is off.
Usage comes from ~/idr-usage.db on this server (Translate, Audio, Email Collector) and
from Image Search's /api/usage on the image server. Only counts and settings are stored.

The Search tab (/search) shows the public websites' search boxes (Hindi, later English), each
from its search API's /api/usage. It is the one place the panel shows text: what readers typed,
in aggregate, with anything that looks like an email address or phone number left out.
"""

import asyncio
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import idr_usage
from .login import make_routes, prefix, require_login
from .web import NAV, NAV_TOOLS, bi

HERE = Path(__file__).parent
IST = timezone(timedelta(hours=5, minutes=30))
ADMIN_COOKIE = "idr_admin"
ADMIN_MAX_AGE = 12 * 3600
IMAGE_SEARCH_FEED = os.environ.get("IMAGE_SEARCH_USAGE_URL", "https://api.idronline.org/image-search/api/usage")
# Public website search boxes, shown on the Search tab. A site without a feed URL is listed as
# not connected (set ENGLISH_SEARCH_USAGE_URL once the English search runs).
SEARCH_SITES = [
    {"key": "hindi", "name": "Hindi search", "where": "the search box on hindi.idronline.org",
     "env": "HINDI_SEARCH_USAGE_URL", "default": "https://api.idronline.org/api/usage"},
    {"key": "english", "name": "English search", "where": "the search box on idronline.org",
     "env": "ENGLISH_SEARCH_USAGE_URL", "default": ""},
]
# name=folder-in-home:port for the tools on this server (folder names differ from repo names)
LOCAL_TOOLS = os.environ.get("IDR_ADMIN_TOOLS",
                             "Translate=multilang_ui:5000,Audio=audio_generation:5001,Email Collector=email_format_tool:5002")
HEALTH_STATE = os.path.expanduser("~/.idr-health-state.json")
# The Audio voice listening test (audio_generation/tools/listening_test.py) and its votes
LISTENING_DIR = os.environ.get("AUDIO_SAMPLES_DIR") or os.path.expanduser("~/listening-test")

# tool key -> (display name, categorical colour slot). Fixed order, never cycled.
TOOLS = {
    "translate": ("Translate", 1),
    "audio": ("Audio", 2),
    "emails": ("Email Collector", 3),
    "image-search": ("Image Search", 4),
}
SEARCH_SLOT = 5  # colour slot for the search sections
SEARCH_MODES = {"dev": "Hindi script", "roman": "English letters", "mixed": "Both scripts"}
SEARCH_KINDS = {"search": "Topic or words", "year": "A year", "series": "A series or format",
                "author": "An author", "place": "A place"}
LANGUAGES = {"hi": "Hindi", "en": "English", "bn": "Bengali", "gu": "Gujarati", "kn": "Kannada", "mr": "Marathi"}
PERIODS = (7, 30, 90)

app = FastAPI(title="IDR tools admin", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Environment(loader=FileSystemLoader(HERE), autoescape=select_autoescape(["html"]))


def nav_html():
    links = "".join(f'<a href="{url}">{name}</a>' for name, url in NAV_TOOLS)
    signout = f'<a class="idr-nav-signout" href="logout">{bi("Sign out", "साइन आउट")}</a>'
    return NAV.replace("<!-- LINKS -->", links).replace("<!-- SIGNOUT -->", signout)


app.include_router(make_routes(nav_html))


# ─────────────────────────────────────────────
# ADMIN PASSWORD (second step after the normal sign-in)
# ─────────────────────────────────────────────

def admin_password():
    return os.environ.get("ADMIN_PASSWORD") or None


def _serializer():
    key = os.environ.get("SECRET_KEY") or hashlib.sha256(f"idr-admin|{admin_password()}".encode()).hexdigest()
    return URLSafeTimedSerializer(key, salt="idr-admin")


def _fingerprint():
    return hashlib.sha256(admin_password().encode()).hexdigest()[:16]


def unlocked(request: Request):
    try:
        data = _serializer().loads(request.cookies.get(ADMIN_COOKIE, ""), max_age=ADMIN_MAX_AGE)
    except BadSignature:
        return False
    return data == {"p": _fingerprint()}


def page(name, status=200, **ctx):
    html = templates.get_template(name).render(nav=nav_html(), **ctx)
    return HTMLResponse(html, status)


# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

def _fetch_feed(url, query):
    """(data, problem) from a /api/usage feed on another server."""
    token = idr_usage.export_token()
    if not token:
        return None, "SECRET_KEY is not set, so the other server can't be asked."
    req = urllib.request.Request(f"{url}?{query}", headers={"X-IDR-Usage-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.load(resp), None
    except Exception as e:  # noqa: BLE001 - show it on the page instead of failing
        return None, f"The server didn't answer ({type(e).__name__}: {getattr(e, 'reason', e)})."


def fetch_image_search(since):
    """(events, health, problem) from Image Search's /api/usage."""
    data, problem = _fetch_feed(IMAGE_SEARCH_FEED, f"since={since:.0f}")
    return (data.get("events", []), data.get("health"), None) if data else ([], None, problem)


def fetch_search(url, since, days):
    """(events, queries, health, problem) from a website search's /api/usage."""
    data, problem = _fetch_feed(url, f"since={since:.0f}&days={days}")
    if not data:
        return [], None, None, problem
    return data.get("events", []), data.get("queries"), data.get("health"), None


def git_version(folder):
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%h|%cd|%s", "--date=format:%Y-%m-%d %H:%M"],
                             cwd=folder, capture_output=True, text=True, timeout=5).stdout.strip()
        commit, date, subject = out.split("|", 2)
        return {"commit": commit, "date": date, "subject": subject[:80]}
    except Exception:  # noqa: BLE001
        return None


def tool_answers(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/login", timeout=3) as resp:
            return resp.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:  # noqa: BLE001
        return False


def local_health():
    tools = []
    for item in LOCAL_TOOLS.split(","):
        name, _, rest = item.partition("=")
        folder, _, port = rest.partition(":")
        tools.append({"name": name.strip(), "up": tool_answers(port.strip()),
                      "version": git_version(os.path.expanduser(f"~/{folder.strip()}"))})
    disk = shutil.disk_usage("/")
    try:
        with open(HEALTH_STATE) as f:
            down_now = json.load(f)
    except (OSError, ValueError):
        down_now = {}
    return {"tools": tools, "disk_used_pct": round(disk.used / disk.total * 100),
            "disk_free_gb": round(disk.free / 1e9, 1), "alerts": down_now}


def language_name(code):
    return LANGUAGES.get((code or "").split("-")[0], code or "?")


def day_of(ts):
    return datetime.fromtimestamp(ts, IST).date()


def summarize(events, days, now=None):
    """Everything the page shows, from usage rows (oldest first) covering 2 x days."""
    now = now or time.time()
    start, prev_start = now - days * 86400, now - 2 * days * 86400
    current = [e for e in events if e["ts"] >= start]
    previous = [e for e in events if prev_start <= e["ts"] < start]

    tiles = []
    for key, (name, slot) in TOOLS.items():
        mine = [e for e in current if e["tool"] == key]
        before = sum(1 for e in previous if e["tool"] == key)
        uses = len(mine)
        change = None if not before else round((uses - before) / before * 100)
        tiles.append({"key": key, "name": name, "slot": slot, "uses": uses, "failed": sum(1 for e in mine if not e["ok"]),
                      "before": before, "change": change})

    # uses per day per tool, for the stacked bar chart
    today = day_of(now)
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    per_day = {d: Counter() for d in dates}
    for e in current:
        d = day_of(e["ts"])
        if d in per_day:
            per_day[d][e["tool"]] += 1
    peak = max([sum(c.values()) for c in per_day.values()] + [1])
    chart = [{"date": d.isoformat(), "label": d.strftime("%d %b"), "total": sum(per_day[d].values()),
              "parts": [{"key": k, "name": TOOLS[k][0], "slot": TOOLS[k][1], "count": per_day[d][k],
                         "pct": per_day[d][k] / peak * 100} for k in TOOLS if per_day[d][k]]}
             for d in dates]

    ok = [e for e in current if e["ok"]]
    by = lambda tool: [e["details"] for e in ok if e["tool"] == tool]  # noqa: E731
    tr, au, em, im = by("translate"), by("audio"), by("emails"), by("image-search")
    usage = {
        "translate": {"languages": Counter(language_name(d.get("language")) for d in tr).most_common()},
        "audio": {"languages": Counter(language_name(d.get("language")) for d in au).most_common(),
                  "voices": Counter(d["voice"].capitalize() for d in au if d.get("voice")).most_common(),
                  "minutes": round(sum(d.get("minutes") or 0 for d in au), 1)},
        "emails": {"audiences": Counter((d.get("audience") or "?").capitalize() for d in em).most_common(),
                   "emails": sum(d.get("emails") or 0 for d in em),
                   "per_list": round(sum(d.get("emails") or 0 for d in em) / len(em)) if em else 0,
                   "unreadable": sum(d.get("unreadable") or 0 for d in em),
                   "fix_typos": sum(1 for d in em if d.get("fix_typos"))},
        "image-search": {"modes": Counter("Uploaded image" if d.get("mode") == "upload" else "Pasted link"
                                          for d in im).most_common(),
                         "found_pct": round(sum(1 for d in im if d.get("found")) / len(im) * 100) if im else None,
                         "best": Counter(d.get("best") for d in im if d.get("best")).most_common()},
    }

    failures = defaultdict(lambda: {"count": 0, "last": 0})
    for e in current:
        if not e["ok"]:
            f = failures[(e["tool"], e.get("error") or "unknown error")]
            f["count"] += 1
            f["last"] = max(f["last"], e["ts"])
    problems = sorted(({"tool": TOOLS.get(t, (t,))[0], "error": err, "count": f["count"],
                        "last": datetime.fromtimestamp(f["last"], IST).strftime("%d %b %H:%M")}
                       for (t, err), f in failures.items()), key=lambda p: (-p["count"], p["tool"]))
    slowest = sorted((e for e in ok if e.get("seconds")), key=lambda e: -e["seconds"])[:5]

    return {"days": days, "tiles": tiles, "chart": chart, "peak": peak, "usage": usage, "problems": problems,
            "slowest": [describe(e) for e in slowest],
            "recent": [describe(e) for e in reversed(current[-50:])], "total": len(current)}


def summarize_search(events, queries, days, name="Search", now=None):
    """One website search's section, from its usage rows (covering 2 x days) and query lists."""
    now = now or time.time()
    start, prev_start = now - days * 86400, now - 2 * days * 86400
    current = [e for e in events if e["ts"] >= start]
    before = sum(1 for e in events if prev_start <= e["ts"] < start)
    ok = [e for e in current if e["ok"]]
    times = sorted(e["seconds"] for e in ok if e.get("seconds"))

    today = day_of(now)
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    per_day = Counter(day_of(e["ts"]) for e in ok)
    peak = max([per_day[d] for d in dates] + [1])
    chart = [{"date": d.isoformat(), "label": d.strftime("%d %b"), "total": per_day[d],
              "parts": [{"key": "search", "name": "Searches", "slot": SEARCH_SLOT, "count": per_day[d],
                         "pct": per_day[d] / peak * 100}] if per_day[d] else []}
             for d in dates]

    failures = defaultdict(lambda: {"count": 0, "last": 0})
    for e in current:
        if not e["ok"]:
            f = failures[e.get("error") or "unknown error"]
            f["count"] += 1
            f["last"] = max(f["last"], e["ts"])
    problems = [{"tool": name, "error": err, "count": f["count"],
                 "last": datetime.fromtimestamp(f["last"], IST).strftime("%d %b %H:%M")} for err, f in failures.items()]

    details = [e["details"] for e in ok]
    queries = queries or {}
    return {
        "searches": len(ok), "before": before,
        "change": None if not before else round((len(ok) - before) / before * 100),
        "failed": len(current) - len(ok),
        "median_seconds": times[len(times) // 2] if times else None,
        "per_day": round(len(ok) / days, 1),
        "chart": chart, "peak": peak,
        "kinds": [(SEARCH_KINDS.get(k, k), n) for k, n in Counter(d.get("kind") for d in details).most_common()],
        "modes": [(SEARCH_MODES.get(m, m), n) for m, n in Counter(d.get("mode") for d in details).most_common()],
        "top": queries.get("top") or [],
        "few_matches": queries.get("few_matches") or [],
        "few_limit": queries.get("few_matches_limit", 5),
        "hidden": queries.get("hidden", 0),
        "problems": problems,
    }


def describe(e):
    """One row for the activity tables."""
    d = e["details"]
    tool = e["tool"]
    if tool == "translate":
        what = f"to {language_name(d.get('language'))}"
    elif tool == "audio":
        what = language_name(d.get('language')) + (f", {d['voice']} voice" if d.get("voice") else "") + \
               (f", {d['minutes']} min" if d.get("minutes") else "")
    elif tool == "emails":
        what = f"{(d.get('audience') or '?').capitalize()} list" + \
               (f", {d['emails']:,} emails from {d.get('files_read', 0)} files" if "emails" in d else "")
    elif tool == "image-search":
        what = ("uploaded image" if d.get("mode") == "upload" else "pasted link") + \
               (f", {d['matches']} matches" if "matches" in d else "")
    else:
        what = ""
    secs = e.get("seconds")
    return {"when": datetime.fromtimestamp(e["ts"], IST).strftime("%d %b %H:%M"), "tool": TOOLS.get(tool, (tool,))[0],
            "slot": TOOLS.get(tool, (tool, 0))[1], "what": what, "ok": bool(e["ok"]), "error": e.get("error"),
            "took": None if secs is None else (f"{secs:.0f} s" if secs < 120 else f"{secs / 60:.1f} min")}


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

def gate(request: Request):
    """A response to send instead of the page (panel off, or not unlocked), else None."""
    if not admin_password():
        return HTMLResponse("Not found", 404)
    if not unlocked(request):
        return page("admin_unlock.html")
    return None


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def dashboard(request: Request, days: int = 30):
    if (blocked := gate(request)) is not None:
        return blocked
    days = days if days in PERIODS else 30
    since = time.time() - 2 * days * 86400
    local = idr_usage.events_since(since)
    (remote, image_health, remote_problem), health = await asyncio.gather(
        asyncio.to_thread(fetch_image_search, since), asyncio.to_thread(local_health))
    data = summarize(sorted(local + remote, key=lambda e: e["ts"]), days)
    return page("admin.html", tab="tools", periods=PERIODS, health=health, image_health=image_health,
                remote_problem=remote_problem, **data)


@app.get("/search", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def search_tab(request: Request, days: int = 30):
    if (blocked := gate(request)) is not None:
        return blocked
    days = days if days in PERIODS else 30
    since = time.time() - 2 * days * 86400
    connected = [(site, url) for site in SEARCH_SITES if (url := os.environ.get(site["env"], site["default"]))]
    feeds = await asyncio.gather(*(asyncio.to_thread(fetch_search, url, since, days) for _, url in connected))
    sites = [{"key": site["key"], "name": site["name"], "where": site["where"], "health": health, "problem": problem,
              "summary": summarize_search(events, queries, days, site["name"])}
             for (site, _), (events, queries, health, problem) in zip(connected, feeds)]
    not_connected = [site["name"] for site in SEARCH_SITES if site not in [c for c, _ in connected]]
    return page("admin_search.html", tab="search", periods=PERIODS, days=days, sites=sites,
                not_connected=not_connected)


def listening_results(folder=None):
    """Votes from tools.idronline.org/audio-samples/ for the current test, with the answer key."""
    folder = folder or LISTENING_DIR
    try:
        with open(os.path.join(folder, "key.json"), encoding="utf-8") as f:
            key = json.load(f)
    except (OSError, ValueError):
        return None
    votes, comments = Counter(), {}
    db = os.path.join(folder, "votes.db")
    if os.path.exists(db):
        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT voter, lang, letter, name, comment, ts FROM votes WHERE run = ?",
                            (key["run"],)).fetchall()
        conn.close()
        for voter, lang, letter, name, comment, ts in rows:
            votes[(lang, letter)] += 1
            if comment:
                comments[voter] = {"name": name or "Someone", "comment": comment,
                                   "when": datetime.fromtimestamp(ts, IST).strftime("%d %b %H:%M")}
        voters = len({r[0] for r in rows})
    else:
        voters = 0
    languages = []
    for code, lang in key["languages"].items():
        total = sum(votes[(code, letter)] for letter in lang["voices"])
        rows = sorted(({"letter": letter, "votes": votes[(code, letter)], **v} for letter, v in lang["voices"].items()),
                      key=lambda r: (-r["votes"], r["letter"]))
        top = rows[0]["votes"] if rows else 0
        for r in rows:
            r["pct"] = round(r["votes"] / total * 100) if total else 0
            r["leader"] = total > 0 and r["votes"] == top
        languages.append({"code": code, "name": lang["name"], "total": total, "rows": rows})
    return {"run": key["run"], "voters": voters, "languages": languages, "comments": list(comments.values())}


@app.get("/voices", response_class=HTMLResponse, dependencies=[Depends(require_login)])
async def voices_tab(request: Request):
    if (blocked := gate(request)) is not None:
        return blocked
    return page("admin_voices.html", tab="voices", days=30, results=listening_results())


@app.post("/unlock", dependencies=[Depends(require_login)])
async def unlock(request: Request, password: str = Form("")):
    if not admin_password():
        return HTMLResponse("Not found", 404)
    if not secrets.compare_digest(password, admin_password()):
        await asyncio.sleep(1)  # slow down guessing
        return page("admin_unlock.html", 401, error="That admin password is not right. · एडमिन पासवर्ड सही नहीं है।")
    resp = RedirectResponse(prefix(request) + "/", 303)
    resp.set_cookie(ADMIN_COOKIE, _serializer().dumps({"p": _fingerprint()}), max_age=ADMIN_MAX_AGE,
                    path=(prefix(request) or "") + "/", httponly=True, secure=request.url.scheme == "https",
                    samesite="lax")
    return resp


@app.get("/lock")
def lock(request: Request):
    resp = RedirectResponse(prefix(request) + "/", 303)
    resp.delete_cookie(ADMIN_COOKIE, path=(prefix(request) or "") + "/")
    return resp
