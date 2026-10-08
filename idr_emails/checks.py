"""Flag suspicious addresses and suggest fixes for common domain typos.

Nothing here changes the upload format: issues go to a side report, and typo
fixes are only applied when --fix-typos is passed.
"""

import re

# Real providers people commonly mistype. A domain one edit away from one of
# these (and not itself listed in KNOWN_OK) is treated as a likely typo.
POPULAR = [
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "ymail.com",
    "hotmail.com", "outlook.com", "live.com", "msn.com", "icloud.com", "me.com",
    "aol.com", "protonmail.com", "proton.me", "rediffmail.com", "zoho.com", "gmx.com",
]
# Real domains that sit one edit away from a popular one - never "fix" these.
KNOWN_OK = set(POPULAR) | {
    "mail.com", "email.com", "gmx.de", "gmx.net", "live.in", "live.co.uk", "yahoo.co.uk",
    "hotmail.co.uk", "outlook.in", "zoho.in", "aim.com", "mac.com",
}
# Explicit typo map for misspellings more than one edit away.
TYPO_MAP = {
    "gamil.com": "gmail.com", "gmial.com": "gmail.com", "gmaill.com": "gmail.com",
    "gmail.co": "gmail.com", "gnail.com": "gmail.com", "gmali.com": "gmail.com",
    "gmail.com.com": "gmail.com", "g.mail.com": "gmail.com", "gmailcom": "gmail.com",
    "yahooo.com": "yahoo.com", "yaho.com": "yahoo.com", "yahoo.co": "yahoo.com",
    "hotmial.com": "hotmail.com", "hotmai.com": "hotmail.com", "homail.com": "hotmail.com",
    "outlok.com": "outlook.com", "outllook.com": "outlook.com",
    "rediff.com": "rediffmail.com", "redifmail.com": "rediffmail.com",
}
BAD_TLDS = {"con": "com", "cmo": "com", "cpm": "com", "comm": "com", "vom": "com", "xom": "com",
            "ocm": "com", "om": "com", "nett": "net", "nte": "net", "ogr": "org", "orgg": "org"}
PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "test.com", "domain.com",
                       "email.example", "abc.com", "xyz.com"}
PLACEHOLDER_LOCALS = {"test", "abc", "xyz", "asdf", "noreply", "no-reply", "donotreply", "none", "na"}


def osa_distance(a: str, b: str) -> int:
    """Edit distance counting a swap of two adjacent characters as one edit."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def suggest_domain(domain: str):
    """Return a corrected domain for a likely typo, or None."""
    if domain in KNOWN_OK:
        return None
    if domain in TYPO_MAP:
        return TYPO_MAP[domain]
    head, _, tld = domain.rpartition(".")
    if tld in BAD_TLDS:
        fixed = f"{head}.{BAD_TLDS[tld]}"
        return TYPO_MAP.get(fixed, fixed)
    close = [p for p in POPULAR if osa_distance(domain, p) == 1]
    return close[0] if len(close) == 1 else None


def issues_for(email: str):
    """Yield (issue, suggestion) pairs for one already-lowercased email."""
    local, _, domain = email.rpartition("@")
    if ".." in email or local.startswith(".") or local.endswith("."):
        yield "malformed local part", ""
    if local in PLACEHOLDER_LOCALS or domain in PLACEHOLDER_DOMAINS:
        yield "placeholder/test address", ""
    if re.search(r"\d{2,}$", domain.rpartition(".")[2]):
        yield "numeric TLD", ""
    fixed = suggest_domain(domain)
    if fixed:
        yield "possible domain typo", f"{local}@{fixed}"


def check_mx(domains, lookup=None):
    """Return the set of domains with no MX (or A) record.

    `lookup(domain) -> bool` can be injected for tests; the default uses dnspython.
    """
    if lookup is None:
        lookup = _dns_lookup()
    return {d for d in sorted(set(domains)) if not lookup(d)}


def _dns_lookup():
    try:
        import dns.exception
        import dns.resolver
    except ImportError:
        raise SystemExit("--check-mx needs dnspython: pip install dnspython")

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5.0

    def lookup(domain):
        for rtype in ("MX", "A"):
            try:
                resolver.resolve(domain, rtype)
                return True
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
                continue
            except dns.exception.Timeout:
                return True  # can't tell - don't flag on a flaky network
        return False

    return lookup


def find_suspicious(found, check_mx_records=False, lookup=None):
    """Return a list of (email, issue, suggestion, source) rows, sorted by email."""
    rows = []
    for e in sorted(found):
        for issue, suggestion in issues_for(e):
            rows.append((e, issue, suggestion, found[e]["source"]))
    if check_mx_records:
        dead = check_mx((e.rpartition("@")[2] for e in found), lookup)
        rows.extend((e, "domain has no mail server", "", found[e]["source"])
                    for e in sorted(found) if e.rpartition("@")[2] in dead)
        rows.sort(key=lambda r: r[0])
    return rows


def apply_typo_fixes(found, suspicious):
    """Rename emails whose domain has a typo suggestion, merging names. Returns the count fixed."""
    fixed = 0
    for email, issue, suggestion, _src in suspicious:
        if issue != "possible domain typo" or email not in found:
            continue
        rec = found.pop(email)
        target = found.setdefault(suggestion, {"first": "", "last": "", "source": rec["source"]})
        target["first"] = target["first"] or rec["first"]
        target["last"] = target["last"] or rec["last"]
        fixed += 1
    return fixed
