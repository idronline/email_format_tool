#!/usr/bin/env python3
"""
collect_emails.py
-----------------
Reads a ZIP of messy files (csv, tsv, xlsx, xlsm, xls, ods, docx, txt, json, html, vcf ...),
pulls out every email address (plus first/last name when available) and writes one
clean CSV in the subscriber upload format:

    email,First Name,Last Name,Newsletter Preference

Usage:
    python collect_emails.py collected_data.zip -o subscribers.csv

The code lives in the idr_emails package; this file keeps the original command working.
"""

import sys

from idr_emails.cli import main

if __name__ == "__main__":
    sys.exit(main())
