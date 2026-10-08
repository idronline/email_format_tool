"""Walk a zip (recursively) and collect unique emails with names."""

import io
import zipfile
from pathlib import Path, PurePosixPath

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


def process_zip(zf: zipfile.ZipFile, prefix, found, log, stats=None):
    """Add every email in zf to `found`; append (file, status, detail) to `log`.

    If `stats` is a list, also append one dict of counts per file read OK.
    """
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
                    process_zip(inner, label + "!/", found, log, stats)
                continue

            hits = hits_from_file(data, ext)
            if hits is None:
                log.append((label, "SKIPPED", f"unsupported type {ext}"))
                continue

            count_before = len(found)
            raw_hits = named_hits = 0
            for e, f, l in hits:
                raw_hits += 1
                named_hits += bool(f or l)
                add(found, e, f, l, label)

            new = len(found) - count_before
            log.append((label, "OK", f"{raw_hits} emails found, {new} new"))
            if stats is not None:
                stats.append({"file": label, "emails_found": raw_hits,
                              "with_name": named_hits, "new_unique": new})

        except Exception as exc:  # keep going whatever happens to one file
            log.append((label, "ERROR", f"{type(exc).__name__}: {exc}"))


def add(found, email, first, last, source=""):
    rec = found.get(email)
    if rec is None:
        found[email] = {"first": first, "last": last, "source": source}
    else:  # fill in missing names from later duplicates
        if not rec["first"] and first:
            rec["first"] = first
        if not rec["last"] and last:
            rec["last"] = last


def collect(zip_path):
    """Return (found, log, stats) for a zip on disk."""
    found, log, stats = {}, [], []
    with zipfile.ZipFile(zip_path) as zf:
        process_zip(zf, "", found, log, stats)
    return found, log, stats


def emails_in_file(path):
    """Return the set of emails in one file on disk (any supported type, or a zip)."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        found, log, _ = collect(path)
    else:
        found, log = {}, []
        try:
            hits = hits_from_file(path.read_bytes(), path.suffix.lower())
            if hits is None:
                raise SystemExit(f"Unsupported file type for --exclude: {path}")
            for e, _f, _l in hits:
                found[e] = None
        except Exception as exc:
            log.append((str(path), "ERROR", f"{type(exc).__name__}: {exc}"))
    errors = [f"{f}: {d}" for f, s, d in log if s == "ERROR"]
    if errors:
        raise SystemExit(f"Could not read all of {path}: " + "; ".join(errors))
    return set(found)
