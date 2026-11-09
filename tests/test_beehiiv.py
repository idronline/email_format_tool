"""beehiiv: who gets added, whose names change, who is left alone (fake beehiiv, no network)."""

import os
import time

import pytest
from fastapi.testclient import TestClient

from idr_emails import beehiiv, beehiiv_web
from conftest import make_zip

PREF = ["The IDR Weekly", "Off The Record"]


class FakeBeehiiv:
    """In-memory stand-in for beehiiv.Client with the behaviour seen on the real API."""

    def __init__(self, subs=None):
        self.subs = {k.lower(): dict(v) for k, v in (subs or {}).items()}   # email -> {"id","status","custom_fields"}
        self.created, self.updated, self.lookups = [], [], 0

    def find(self, pub_id, email):
        self.lookups += 1
        sub = self.subs.get(email.lower())
        return None if sub is None else dict(sub, email=email)

    def create(self, pub_id, email, fields):
        assert email.lower() not in self.subs, "must never create someone who already exists"
        self.created.append((pub_id, email, fields))
        self.subs[email.lower()] = {"id": f"sub_{len(self.subs)}", "status": "active", "custom_fields": fields}

    def update_fields(self, pub_id, sub_id, fields):
        self.updated.append((pub_id, sub_id, fields))


def sub(sid, status="active", first="", last="", pref=None):
    fields = [{"name": "First Name", "value": first}, {"name": "Last Name", "value": last}]
    if pref is not None:
        fields.append({"name": "Newsletter Preference", "value": pref})
    return {"id": sid, "status": status, "custom_fields": fields}


EXISTING = {
    "same@example.com": sub("s1", first="Asha", last="Rao", pref=["The IDR Weekly"]),
    "rename@example.com": sub("s2", first="R", last="", pref=PREF),
    "gone@example.com": sub("s3", status="inactive", first="Old"),
    "bad@example.com": sub("s4", status="invalid"),
}
ROWS = [("new@example.com", "Nia", "Shah"), ("same@example.com", "Asha", "Rao"),
        ("rename@example.com", "Ravi", "Kumar"), ("gone@example.com", "Gita", ""),
        ("bad@example.com", "", ""), ("noname@example.com", "", "")]


def test_plan_sorts_people_into_the_right_groups():
    plan = beehiiv.check(FakeBeehiiv(EXISTING), "english", ROWS)
    assert [p["action"] for p in plan] == ["new", "same", "rename", "unsubscribed", "other", "new"]
    assert plan[2]["changes"] == [{"name": "First Name", "value": "Ravi"}, {"name": "Last Name", "value": "Kumar"}]
    assert beehiiv.summary(plan) == {"new": 2, "rename": 1, "same": 1, "unsubscribed": 1, "other": 1, "error": 0}


def test_english_new_get_both_newsletters_existing_only_names():
    fake = FakeBeehiiv(EXISTING)
    results = beehiiv.apply(fake, "english", beehiiv.check(fake, "english", ROWS))
    pub, _ = beehiiv.publication("english")
    assert [(e, f) for _, e, f in fake.created] == [
        ("new@example.com", [{"name": "First Name", "value": "Nia"}, {"name": "Last Name", "value": "Shah"},
                             {"name": "Newsletter Preference", "value": PREF}]),
        ("noname@example.com", [{"name": "Newsletter Preference", "value": PREF}])]
    # existing: only the names, never the preference; unsubscribed/invalid untouched
    assert fake.updated == [(pub, "s2", [{"name": "First Name", "value": "Ravi"}, {"name": "Last Name", "value": "Kumar"}])]
    assert [r["outcome"] for r in results] == ["added", "already subscribed", "name updated", "unsubscribed - skipped",
                                               "skipped (invalid)", "added"]


def test_hindi_has_no_newsletter_preference():
    fake = FakeBeehiiv()
    beehiiv.apply(fake, "hindi", beehiiv.check(fake, "hindi", [("x@example.com", "Ek", "")]))
    pub, _ = beehiiv.publication("hindi")
    assert fake.created == [(pub, "x@example.com", [{"name": "First Name", "value": "Ek"}])]


def test_blank_names_never_wipe_existing_names():
    fake = FakeBeehiiv({"a@example.com": sub("s1", first="Asha", last="Rao")})
    plan = beehiiv.check(fake, "english", [("a@example.com", "", "")])
    assert plan[0]["action"] == "same"


def test_someone_who_joins_between_preview_and_send_is_not_created():
    fake = FakeBeehiiv()
    plan = beehiiv.check(fake, "english", [("late@example.com", "Lata", "")])
    assert plan[0]["action"] == "new"
    fake.subs["late@example.com"] = sub("s9", status="inactive")      # unsubscribed meanwhile
    results = beehiiv.apply(fake, "english", plan)
    assert fake.created == [] and results[0]["outcome"] == "unsubscribed - skipped"


def test_lookup_errors_are_reported_not_fatal():
    class Flaky(FakeBeehiiv):
        def find(self, pub_id, email):
            if email.startswith("x"):
                raise beehiiv.BeehiivError("beehiiv answered HTTP 400")
            return super().find(pub_id, email)
    plan = beehiiv.check(Flaky(), "english", [("x@example.com", "", ""), ("y@example.com", "", "")])
    assert [p["action"] for p in plan] == ["error", "new"]
    assert beehiiv.apply(Flaky(), "english", plan)[0]["outcome"] == "not checked"


def test_client_waits_for_the_rate_limit_and_retries_429():
    slept = []
    c = beehiiv.Client("k", sleep=slept.append, now=lambda: 1000)
    replies = iter([(429, {}), (200, {"data": {"id": "s1"}})])
    c._send = lambda *a: next(replies)
    c.reset = 1010
    assert c.request("GET", "/x") == (200, {"data": {"id": "s1"}})
    assert slept and slept[0] >= 10                                     # waited for the window
    c.remaining, c.reset = 1, 1030
    c._send = lambda *a: (200, {})
    c.request("GET", "/y")
    assert slept[-1] == 31


def test_find_returns_none_for_404_and_quotes_the_email():
    c = beehiiv.Client("k", sleep=lambda s: None)
    seen = []
    c._send = lambda method, path, body=None: (seen.append(path), (404, {}))[1]
    assert c.find("pub_1", "a+b@example.com") is None
    assert "by_email/a%2Bb%40example.com" in seen[0]


# ── the web card ─────────────────────────────────────────────────────────────

@pytest.fixture
def web(monkeypatch):
    monkeypatch.setenv("BEEHIIV_API_KEY", "test-key")
    fake = FakeBeehiiv({"ada@example.com": sub("s1", first="Ada", last="")})
    monkeypatch.setattr(beehiiv_web, "make_client", lambda: fake)
    beehiiv_web.BATCHES.clear()
    beehiiv_web.JOBS.clear()
    from idr_emails.web import app
    client = TestClient(app)
    client.fake = fake
    return client


def wait(client, job):
    for _ in range(100):
        d = client.get(f"/beehiiv/jobs/{job}").json()
        if d["state"] != "running":
            return d
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_result_page_card_preview_then_send(web):
    z = make_zip({"a.csv": "email,First Name,Last Name\nada@example.com,ada,lovelace\nnew@example.org,Nia,\n"})
    page = web.post("/", files={"zipfile": ("in.zip", z)}, data={"audience": "english"}).text
    assert "Add to beehiiv" in page and "The IDR Weekly" in page
    batch = page.split('data-batch="')[1].split('"')[0]
    d = wait(web, web.post("/beehiiv/check", data={"batch": batch}).json()["job"])
    assert d["summary"]["new"] == 1 and d["summary"]["rename"] == 1        # Ada gets her last name
    assert web.fake.created == [] and web.fake.updated == []              # the check changes nothing
    check_job = next(j for j, v in beehiiv_web.JOBS.items() if v["kind"] == "check")
    first = web.post("/beehiiv/apply", data={"job": check_job}).json()["job"]
    again = web.post("/beehiiv/apply", data={"job": check_job}).json()["job"]
    assert first == again                                                 # pressing twice runs once
    done = wait(web, first)
    assert done["counts"] == {"name updated": 1, "added": 1}
    assert "new@example.org,added" in done["csv"]
    assert [e for _, e, _ in web.fake.created] == ["new@example.org"]


def test_no_card_without_api_key(monkeypatch):
    monkeypatch.delenv("BEEHIIV_API_KEY", raising=False)
    from idr_emails.web import app
    z = make_zip({"a.csv": "email\nx@example.com\n"})
    assert "Add to beehiiv" not in TestClient(app).post("/", files={"zipfile": ("in.zip", z)},
                                                         data={"audience": "hindi"}).text


def test_expired_and_unchecked(web):
    assert web.post("/beehiiv/check", data={"batch": "nope"}).status_code == 404
    assert web.post("/beehiiv/apply", data={"job": "nope"}).status_code == 400
    assert web.get("/beehiiv/jobs/nope").status_code == 404
    beehiiv_web.BATCHES["old"] = {"audience": "english", "rows": [], "created": time.time() - 2 * beehiiv_web.KEEP_SECONDS}
    beehiiv_web._forget_old()
    assert "old" not in beehiiv_web.BATCHES


def test_rules_card_only_when_beehiiv_is_connected(web, monkeypatch):
    html = web.get("/").text
    assert "How beehiiv is updated" in html and "beehiiv कैसे अपडेट होता है" in html
    assert "never added back" in html and "दोबारा नहीं जोड़ा जाता" in html
    monkeypatch.delenv("BEEHIIV_API_KEY")
    assert "How beehiiv is updated" not in web.get("/").text
