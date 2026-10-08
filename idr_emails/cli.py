"""Command-line entry point."""

import argparse

from . import NEWSLETTER_PREF, OUT_COLUMNS
from .collector import collect
from .reports import write_csv, write_reports


def main(argv=None):
    ap = argparse.ArgumentParser(description="Collect emails from a zip of mixed files.")
    ap.add_argument("zipfile", help="path to the input .zip")
    ap.add_argument("-o", "--output", default="subscribers.csv", help="output CSV (default: subscribers.csv)")
    ap.add_argument("--log", default="collect_emails_log.csv", help="per-file log (default: collect_emails_log.csv)")
    ap.add_argument("--report-dir", metavar="DIR",
                    help="also write missing_names.csv and per_file_summary.csv into DIR")
    args = ap.parse_args(argv)

    found, log, stats = collect(args.zipfile)

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
    if args.report_dir:
        for path in write_reports(args.report_dir, found, stats):
            print(f"Report        : {path}")
    if bad:
        print(f"\n{len(bad)} file(s) skipped or failed:")
        for f, s, d in bad:
            print(f"  [{s}] {f} - {d}")
