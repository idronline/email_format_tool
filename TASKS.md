# IDR tools – open tasks

One list for all the IDR tools (Translate, Audio, Email Collector, Image Search, admin panel)
and their two servers. Update it whenever something is decided, started or finished:
move finished items to **Done**, dropped ones to **Decided against** (with the reason), and
change the date below. Keep keys, passwords and personal email addresses out of this file.

_Last updated: 2026-11-10_

Servers: **tools server** (Translate, Audio, Email Collector, admin panel – `tools.idronline.org`)
and **search server** (Image Search, Hindi search, English search – `api.idronline.org`).

---

## Waiting on the team / Subhash

| # | Task | Waiting for | Next step once it arrives |
|---|------|-------------|---------------------------|
| 1 | **Pick the Audio voices** from the listening test (`tools.idronline.org/audio-samples/`) | Enough votes per language (admin panel → **Voices** tab) | Set Audio to the winning voice per language. If Chirp 3 HD wins, first check that heading pauses and `pronunciations.txt` still work with it. Then delete `~/listening-test` on the tools server. |
| 2 | **Pronunciation list** for Audio (`audio_generation/pronunciations.txt`, only examples so far) | Words/names the voice gets wrong, from the team | Add them as `language \| written \| spoken`, push, `idr-deploy`. |
| 3 | **Translate glossary** | Mapping file: English article URL ↔ Hindi / Bengali / Kannada / Marathi versions | Pair articles, draft a glossary per language (Hindi first) for an editor to approve, connect it to Translate, compare before/after. |
| 4 | **beehiiv go-live** | `BEEHIIV_API_KEY` in `~/idr-tools.env` on the tools server, then `idr-deploy` | Run one small real list through "Add to beehiiv" and read its result CSV. Adding a *brand-new* subscriber was only tested with a stand-in (live tests used existing addresses). |
| 5 | **S3 auto-cleanup** on bucket `idrtranslatedfiles` | Lifecycle rule in the AWS console (not confirmed done) | Rule "delete after 30 days" on all objects. Note: download links stop working after 30 days. |

## Ready to build (say the word)

| # | Task | Notes |
|---|------|-------|
| 6 | **Translate: Google vs Claude blind test** | 3–4 recent articles, side-by-side sheet for an editor, unlabelled. Earlier test: Claude made no narrator-gender mistakes, Google 2; scores close. |
| 7 | **Translate: several languages per upload; long documents in the background** | Same progress-bar pattern as Audio. |
| 8 | **Admin panel, next parts** | Google/S3 costs; editor for the pronunciation list (no git needed); "run Image Search update now" button; count beehiiv sends in usage. |
| 9 | **Fewer false alarms** | Slack alert only after two failed checks in a row. |

## Parked / later

| # | Task | When |
|---|------|------|
| 10 | **Image Search backups** – built, switched off | Turn on with `BACKUP_ENABLED=1` (+ `BACKUP_S3_BUCKET` and an IAM role for off-server copies). |
| 11 | **Move the tools server to Ubuntu 24.04 (Python 3.12)** | Before **April 2027** (end of Ubuntu 22.04 standard support). Use the side-by-side venv steps; keep old venvs for rollback. |

## Housekeeping (small, unconfirmed)

- [ ] Image Search weekly update: check the **English** exports work again on Sunday 2026-11-15 (admin panel → Health, or
      `grep 'English' ~/idr-image-search/logs/weekly_update.log | tail`). On 2026-11-08 idronline.org answered 403 to the export
      *trigger* for all four English exports; the search server's IP has since been whitelisted. Quick test any time:
      `venv/bin/python weekly_update.py --only English-Articles.csv`.
- [ ] Search server: reboot if it still shows "System restart required" (not during the Sunday update).
- [ ] Search server: delete unused `~/hindi-image-search` (check nothing runs from it first).
- [ ] Search server: check `exports.json` includes the Hindi site's exports, so Hindi images are indexed each Sunday.
- [ ] Tools server: confirm the health check's first scheduled runs in `~/idr-health.log`.
- [ ] Laptop: delete `email_format_tool/beehiiv_api.txt` once the key is on the server (git ignores it).

---

## Decided against (don't re-propose without a new reason)

| What | Why / when |
|------|------------|
| Email Collector → **Listmonk** | Cancelled for good (Nov 2026); IDR uses **beehiiv** (built instead). |
| **IndicTrans2** for translation | Tested Oct 2026: weaker than Google on every comparison and kept making a woman narrator masculine. Models deleted. |
| "Paste a link" safety fix in Image Search | Only the editorial team uses it (Oct 2026). Revisit if the password is shared wider or the search server gets AWS permissions. |
| Upgrading Python on the tools server now | Stay on Ubuntu's Python 3.10 (still gets security fixes) until the OS upgrade (#11). |
| Moving Image Search onto the tools server | Too big (model, index, weekly indexing). It stays on the search server; tools.idronline.org passes `/image-search/` through. |
| Female/male choice with basic Standard voices in Audio | Team preferred Google's default voice per language (reverted Oct 2026); the listening test (#1) decides any change. |
| "One sign-in works for every tool" line on the sign-in page | Removed at the team's request. |

## Done (recent)

- 2026-11-09 Email Collector → **beehiiv**: preview, then a button; rules card in English + Hindi. Verified live that beehiiv's "create" overwrites existing subscribers, so the tool never creates someone who exists.
- 2026-11-09 Health checks fixed: each server checks its own tools (search server had been checking the tools server's tools, causing false alerts).
- 2026-10/11 Audio **listening test** with voting at `/audio-samples/`; results in admin → Voices.
- 2026-10 **Admin panel** at `/admin/` (second password): usage, problems, health; Search and Voices tabs.
- 2026-10 Audio back to Google's default voice; background jobs with progress bar; heading pauses; pronunciation list; Kannada.
- 2026-10 Tests for Translate and Audio; GitHub Actions on all three repos; shared files with one master copy (`shared/sync.sh`).
- 2026-10 `idr-deploy` on both servers; Slack alerts; single sign-in across `tools.idronline.org`; new look with Hindi text; S3 cleanup of old translation/audio files (334 files).
