"""The "Add to beehiiv" card under an Email Collector result.

Flow: the result page starts a read-only check of every collected email against
beehiiv (a background job with a progress bar), shows what would happen, and only
after someone presses the button adds the new people / updates names (another job).

The collected list (emails and names) is kept in memory only, for at most an hour,
so the check and the button can work on it; it is never written to disk.
"""

import csv
import io
import secrets
import threading
import time

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse

from . import beehiiv
from .login import require_login

KEEP_SECONDS = 3600
BATCHES = {}          # batch id -> {"audience", "rows": [(email, first, last)], "created"}
JOBS = {}             # job id -> {"kind": "check"|"apply", "batch", "state", "done", "total", ...}
LOCK = threading.Lock()

router = APIRouter(dependencies=[Depends(require_login)])


def make_client():
    return beehiiv.Client(beehiiv.api_key())


def enabled():
    return beehiiv.api_key() is not None


def _forget_old():
    cutoff = time.time() - KEEP_SECONDS
    with LOCK:
        for store in (BATCHES, JOBS):
            for k in [k for k, v in store.items() if v["created"] < cutoff]:
                del store[k]


def remember(audience, rows):
    """Keep a collected list for the beehiiv card; returns its id."""
    _forget_old()
    batch = secrets.token_urlsafe(12)
    with LOCK:
        BATCHES[batch] = {"audience": audience, "rows": list(rows), "created": time.time()}
    return batch


def _update(job_id, **fields):
    with LOCK:
        JOBS[job_id].update(fields)


def _start(kind, batch, total, target, **extra):
    job_id = secrets.token_urlsafe(12)
    with LOCK:
        JOBS[job_id] = {"kind": kind, "batch": batch, "state": "running", "done": 0, "total": total,
                        "created": time.time(), **extra}
    threading.Thread(target=target, args=(job_id,), daemon=True).start()
    return job_id


def _run_check(job_id):
    job = JOBS[job_id]
    b = BATCHES[job["batch"]]
    try:
        plan = beehiiv.check(make_client(), b["audience"], b["rows"], progress=lambda n: _update(job_id, done=n))
        _update(job_id, state="done", plan=plan)
    except Exception as e:  # noqa: BLE001 - shown on the page
        _update(job_id, state="error", error=str(e) or type(e).__name__)


def _run_apply(job_id):
    job = JOBS[job_id]
    check_job = JOBS[job["check"]]
    try:
        results = beehiiv.apply(make_client(), BATCHES[job["batch"]]["audience"], check_job["plan"],
                                progress=lambda n: _update(job_id, done=n))
        _update(job_id, state="done", results=results)
    except Exception as e:  # noqa: BLE001
        _update(job_id, state="error", error=str(e) or type(e).__name__)


def results_csv(results):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["email", "beehiiv result", "error"])
    for r in results:
        w.writerow([r["email"], r["outcome"], r["error"] or ""])
    return out.getvalue()


@router.post("/beehiiv/check")
def start_check(batch: str = Form(...)):
    if not enabled():
        return JSONResponse({"error": "beehiiv is not set up (BEEHIIV_API_KEY)."}, 400)
    with LOCK:
        b = BATCHES.get(batch)
    if not b:
        return JSONResponse({"error": "This list has expired. Please upload the zip again."}, 404)
    return {"job": _start("check", batch, len(b["rows"]), _run_check)}


@router.post("/beehiiv/apply")
def start_apply(job: str = Form(...)):
    with LOCK:
        check_job = JOBS.get(job)
        if not check_job or check_job["kind"] != "check" or check_job["state"] != "done":
            return JSONResponse({"error": "Check the list against beehiiv first."}, 400)
        if check_job.get("apply"):                       # pressed twice: show the same run
            return {"job": check_job["apply"]}
        if check_job["batch"] not in BATCHES:
            return JSONResponse({"error": "This list has expired. Please upload the zip again."}, 404)
        batch, total = check_job["batch"], len(check_job["plan"])
        check_job["apply"] = "starting"                  # blocks a second press while starting
    apply_id = _start("apply", batch, total, _run_apply, check=job)
    with LOCK:
        check_job["apply"] = apply_id
    return {"job": apply_id}


@router.get("/beehiiv/jobs/{job_id}")
def job_status(job_id: str):
    with LOCK:
        job = dict(JOBS.get(job_id) or {})
    if not job:
        return JSONResponse({"state": "missing", "error": "This list has expired. Please upload the zip again."}, 404)
    out = {k: job.get(k) for k in ("kind", "state", "done", "total", "error")}
    if job["state"] == "done" and job["kind"] == "check":
        out["summary"] = beehiiv.summary(job["plan"])
        out["errors"] = sorted({p["error"] for p in job["plan"] if p["action"] == "error"})[:3]
    if job["state"] == "done" and job["kind"] == "apply":
        counts = {}
        for r in job["results"]:
            counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
        out["counts"] = counts
        out["csv"] = results_csv(job["results"])
    return out


def card(batch, audience, rows):
    """HTML for the beehiiv card on the result page (the script drives it)."""
    _, pub_name = beehiiv.publication(audience)
    minutes = max(1, round(rows / beehiiv.REQUESTS_PER_MINUTE))
    english = audience == "english"
    rules = ("New subscribers get both newsletters (The IDR Weekly, Off The Record). People already in beehiiv keep "
             "their choices; only their names are updated. Unsubscribed people are skipped. No welcome email."
             if english else
             "New subscribers are added with their names. People already in beehiiv only get their names updated. "
             "Unsubscribed people are skipped. No welcome email.")
    rules_hi = ("नए सब्सक्राइबर्स को दोनों न्यूज़लेटर मिलेंगे। पहले से मौजूद लोगों की पसंद नहीं बदलेगी, सिर्फ़ नाम अपडेट होंगे। "
                "अनसब्सक्राइब कर चुके लोगों को छोड़ दिया जाएगा।" if english else
                "नए सब्सक्राइबर्स नाम के साथ जुड़ेंगे। पहले से मौजूद लोगों के सिर्फ़ नाम अपडेट होंगे। अनसब्सक्राइब कर चुके लोगों को छोड़ दिया जाएगा।")
    return f"""
<section class="card result" id="bh" data-batch="{batch}">
  <div class="done-head"><div class="tick" style="background:var(--black);font-size:1rem">b</div>
    <div><h2>Add to beehiiv<span class="hi" lang="hi">beehiiv में जोड़ें</span></h2>
      <p>Publication: {pub_name} &middot; {rows:,} emails &middot; checking takes about {minutes} min</p></div></div>
  <p class="hint" style="margin-top:0">{rules}<span class="hi" lang="hi">{rules_hi}</span></p>
  <div id="bh-body"></div>
</section>
<script>
(function () {{
  var box = document.getElementById('bh'), body = document.getElementById('bh-body');
  function bi(en, hi) {{ return en + '<span class="hi" lang="hi">' + hi + '</span>'; }}
  function esc(s) {{ return String(s).replace(/[&<>"]/g, function (c) {{ return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]; }}); }}
  function fail(msg) {{ body.innerHTML = '<div class="warn" style="background:var(--pale-red);border-left-color:var(--red)">' + esc(msg) + '</div>'; }}
  function post(url, data) {{
    var fd = new FormData(); for (var k in data) fd.append(k, data[k]);
    return fetch(url, {{method: 'POST', body: fd, headers: {{'Accept': 'application/json'}}}})
      .then(function (r) {{ return r.json().catch(function () {{ throw new Error('Please sign in again and reload.'); }}); }});
  }}
  function bar(done, total, en, hi) {{
    var pct = Math.round(100 * done / Math.max(1, total));
    body.innerHTML = '<div class="working"><div class="spinner"></div><div style="flex:1">' + bi(en, hi) +
      '<div style="height:8px;background:var(--light-grey);border-radius:999px;margin:.5rem 0;overflow:hidden">' +
      '<div style="height:100%;width:' + pct + '%;background:var(--red)"></div></div>' +
      '<span class="hint">' + done + ' / ' + total + '</span></div></div>';
  }}
  function poll(job, onDone) {{
    fetch('beehiiv/jobs/' + job, {{headers: {{'Accept': 'application/json'}}}}).then(function (r) {{ return r.json(); }}).then(function (d) {{
      if (d.state === 'running') {{
        if (d.kind === 'check') bar(d.done, d.total, 'Checking these emails in beehiiv…', 'beehiiv में मिलान हो रहा है…');
        else bar(d.done, d.total, 'Updating beehiiv…', 'beehiiv अपडेट हो रहा है…');
        setTimeout(function () {{ poll(job, onDone); }}, 2000);
      }} else if (d.state === 'done') onDone(d);
      else fail(d.error || 'Something went wrong.');
    }}).catch(function () {{ setTimeout(function () {{ poll(job, onDone); }}, 5000); }});
  }}
  function tile(n, en, hi) {{ return '<div class="stat"><b>' + n.toLocaleString() + '</b><span>' + bi(en, hi) + '</span></div>'; }}
  function preview(job, d) {{
    var s = d.summary, skipped = s.unsubscribed + s.other;
    var html = '<div class="stats">' + tile(s.new, 'new — will be added', 'नए — जोड़े जाएंगे') +
      tile(s.rename + s.same, 'already subscribed', 'पहले से सब्सक्राइब्ड') +
      tile(s.rename, 'of them: names to update', 'इनमें से नाम अपडेट होंगे') +
      tile(skipped, 'unsubscribed or invalid — skipped', 'अनसब्सक्राइब्ड/अमान्य — छोड़े गए') + '</div>';
    if (s.error) html += '<div class="warn">' + s.error + ' emails could not be checked and will be left out. ' + esc((d.errors || []).join('; ')) + '</div>';
    if (s.new + s.rename === 0) {{ body.innerHTML = html + '<p class="hint">' + bi('Nothing to change in beehiiv.', 'beehiiv में कुछ बदलना नहीं है।') + '</p>'; return; }}
    html += '<button type="button" class="btn btn-primary" id="bh-go">' +
      bi('Add ' + s.new.toLocaleString() + ' new and update ' + s.rename.toLocaleString() + ' names in beehiiv',
         'beehiiv में ' + s.new.toLocaleString() + ' नए जोड़ें और ' + s.rename.toLocaleString() + ' नाम अपडेट करें') + '</button>';
    body.innerHTML = html;
    document.getElementById('bh-go').addEventListener('click', function () {{
      this.disabled = true;
      post('beehiiv/apply', {{job: job}}).then(function (r) {{
        if (r.error) return fail(r.error);
        poll(r.job, finished);
      }}).catch(function (e) {{ fail(e.message); }});
    }});
  }}
  function finished(d) {{
    var c = d.counts, parts = [];
    for (var k in c) parts.push('<b>' + c[k].toLocaleString() + '</b> ' + esc(k));
    var href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(d.csv);
    body.innerHTML = '<div class="done-head" style="border:0;margin:0"><div class="tick">&#10003;</div><div><h2>' +
      bi('beehiiv is updated', 'beehiiv अपडेट हो गया') + '</h2><p>' + parts.join(' &middot; ') + '</p></div></div>' +
      '<a download="beehiiv_results.csv" href="' + href + '">' + bi('Download what happened to each email (CSV)', 'हर ईमेल का नतीजा डाउनलोड करें (CSV)') + '</a>';
  }}
  post('beehiiv/check', {{batch: box.dataset.batch}}).then(function (r) {{
    if (r.error) return fail(r.error);
    poll(r.job, function (d) {{ preview(r.job, d); }});
  }}).catch(function (e) {{ fail(e.message); }});
}})();
</script>"""
