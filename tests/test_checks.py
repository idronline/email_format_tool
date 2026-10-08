"""Unit tests for suspicious-address checks (no network)."""

import pytest

from idr_emails.checks import apply_typo_fixes, find_suspicious, issues_for, osa_distance, suggest_domain


@pytest.mark.parametrize("domain, expected", [
    ("gmial.com", "gmail.com"),      # explicit map
    ("gmai.com", "gmail.com"),       # one edit from a popular provider
    ("hotmail.con", "hotmail.com"),  # bad TLD
    ("gmail.con", "gmail.com"),
    ("yahoo.co.in", None),           # real
    ("mail.com", None),              # real, though one edit from gmail.com
    ("acme-ngo.org", None),          # unrelated
])
def test_suggest_domain(domain, expected):
    assert suggest_domain(domain) == expected


def test_osa_counts_transposition_as_one():
    assert osa_distance("gmial.com", "gmail.com") == 1
    assert osa_distance("abc", "abc") == 0


def test_issues_for():
    assert ("possible domain typo", "ann@gmail.com") in list(issues_for("ann@gmial.com"))
    assert ("malformed local part", "") in list(issues_for("ann..b@acme.org"))
    assert ("placeholder/test address", "") in list(issues_for("noreply@acme.org"))
    assert list(issues_for("ann@acme.org")) == []


def test_apply_typo_fixes_merges_into_existing():
    found = {"ann@gmial.com": {"first": "", "last": "Lee", "source": "a"},
             "ann@gmail.com": {"first": "Ann", "last": "", "source": "b"}}
    n = apply_typo_fixes(found, find_suspicious(found))
    assert n == 1
    assert found == {"ann@gmail.com": {"first": "Ann", "last": "Lee", "source": "b"}}

