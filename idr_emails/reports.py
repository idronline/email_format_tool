"""CSV writing and the optional side reports (never change the upload format)."""

import csv
import io


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def to_csv_text(header, rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def report_tables(found, stats, suspicious=()):
    """{filename: (header, rows)} for missing_names, per_file_summary and suspicious_emails."""
    return {
        "missing_names.csv": (
            ["email", "source file"],
            [[e, found[e]["source"]] for e in sorted(found)
             if not found[e]["first"] and not found[e]["last"]],
        ),
        "per_file_summary.csv": (
            ["file", "emails found", "with name", "new unique"],
            [[s["file"], s["emails_found"], s["with_name"], s["new_unique"]] for s in stats],
        ),
        "suspicious_emails.csv": (
            ["email", "issue", "suggestion", "source file"],
            list(suspicious),
        ),
    }
