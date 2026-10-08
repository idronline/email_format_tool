"""Optional side reports written next to the upload file (never change the upload format)."""

import csv
from pathlib import Path


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def write_reports(report_dir, found, stats, suspicious=()):
    """Write the side reports into report_dir. Returns the paths written."""
    d = Path(report_dir)
    d.mkdir(parents=True, exist_ok=True)

    missing = d / "missing_names.csv"
    write_csv(missing, ["email", "source file"],
              ([e, found[e]["source"]] for e in sorted(found)
               if not found[e]["first"] and not found[e]["last"]))

    summary = d / "per_file_summary.csv"
    write_csv(summary, ["file", "emails found", "with name", "new unique"],
              ([s["file"], s["emails_found"], s["with_name"], s["new_unique"]] for s in stats))

    sus = d / "suspicious_emails.csv"
    write_csv(sus, ["email", "issue", "suggestion", "source file"], suspicious)

    return [missing, summary, sus]
