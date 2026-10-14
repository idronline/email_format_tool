"""Shared IDR tools login, FastAPI version (the Flask tools use idr_login.py).

Same rules and the same cookie as the other tools on this server, so one sign-in
works for all of them:
- APP_USERNAME / APP_PASSWORD from the environment; login is off if either is unset.
- "idr_login" cookie for path "/", signed with SECRET_KEY (shared idr-tools.env).
- Changing APP_PASSWORD signs everyone out.
Behind nginx the tool lives under a path (X-Forwarded-Prefix, e.g. /emails).
"""

import asyncio
import hashlib
import html
import os
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

COOKIE = "idr_login"
MAX_AGE = 14 * 24 * 3600
LOGIN_PAGE = (Path(__file__).parent / "login.html").read_text(encoding="utf-8")

router = APIRouter()


def credentials():
    user, pw = os.environ.get("APP_USERNAME"), os.environ.get("APP_PASSWORD")
    return (user, pw) if user and pw else (None, None)


def login_enabled():
    return credentials()[0] is not None


def _serializer(user, pw):
    key = os.environ.get("SECRET_KEY") or hashlib.sha256(f"idr-tools|{user}|{pw}".encode()).hexdigest()
    return URLSafeTimedSerializer(key, salt="idr-login")


def _fingerprint(pw):
    return hashlib.sha256(pw.encode()).hexdigest()[:16]


def prefix(request: Request):
    """Path this tool is served under, e.g. '/emails' behind nginx, '' when run directly."""
    p = request.headers.get("x-forwarded-prefix", "").rstrip("/")
    return p if p.startswith("/") or p == "" else ""


def signed_in(request: Request):
    user, pw = credentials()
    if user is None:
        return True
    try:
        data = _serializer(user, pw).loads(request.cookies.get(COOKIE, ""), max_age=MAX_AGE)
    except BadSignature:
        return False
    return data.get("u") == user and data.get("p") == _fingerprint(pw)


def require_login(request: Request):
    """Route dependency: send people who are not signed in to the login page."""
    if not signed_in(request):
        nxt = prefix(request) + request.url.path
        raise HTTPException(303, headers={"Location": f"{prefix(request)}/login?next={quote(nxt, safe='/')}"})


def _safe_next(request, target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return prefix(request) + "/"


def _login_page(nav_html, error="", nxt="/", username=""):
    err = f'<div class="warn" style="background:var(--pale-red);border-left-color:var(--red)">{html.escape(error)}</div>' if error else ""
    return (LOGIN_PAGE.replace("<!-- NAV -->", nav_html).replace("<!-- ERROR -->", err)
            .replace("{{next}}", html.escape(nxt, quote=True)).replace("{{username}}", html.escape(username, quote=True))
            .replace("{{autofocus_user}}", "" if username else "autofocus")
            .replace("{{autofocus_pw}}", "autofocus" if username else ""))


def make_routes(nav_html):
    @router.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = ""):
        nxt = _safe_next(request, next)
        if not login_enabled():
            return RedirectResponse(nxt, 303)
        return HTMLResponse(_login_page(nav_html(), nxt=nxt))

    @router.post("/login", response_class=HTMLResponse)
    async def login_submit(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("")):
        user, pw = credentials()
        nxt = _safe_next(request, next)
        if user is None:
            return RedirectResponse(nxt, 303)
        ok = secrets.compare_digest(username, user) & secrets.compare_digest(password, pw)
        if not ok:
            await asyncio.sleep(1)  # slow down password guessing
            return HTMLResponse(_login_page(nav_html(), "That username or password is not right. · यूज़रनेम या पासवर्ड सही नहीं है।", nxt, username), 401)
        resp = RedirectResponse(nxt, 303)
        resp.set_cookie(COOKIE, _serializer(user, pw).dumps({"u": user, "p": _fingerprint(pw)}), max_age=MAX_AGE,
                        path="/", httponly=True, secure=request.url.scheme == "https", samesite="lax")
        return resp

    @router.get("/logout")
    def logout(request: Request):
        resp = RedirectResponse(prefix(request) + "/login", 303)
        resp.delete_cookie(COOKIE, path="/")
        return resp

    return router
