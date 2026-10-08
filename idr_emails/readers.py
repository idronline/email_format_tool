"""Turn raw file bytes into rows (tables) or plain text."""

import csv
import io
import re
import zipfile

import pandas as pd

ENCODINGS = ["utf-8-sig", "utf-16", "cp1252", "latin-1"]


def decode(data: bytes) -> str:
    for enc in ENCODINGS:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="ignore")


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
