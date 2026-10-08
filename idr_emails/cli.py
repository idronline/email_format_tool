"""Command-line entry point."""

import argparse
import csv

from . import NEWSLETTER_PREF, OUT_COLUMNS
from .collector import collect


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Collect emails from a zip of mixed files.")
    ap.add_argument("zipfile", help="path to the input .zip")
    ap.add_argument("-o", "--output", default="subscribers.csv", help="output CSV (default: subscribers.csv)")
    ap.add_argument("--log", default="collect_emails_log.csv", help="per-file log (default: collect_emails_log.csv)")
    args = ap.parse_args(argv)

    found, log = collect(args.zipfile)

    emails = sorted(found)
    write_csv(args.output, OUT_COLUMNS,
              ([e, found[e]["first"], found[e]["last"], NEWSLETTER_PREF] for e in emails))
    write_csv(args.log, ["file", "status", "detail"], log)

    ok = sum(1 for _, s, _ in log if s == "OK")
    bad = [(f, s, d) for f, s, d in log if s != "OK"]
    print(f"Files read OK : {ok}")
    print(f"Unique emails : {len(emails)}  ->  {args.output}")
    print(f"Per-file log  : {args.log}")
    if bad:
        print(f"\n{len(bad)} file(s) skipped or failed:")
        for f, s, d in bad:
            print(f"  [{s}] {f} - {d}")
