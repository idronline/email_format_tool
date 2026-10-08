"""Find emails and names in a list of rows, whatever the source format was."""

import re

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+'\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"
)

FIRST_KEYS = {"firstname", "fname", "first", "givenname", "forename"}
LAST_KEYS = {"lastname", "lname", "last", "surname", "familyname"}
FULL_KEYS = {"name", "fullname", "contactname", "yourname", "studentname", "participantname"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


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


def emails_in_text(text: str):
    """Yield cleaned emails found anywhere in free text."""
    for e in EMAIL_RE.findall(text):
        yield clean_email(e)


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
