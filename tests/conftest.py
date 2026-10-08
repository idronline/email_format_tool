"""Shared helpers for building synthetic input zips in code.

No real data is ever used: every address is on example.com / example.org.
"""

import csv
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
PREF = "The IDR Weekly||Off The Record"
HEADER = ["email", "First Name", "Last Name", "Newsletter Preference"]


def make_zip(files: dict) -> bytes:
    """files: {path_in_zip: bytes | str}. Returns the zip as bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data.encode("utf-8") if isinstance(data, str) else data)
    return buf.getvalue()


def make_xlsx(sheets: dict) -> bytes:
    """sheets: {sheet_name: list of rows (first row is the header)}."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, rows in sheets.items():
            pd.DataFrame(rows[1:], columns=rows[0]).to_excel(xw, sheet_name=name, index=False)
    return buf.getvalue()


def make_docx(paragraphs=(), table=()) -> bytes:
    """Minimal hand-built .docx with optional paragraphs and one table."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    if table:
        rows = "".join(
            "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row) + "</w:tr>"
            for row in table
        )
        body += f"<w:tbl>{rows}</w:tbl>"
    doc = f'<?xml version="1.0" encoding="UTF-8"?><w:document {ns}><w:body>{body}</w:body></w:document>'
    return make_zip({
        "[Content_Types].xml": '<?xml version="1.0"?><Types/>',
        "word/document.xml": doc,
    })


class Result:
    def __init__(self, proc, out, log):
        self.proc = proc
        self.stdout = proc.stdout
        with open(out, newline="", encoding="utf-8") as fh:
            self.rows = list(csv.reader(fh))
        with open(log, newline="", encoding="utf-8") as fh:
            self.log = list(csv.DictReader(fh))

    @property
    def header(self):
        return self.rows[0]

    @property
    def by_email(self):
        return {r[0]: r for r in self.rows[1:]}

    def status_of(self, fragment):
        return [r["status"] for r in self.log if fragment in r["file"]]


@pytest.fixture
def run_cli(tmp_path):
    """Write a zip built from `files`, run the CLI on it, return a Result."""
    def _run(files: dict, *extra_args):
        zpath = tmp_path / "input.zip"
        zpath.write_bytes(make_zip(files))
        out, log = tmp_path / "out.csv", tmp_path / "log.csv"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "collect_emails.py"), str(zpath), "-o", str(out), "--log", str(log), *extra_args],
            capture_output=True, text=True, cwd=tmp_path,
        )
        assert proc.returncode == 0, proc.stderr
        return Result(proc, out, log)
    return _run


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))
