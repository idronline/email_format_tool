"""Command-line entry point."""

import argparse
from pathlib import Path

from . import AUDIENCES
from .pipeline import run
from .reports import write_csv

REPORT_NAMES = ["missing_names.csv", "per_file_summary.csv", "suspicious_emails.csv"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Collect emails from a zip of csv/xlsx/docx files.")
    ap.add_argument("zipfile", help="path to the input .zip")
    ap.add_argument("-o", "--output", default="subscribers.csv", help="output CSV (default: subscribers.csv)")
    ap.add_argument("--log", default="collect_emails_log.csv", help="per-file log (default: collect_emails_log.csv)")
    ap.add_argument("--report-dir", metavar="DIR",
                    help="also write missing_names.csv, per_file_summary.csv and suspicious_emails.csv into DIR")
    ap.add_argument("--fix-typos", action="store_true",
                    help="rewrite likely domain typos (e.g. gmial.com -> gmail.com) in the output")
    ap.add_argument("--exclude", metavar="FILE", action="append", default=[],
                    help="suppression list: drop every email found in FILE (csv/xlsx/docx/zip). Repeatable")
    ap.add_argument("--audience", choices=list(AUDIENCES), default="english",
                    help="english: Newsletter Preference is 'The IDR Weekly||Off The Record' (default); "
                         "hindi: Newsletter Preference is left blank")
    args = ap.parse_args(argv)

    try:
        r = run(args.zipfile, args.exclude, args.fix_typos, args.audience)
    except ValueError as exc:
        raise SystemExit(str(exc))

    tables = r.tables()
    write_csv(args.output, *tables["subscribers.csv"])
    write_csv(args.log, *tables["collect_emails_log.csv"])

    print(f"Audience      : {r.audience} (Newsletter Preference: {r.preference or 'blank'})")
    print(f"Files read OK : {r.ok}")
    print(f"Unique emails : {len(r.found)}  ->  {args.output}")
    print(f"Per-file log  : {args.log}")
    print(f"Without a name: {r.no_name}")
    print(f"Suspicious    : {r.suspicious_count}"
          + ("" if args.report_dir else "  (see --report-dir for details)"))
    if args.fix_typos:
        print(f"Typos fixed   : {r.fixed}")
    if args.exclude:
        print(f"Excluded      : {r.excluded} already on the suppression list ({r.suppressed} emails)")
    if args.report_dir:
        d = Path(args.report_dir)
        d.mkdir(parents=True, exist_ok=True)
        for name in REPORT_NAMES:
            write_csv(d / name, *tables[name])
            print(f"Report        : {d / name}")
    if r.bad:
        print(f"\n{len(r.bad)} file(s) skipped or failed:")
        for f, s, d in r.bad:
            print(f"  [{s}] {f} - {d}")
