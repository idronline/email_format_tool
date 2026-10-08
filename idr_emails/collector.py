"""Walk a zip (recursively) and collect unique emails with names."""

import io
import zipfile
from pathlib import PurePosixPath

from .extract import emails_in_text, extract_from_rows
from .readers import decode, rows_from_csv, sheets_from_excel, text_from_docx

CSV_EXTS = {".csv", ".tsv"}
EXCEL_EXTS = {".xlsx", ".xlsm", ".xltx", ".xls", ".ods"}
DOCX_EXTS = {".docx", ".docm"}
TEXT_EXTS = {".txt", ".json", ".html", ".htm", ".vcf", ".xml", ".md", ".log", ".eml"}


def hits_from_file(data: bytes, ext: str):
    """Yield (email, first, last) from one file, or return None if the type is unsupported."""
    if ext in CSV_EXTS:
        return extract_from_rows(rows_from_csv(data, ext))
    if ext in EXCEL_EXTS:
        return (hit for _sheet, rows in sheets_from_excel(data) for hit in extract_from_rows(rows))
    if ext in DOCX_EXTS:
        return ((e, "", "") for e in emails_in_text(text_from_docx(data)))
    if ext in TEXT_EXTS or ext == "":
        return ((e, "", "") for e in emails_in_text(decode(data)))
    return None


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

            hits = hits_from_file(data, ext)
            if hits is None:
                log.append((label, "SKIPPED", f"unsupported type {ext}"))
                continue

            count_before = len(found)
            raw_hits = 0
            for e, f, l in hits:
                raw_hits += 1
                add(found, e, f, l)

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


def collect(zip_path):
    """Return (found, log) for a zip on disk."""
    found, log = {}, []
    with zipfile.ZipFile(zip_path) as zf:
        process_zip(zf, "", found, log)
    return found, log
