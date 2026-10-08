"""One full run: collect, check, fix, suppress. Shared by the CLI and the web app."""

from dataclasses import dataclass

from . import NEWSLETTER_PREF, OUT_COLUMNS
from .checks import apply_typo_fixes, find_suspicious
from .collector import collect, emails_in_file
from .reports import report_tables, to_csv_text


@dataclass
class Run:
    found: dict
    log: list
    stats: list
    suspicious: list
    fixed: int
    excluded: int
    suppressed: int

    @property
    def emails(self):
        return sorted(self.found)

    @property
    def ok(self):
        return sum(1 for _, s, _ in self.log if s == "OK")

    @property
    def bad(self):
        return [(f, s, d) for f, s, d in self.log if s != "OK"]

    @property
    def no_name(self):
        return sum(1 for r in self.found.values() if not r["first"] and not r["last"])

    @property
    def suspicious_count(self):
        return len({r[0] for r in self.suspicious})

    def subscriber_rows(self):
        return ([e, self.found[e]["first"], self.found[e]["last"], NEWSLETTER_PREF] for e in self.emails)

    def tables(self):
        """{filename: (header, rows)} for the upload file, the log and every report."""
        return {
            "subscribers.csv": (OUT_COLUMNS, self.subscriber_rows()),
            "collect_emails_log.csv": (["file", "status", "detail"], self.log),
            **report_tables(self.found, self.stats, self.suspicious),
        }

    def csv_texts(self):
        return {name: to_csv_text(h, rows) for name, (h, rows) in self.tables().items()}


def run(zip_source, exclude_paths=(), fix_typos=False) -> Run:
    """zip_source is a path or a binary file object. Raises ValueError on an unreadable exclude file."""
    suppressed = set()
    for path in exclude_paths:
        suppressed |= emails_in_file(path)

    found, log, stats = collect(zip_source)
    suspicious = find_suspicious(found)
    fixed = apply_typo_fixes(found, suspicious) if fix_typos else 0
    excluded = [e for e in found if e in suppressed]
    for e in excluded:
        del found[e]

    return Run(found, log, stats, suspicious, fixed, len(excluded), len(suppressed))
