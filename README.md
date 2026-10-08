# email_format_tool

Turns a zip of messy files (collected by non-technical people) into **one clean CSV**
in the IDR newsletter-subscriber upload format.

## Output format

Exact header, one row per unique email:

```csv
email,First Name,Last Name,Newsletter Preference
subhaoi@gmail.com,Subhash,S,The IDR Weekly||Off The Record
```

- `email`: lowercased, deduplicated, sorted.
- `First Name` / `Last Name`: taken from the source when it has them, otherwise blank.
- `Newsletter Preference`: always `The IDR Weekly||Off The Record`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt     # runtime deps + pytest
# optional: pip install -e .            # adds a `collect-emails` command
```

## Usage

```bash
python collect_emails.py data.zip -o subscribers.csv [--log collect_emails_log.csv]
# equivalent:
python -m idr_emails data.zip -o subscribers.csv
```

Writes:

| File | Contents |
|---|---|
| `subscribers.csv` | the upload file (format above) |
| `collect_emails_log.csv` | one row per file read: `file,status,detail` (`OK` / `SKIPPED` / `ERROR`) |

Skipped and failed files are also printed to the terminal. One bad file never stops the run.

## What it reads

- Every folder in the zip, including **nested zips**. It skips `__MACOSX/`, dotfiles and `~$` Office lock files.
- **csv / tsv**: sniffs the delimiter (`,` `;` tab `|`) and tries several encodings.
- **xlsx / xlsm / xltx / xls / ods**: all sheets.
- **docx / docm**: body, tables, headers/footers and `mailto:` links (stdlib only).
- **txt / json / html / htm / vcf / xml / md / log / eml** and extension-less files: regex scan.

How emails and names are found:

- Emails are matched by regex in every cell, so the column name doesn't matter.
- A header row is looked for in the first 10 rows. First/last name columns are recognised
  from variants such as `First Name`, `fname`, `Given Name`, `Surname`, `lname` and so on.
  If there is only a full `Name` column, it is split at the first space.
- Names from later duplicates fill blanks but never overwrite an existing name.
- ALL-CAPS or all-lowercase names are Title-Cased. A name cell that contains an email is ignored.
- When a row has several emails, its names go to the first one only.

## Privacy

The input zips and every generated CSV/log contain **real personal email addresses**.
`.gitignore` excludes `*.zip`, `*.csv`, spreadsheets, docs, logs etc. Never force-add them.
Tests build all their fixtures in code with `example.com` / `example.org` addresses.

## Tests

```bash
python -m pytest -q
```

## Layout

```
collect_emails.py      thin entry point (keeps the original command)
idr_emails/
  cli.py               argument parsing, writing outputs, terminal summary
  collector.py         zip walking, per-file dispatch, dedupe/merge
  readers.py           bytes -> rows / text (csv, excel, docx, encodings)
  extract.py           email regex, header detection, name cleaning
tests/                 pytest, synthetic fixtures only
```
