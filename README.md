# email_format_tool

Turns a zip of folders of CSV / XLSX / DOCX files (collected by non-technical people) into **one clean CSV**
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

## Web app

```bash
uvicorn idr_emails.web:app --host 0.0.0.0 --port 5002
```

Open `http://localhost:5002`, upload the zip, optionally add an existing list to exclude and
tick "Fix common domain typos", then click **Download subscribers.csv**. The reports are
offered as downloads on the same page.

- Uploads are processed in a temporary folder that is deleted straight away. Results are
  embedded in the response page, so the server never keeps personal data.
- Set `APP_USERNAME` and `APP_PASSWORD` in the environment to require a browser login
  (HTTP basic auth). Without them the page is open to anyone who can reach the port.

## Command line

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

With `--report-dir DIR` it also writes (never committed, these contain personal data):

| File | Contents |
|---|---|
| `DIR/missing_names.csv` | `email,source file` for every email that ended up with no name |
| `DIR/per_file_summary.csv` | `file,emails found,with name,new unique` per file read |
| `DIR/suspicious_emails.csv` | `email,issue,suggestion,source file` (see below) |

### Suspicious addresses and typos

Every run counts suspicious addresses. The details go to `suspicious_emails.csv`:

- **possible domain typo**: known misspellings (`gmial.com`), bad TLDs (`.con`, `.cmo`),
  or one edit away from a popular provider (`gmai.com`). A suggestion is given.
- **placeholder/test address**: `noreply@`, `test@`, `example.com` and similar.
- **malformed local part**: `..`, or a leading or trailing dot.

`--fix-typos` rewrites typo domains to the suggestion in `subscribers.csv`, merging names if
the corrected address already exists. Without it, nothing is changed, only reported.

Skipped and failed files are also printed to the terminal. One bad file never stops the run.

### Suppression list

```bash
python collect_emails.py data.zip -o subscribers.csv --exclude existing_list.csv [--exclude more.xlsx]
```

Every email found in an `--exclude` file (csv, xlsx, docx or a zip of them; the column name
doesn't matter) is left out of `subscribers.csv`. Typo fixes are applied first, so a corrected
address that is already on the list is also dropped. If a suppression file can't be read, the
run stops without writing output, so you never get an unsuppressed list by accident.

## What it reads

- Every folder in the zip, including **nested zips**. It skips `__MACOSX/`, dotfiles and `~$` Office lock files.
- **csv**: sniffs the delimiter (`,` `;` tab `|`) and tries several encodings.
- **xlsx / xlsm**: all sheets.
- **docx**: tables get the same header/name detection as spreadsheets; emails anywhere else
  (paragraph lists, headers, footers) are picked up without names.
- Anything else (pdf, images, old .doc...) is logged as `SKIPPED` and listed in the terminal.

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
  cli.py               command line: argument parsing, writing files, terminal summary
  web.py, page.html    FastAPI web app (same pipeline, downloads in the browser)
  pipeline.py          one full run: collect -> check -> fix typos -> exclude
  collector.py         zip walking, per-file dispatch, dedupe/merge
  readers.py           bytes -> rows (csv, xlsx, docx, encodings)
  extract.py           email regex, header detection, name cleaning
  checks.py            suspicious-address checks, typo fixes
  reports.py           optional side reports (--report-dir)
tests/                 pytest, synthetic fixtures only
```
