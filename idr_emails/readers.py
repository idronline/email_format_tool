"""Turn raw csv / xlsx bytes into lists of rows."""

import csv
import io

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

