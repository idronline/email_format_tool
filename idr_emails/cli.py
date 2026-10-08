"""Command-line entry point."""

import argparse

from . import NEWSLETTER_PREF, OUT_COLUMNS
from .checks import apply_typo_fixes, find_suspicious
from .collector import collect, emails_in_file
from .reports import write_csv, write_reports


def main(argv=None):
    ap = argparse.ArgumentParser(description="Collect emails from a zip of mixed files.")
    ap.add_argument("zipfile", help="path to the input .zip")
    ap.add_argument("-o", "--output", default="subscribers.csv", help="output CSV (default: subscribers.csv)")
    ap.add_argument("--log", default="collect_emails_log.csv", help="per-file log (default: collect_emails_log.csv)")
    ap.add_argument("--report-dir", metavar="DIR",
                    help="also write missing_names.csv, per_file_summary.csv and suspicious_emails.csv into DIR")
    ap.add_argument("--fix-typos", action="store_true",
                    help="rewrite likely domain typos (e.g. gmial.com -> gmail.com) in the output")
    ap.add_argument("--exclude", metavar="FILE", action="append", default=[],
                    help="suppression list: drop every email found in FILE (csv/xlsx/zip). Repeatable")
    args = ap.parse_args(argv)

    suppressed = set()
    for path in args.exclude:
        suppressed |= emails_in_file(path)

    found, log, stats = collect(args.zipfile)
    suspicious = find_suspicious(found)
    fixed = apply_typo_fixes(found, suspicious) if args.fix_typos else 0
    excluded = [e for e in found if e in suppressed]
    for e in excluded:
        del found[e]

    emails = sorted(found)
    write_csv(args.output, OUT_COLUMNS,
              ([e, found[e]["first"], found[e]["last"], NEWSLETTER_PREF] for e in emails))
    write_csv(args.log, ["file", "status", "detail"], log)

    ok = sum(1 for _, s, _ in log if s == "OK")
    bad = [(f, s, d) for f, s, d in log if s != "OK"]
    print(f"Files read OK : {ok}")
    print(f"Unique emails : {len(emails)}  ->  {args.output}")
    print(f"Per-file log  : {args.log}")
    no_name = sum(1 for r in found.values() if not r["first"] and not r["last"])
    print(f"Without a name: {no_name}")
    print(f"Suspicious    : {len({r[0] for r in suspicious})}"
          + ("" if args.report_dir else "  (see --report-dir for details)"))
    if args.fix_typos:
        print(f"Typos fixed   : {fixed}")
    if args.exclude:
        print(f"Excluded      : {len(excluded)} already on the suppression list ({len(suppressed)} emails)")
    if args.report_dir:
        for path in write_reports(args.report_dir, found, stats, suspicious):
            print(f"Report        : {path}")
    if bad:
        print(f"\n{len(bad)} file(s) skipped or failed:")
        for f, s, d in bad:
            print(f"  [{s}] {f} - {d}")
