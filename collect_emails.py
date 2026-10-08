#!/usr/bin/env python3
"""
collect_emails.py
-----------------
Reads a ZIP of messy files (csv, tsv, xlsx, xlsm, xls, ods, txt, json, html, vcf ...),
pulls out every email address (plus first/last name when available) and writes one
clean CSV in the subscriber upload format:

    email,First Name,Last Name,Newsletter Preference

Newsletter Preference is always: The IDR Weekly||Off The Record

Usage:
    python collect_emails.py collected_data.zip
    python collect_emails.py collected_data.zip -o subscribers.csv

Install once:
    pip install pandas openpyxl xlrd odfpy
(xlrd is only needed for old .xls files, odfpy only for .ods files)
"""

import argparse
import csv
import io
import re
import sys
import zipfile
from pathlib import PurePosixPath

import pandas as pd

NEWSLETTER_PREF = "The IDR Weekly||Off The Record"
OUT_COLUMNS = ["email", "First Name", "Last Name", "Newsletter Preference"]

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+'\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"
)

FIRST_KEYS = {"firstname", "fname", "first", "givenname", "forename"}
LAST_KEYS = {"lastname", "lname", "last", "surname", "familyname"}
FULL_KEYS = {"name", "fullname", "contactname", "yourname", "studentname", "participantname"}

TABLE_EXTS = {".csv", ".tsv", ".xlsx", ".xlsm", ".xltx", ".xls", ".ods"}
TEXT_EXTS = {".txt", ".json", ".html", ".htm", ".vcf", ".xml", ".md", ".log", ".eml"}
ENCODINGS = ["utf-8-sig", "utf-16", "cp1252", "latin-1"]


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def decode(data: bytes) -> str:
    for enc in ENCODINGS:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="ignore")


def clean_name(s) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if s.lower() in {"nan", "none", "null", "n/a", "na", "-"}:
        return ""
    if EMAIL_RE.search(s):  # someone typed an email into a name field
        return ""
    if s and (s.islower() or s.isupper()):
        s = s.title()
    return s


def clean_email(e: str) -> str:
    return e.strip().strip(".,;:'\"<>()[]").lower()


# ----------------------------------------------------------------------------
# row extraction (works on a list-of-rows, whatever the source format was)
# ----------------------------------------------------------------------------
def rows_from_csv(data: bytes, ext: str):
    text = decode(data)
    delim = "\t" if ext == ".tsv" else None
    if delim is None:
        try:
            delim = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
        except csv.Error:
            delim = ","
    return [list(r) for r in csv.reader(io.StringIO(text), delimiter=delim)]


def sheets_from_excel(data: bytes):
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=str)
    for name, df in sheets.items():
        yield name, df.fillna("").values.tolist()


def text_from_docx(data: bytes) -> str:
    """Plain text from a .docx (body, tables, headers, footers, mailto links) - no extra libs."""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.startswith("word/") and name.endswith((".xml", ".rels")):
                xml = z.read(name).decode("utf-8", errors="ignore")
                xml = re.sub(r"</w:p>|</w:tc>|<w:tab/>|<w:br/>", " \n", xml)
                xml = re.sub(r"<[^>]+>", "", xml) if name.endswith(".xml") else xml.replace("mailto:", " ")
                out.append(xml)
    return "\n".join(out)


def find_header(rows):
    """Return (header_index, first_idx, last_idx, full_idx) or None if no header found."""
    for i, row in enumerate(rows[:10]):
        keys = [norm(c) for c in row]
        has_known = any(k in FIRST_KEYS | LAST_KEYS | FULL_KEYS for k in keys)
        has_email = any("email" in k or k in {"mail", "emailid"} for k in keys)
        if has_known or has_email:
            first = next((j for j, k in enumerate(keys) if k in FIRST_KEYS), None)
            last = next((j for j, k in enumerate(keys) if k in LAST_KEYS), None)
            full = next((j for j, k in enumerate(keys) if k in FULL_KEYS), None)
            return i, first, last, full
    return None


def extract_from_rows(rows):
    """Yield (email, first, last) for every email found in the rows."""
    hdr = find_header(rows)
    start, fi, li, ni = (0, None, None, None)
    if hdr:
        start, fi, li, ni = hdr[0] + 1, hdr[1], hdr[2], hdr[3]

    for row in rows[start:]:
        cells = [str(c) if c is not None else "" for c in row]
        emails = []
        for c in cells:
            emails.extend(EMAIL_RE.findall(c))
        if not emails:
            continue

        first = clean_name(cells[fi]) if fi is not None and fi < len(cells) else ""
        last = clean_name(cells[li]) if li is not None and li < len(cells) else ""
        if not first and not last and ni is not None and ni < len(cells):
            full = clean_name(cells[ni])
            if full:
                parts = full.split(" ", 1)
                first, last = parts[0], (parts[1] if len(parts) > 1 else "")

        for n, e in enumerate(emails):
            # names are only trusted for the first email in a row
            yield clean_email(e), (first if n == 0 else ""), (last if n == 0 else "")


# ----------------------------------------------------------------------------
# zip walker
# ----------------------------------------------------------------------------
def process_zip(zf: zipfile.ZipFile, prefix, found, log):
    for info in zf.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename)
        base = path.name
        if "__MACOSX" in path.parts or base.startswith("~$") or base.startswith("."):
            continue

        label = f"{prefix}{info.filename}"
        ext = path.suffix.lower()

        try:
            data = zf.read(info)

            if ext == ".zip":
                with zipfile.ZipFile(io.BytesIO(data)) as inner:
                    process_zip(inner, label + "!/", found, log)
                continue

            count_before = len(found)
            raw_hits = 0

            if ext in {".csv", ".tsv"}:
                for e, f, l in extract_from_rows(rows_from_csv(data, ext)):
                    raw_hits += 1
                    add(found, e, f, l)
            elif ext in {".xlsx", ".xlsm", ".xltx", ".xls", ".ods"}:
                for _sheet, rows in sheets_from_excel(data):
                    for e, f, l in extract_from_rows(rows):
                        raw_hits += 1
                        add(found, e, f, l)
            elif ext in {".docx", ".docm"}:
                for e in EMAIL_RE.findall(text_from_docx(data)):
                    raw_hits += 1
                    add(found, clean_email(e), "", "")
            elif ext in TEXT_EXTS or ext == "":
                for e in EMAIL_RE.findall(decode(data)):
                    raw_hits += 1
                    add(found, clean_email(e), "", "")
            else:
                log.append((label, "SKIPPED", f"unsupported type {ext}"))
                continue

            log.append((label, "OK", f"{raw_hits} emails found, {len(found) - count_before} new"))

        except Exception as exc:  # keep going whatever happens to one file
            log.append((label, "ERROR", f"{type(exc).__name__}: {exc}"))


def add(found, email, first, last):
    rec = found.get(email)
    if rec is None:
        found[email] = {"first": first, "last": last}
    else:  # fill in missing names from later duplicates
        if not rec["first"] and first:
            rec["first"] = first
        if not rec["last"] and last:
            rec["last"] = last


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Collect emails from a zip of mixed files.")
    ap.add_argument("zipfile", help="path to the input .zip")
    ap.add_argument("-o", "--output", default="subscribers.csv", help="output CSV (default: subscribers.csv)")
    ap.add_argument("--log", default="collect_emails_log.csv", help="per-file log (default: collect_emails_log.csv)")
    args = ap.parse_args()

    found, log = {}, []
    with zipfile.ZipFile(args.zipfile) as zf:
        process_zip(zf, "", found, log)

    emails = sorted(found)
    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(OUT_COLUMNS)
        for e in emails:
            w.writerow([e, found[e]["first"], found[e]["last"], NEWSLETTER_PREF])

    with open(args.log, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "status", "detail"])
        w.writerows(log)

    ok = sum(1 for _, s, _ in log if s == "OK")
    bad = [(f, s, d) for f, s, d in log if s != "OK"]
    print(f"Files read OK : {ok}")
    print(f"Unique emails : {len(emails)}  ->  {args.output}")
    print(f"Per-file log  : {args.log}")
    if bad:
        print(f"\n{len(bad)} file(s) skipped or failed:")
        for f, s, d in bad:
            print(f"  [{s}] {f} - {d}")


if __name__ == "__main__":
    sys.exit(main())
