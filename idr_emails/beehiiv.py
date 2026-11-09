"""Send a collected list to beehiiv: add new people, update names of existing ones.

Rules (agreed with the newsletter team; verified against the live API in Nov 2026):
- Everyone is looked up first. Only people who are NOT in beehiiv at all are added.
  (Creating a subscriber who already exists overwrites their fields - e.g. it would
  reset someone's Newsletter Preference - so existing people are never "created".)
- New English subscribers get Newsletter Preference = both newsletters; new Hindi
  subscribers get names only. No welcome email, no confirmation email (active at once).
- Existing subscribers keep everything; only First Name / Last Name are updated, and
  only when the list has a non-empty name that differs. Updating a name leaves the
  other fields untouched.
- Unsubscribed people (status "inactive") are never touched or re-subscribed.

BEEHIIV_API_KEY comes from the environment (~/idr-tools.env on the server).
Publication IDs can be overridden with BEEHIIV_PUB_ENGLISH / BEEHIIV_PUB_HINDI.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import AUDIENCES

API = "https://api.beehiiv.com/v2"
PUBLICATIONS = {
    "english": ("BEEHIIV_PUB_ENGLISH", "pub_632433f6-7cf0-40cd-a764-ae908929bb3c", "The IDR Weekly"),
    "hindi": ("BEEHIIV_PUB_HINDI", "pub_90e68c67-b167-4a5a-95dd-47512e85a832", "आईडीआर हिंदी"),
}
PREFERENCE_FIELD = "Newsletter Preference"
SKIP_STATUSES = {"invalid", "unset"}            # can't or shouldn't be written to
REQUESTS_PER_MINUTE = 180                       # beehiiv's limit on IDR's plan (for time estimates)


def api_key():
    return os.environ.get("BEEHIIV_API_KEY") or None


def publication(audience):
    env, default, name = PUBLICATIONS[audience]
    return os.environ.get(env) or default, name


def preference(audience):
    """Newsletter Preference values for new subscribers, from the same setting as the CSV."""
    return [p.strip() for p in AUDIENCES[audience].split(",") if p.strip()]


class BeehiivError(Exception):
    pass


class Client:
    """Small beehiiv API client that waits instead of hitting the rate limit."""

    def __init__(self, key, sleep=time.sleep, now=time.time):
        self.key, self.sleep, self.now = key, sleep, now
        self.remaining, self.reset = None, 0

    def _send(self, method, path, body=None):
        req = urllib.request.Request(API + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                                              "Accept": "application/json", "User-Agent": "idr-email-collector"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self._note_limits(resp.headers)
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            self._note_limits(e.headers or {})
            try:
                data = json.load(e)
            except Exception:  # noqa: BLE001
                data = {}
            return e.code, data

    def _note_limits(self, headers):
        try:
            self.remaining = int(headers.get("RateLimit-Remaining"))
            self.reset = float(headers.get("RateLimit-Reset"))
        except (TypeError, ValueError):
            pass

    def request(self, method, path, body=None):
        """(status, data). Waits for the rate-limit window and retries 429 / 5xx / network errors."""
        for attempt in range(6):
            if self.remaining is not None and self.remaining <= 1:
                self.sleep(min(65, max(1, self.reset - self.now() + 1)))
                self.remaining = None
            try:
                status, data = self._send(method, path, body)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt == 5:
                    raise BeehiivError(f"beehiiv could not be reached ({e})") from e
                self.sleep(2 ** attempt)
                continue
            if status == 429 or status >= 500:
                if attempt == 5:
                    break
                self.sleep(min(65, max(2 ** attempt, self.reset - self.now() + 1)) if status == 429 else 2 ** attempt)
                continue
            return status, data
        raise BeehiivError(f"beehiiv kept answering HTTP {status}")

    def find(self, pub_id, email):
        """The subscription (with custom fields) or None if this email isn't in the publication."""
        status, data = self.request("GET", f"/publications/{pub_id}/subscriptions/by_email/"
                                           f"{urllib.parse.quote(email, safe='')}?expand[]=custom_fields")
        if status == 404:
            return None
        if status != 200:
            raise BeehiivError(_message(status, data))
        return data["data"]

    def create(self, pub_id, email, fields):
        status, data = self.request("POST", f"/publications/{pub_id}/subscriptions", {
            "email": email, "reactivate_existing": False, "send_welcome_email": False,
            "double_opt_override": "off", "utm_source": "idr-email-collector", "custom_fields": fields})
        if status not in (200, 201):
            raise BeehiivError(_message(status, data))
        return data

    def update_fields(self, pub_id, sub_id, fields):
        status, data = self.request("PUT", f"/publications/{pub_id}/subscriptions/{sub_id}", {"custom_fields": fields})
        if status != 200:
            raise BeehiivError(_message(status, data))
        return data


def _message(status, data):
    errors = (data or {}).get("errors") if isinstance(data, dict) else None
    detail = "; ".join(e.get("message", "") for e in errors) if errors else ""
    return f"beehiiv answered HTTP {status}" + (f": {detail}" if detail else "")


def _fields(sub):
    return {f.get("name"): f.get("value") for f in (sub.get("custom_fields") or [])}


def name_changes(sub, first, last):
    """Custom fields to send so the names match the list (non-empty values that differ)."""
    current = _fields(sub)
    return [{"name": n, "value": v} for n, v in (("First Name", first), ("Last Name", last))
            if v and v != (current.get(n) or "")]


def new_fields(audience, first, last):
    fields = [{"name": n, "value": v} for n, v in (("First Name", first), ("Last Name", last)) if v]
    if preference(audience):
        fields.append({"name": PREFERENCE_FIELD, "value": preference(audience)})
    return fields


def classify(sub, first, last):
    """What to do with one person, from their beehiiv record (None = not in beehiiv)."""
    if sub is None:
        return "new", None, []
    status = sub.get("status")
    if status == "inactive":
        return "unsubscribed", sub.get("id"), []
    if status in SKIP_STATUSES:
        return "other", sub.get("id"), []
    changes = name_changes(sub, first, last)
    return ("rename" if changes else "same"), sub.get("id"), changes


def check(client, audience, rows, progress=None):
    """Look everyone up (read-only). rows: [(email, first, last)]. Returns the plan."""
    pub_id, _ = publication(audience)
    plan = []
    for i, (email, first, last) in enumerate(rows, 1):
        try:
            sub = client.find(pub_id, email)
            action, sub_id, changes = classify(sub, first, last)
            plan.append({"email": email, "first": first, "last": last, "action": action, "id": sub_id,
                         "changes": changes, "status": None if sub is None else sub.get("status")})
        except BeehiivError as e:
            plan.append({"email": email, "first": first, "last": last, "action": "error", "error": str(e)})
        if progress:
            progress(i)
    return plan


def apply(client, audience, plan, progress=None):
    """Add the new people and update names, re-checking each new person first. Returns results."""
    pub_id, _ = publication(audience)
    results = []
    for i, p in enumerate(plan, 1):
        outcome, error = p["action"], None
        try:
            if p["action"] == "new":
                sub = client.find(pub_id, p["email"])          # may have changed since the preview
                if sub is None:
                    client.create(pub_id, p["email"], new_fields(audience, p["first"], p["last"]))
                    outcome = "added"
                else:
                    action, sub_id, changes = classify(sub, p["first"], p["last"])
                    if action == "rename":
                        client.update_fields(pub_id, sub_id, changes)
                        outcome = "name updated"
                    else:
                        outcome = {"same": "already subscribed", "unsubscribed": "unsubscribed - skipped"}.get(
                            action, "skipped")
            elif p["action"] == "rename":
                client.update_fields(pub_id, p["id"], p["changes"])
                outcome = "name updated"
            else:
                outcome = {"same": "already subscribed", "unsubscribed": "unsubscribed - skipped",
                           "other": f"skipped ({p.get('status')})", "error": "not checked"}[p["action"]]
                error = p.get("error")
        except BeehiivError as e:
            outcome, error = "failed", str(e)
        results.append({"email": p["email"], "outcome": outcome, "error": error})
        if progress:
            progress(i)
    return results


def summary(plan):
    counts = {}
    for p in plan:
        counts[p["action"]] = counts.get(p["action"], 0) + 1
    return {"new": counts.get("new", 0), "rename": counts.get("rename", 0), "same": counts.get("same", 0),
            "unsubscribed": counts.get("unsubscribed", 0), "other": counts.get("other", 0),
            "error": counts.get("error", 0)}
