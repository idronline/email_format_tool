"""Turn raw csv / xlsx / docx bytes into lists of rows (and docx free text)."""

import csv
import html
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


def rows_from_csv(data: bytes):
    text = decode(data)
    try:
        delim = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
    except csv.Error:
        delim = ","
    return [list(r) for r in csv.reader(io.StringIO(text), delimiter=delim)]


def sheets_from_excel(data: bytes):
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=str)
    for name, df in sheets.items():
        yield name, df.fillna("").values.tolist()



def docx_tables_and_text(data: bytes):
    """Return (tables, text) from a .docx: tables as lists of rows, plus all text outside tables."""
    tables, texts = [], []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts = [n for n in z.namelist() if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", n)]
        for name in parts:
            xml = z.read(name).decode("utf-8", errors="ignore")
            for tbl in re.findall(r"<w:tbl>.*?</w:tbl>", xml, re.S):
                tables.append([[_xml_text(tc) for tc in re.findall(r"<w:tc\b.*?</w:tc>", tr, re.S)]
                               for tr in re.findall(r"<w:tr\b.*?</w:tr>", tbl, re.S)])
            body = re.sub(r"<w:tbl>.*?</w:tbl>", "", xml, flags=re.S)
            texts.extend(_xml_text(p) for p in re.findall(r"<w:p\b.*?</w:p>", body, re.S))
    return tables, "\n".join(texts)


def _xml_text(fragment: str) -> str:
    """Visible text of a WordprocessingML fragment, with spaces between runs/paragraphs."""
    fragment = re.sub(r"<w:tab/>|<w:br/>|</w:p>", " ", fragment)
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()
