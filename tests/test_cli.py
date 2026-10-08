"""End-to-end tests: build a synthetic zip, run the CLI, inspect the output CSV."""

from conftest import HEADER, PREF, make_docx, make_xlsx, make_zip, read_csv


def test_output_format_is_exact(run_cli):
    res = run_cli({"a.csv": "Email,First Name,Last Name\nada@example.com,Ada,Lovelace\n"})
    assert res.header == HEADER
    assert res.rows[1] == ["ada@example.com", "Ada", "Lovelace", PREF]


def test_csv_with_header(run_cli):
    csv_text = (
        "Timestamp,Given Name,Surname,E-mail Address\n"
        "2024-01-01,grace,HOPPER,Grace.Hopper@Example.com\n"
        "2024-01-02,Alan,Turing,alan@example.org\n"
    )
    res = run_cli({"forms/signup.csv": csv_text})
    assert res.by_email["grace.hopper@example.com"][1:3] == ["Grace", "Hopper"]
    assert res.by_email["alan@example.org"][1:3] == ["Alan", "Turing"]


def test_csv_without_header(run_cli):
    res = run_cli({"raw.csv": "x1@example.com,foo\nx2@example.com,bar\n"})
    assert set(res.by_email) == {"x1@example.com", "x2@example.com"}
    # no header -> no names
    assert res.by_email["x1@example.com"][1:3] == ["", ""]


def test_semicolon_delimiter(run_cli):
    csv_text = "First Name;Last Name;Email\nMarie;Curie;marie@example.com\nPierre;Curie;pierre@example.com\n"
    res = run_cli({"semi.csv": csv_text})
    assert res.by_email["marie@example.com"][1:3] == ["Marie", "Curie"]
    assert res.by_email["pierre@example.com"][1:3] == ["Pierre", "Curie"]


def test_xlsx_full_name_is_split(run_cli):
    xlsx = make_xlsx({
        "Sheet1": [["Full Name", "Email ID"], ["Rosalind Elsie Franklin", "ros@example.com"], ["Plato", "plato@example.com"]],
        "Second": [["Name", "Mail"], ["ada lovelace", "ada@example.com"]],
    })
    res = run_cli({"book.xlsx": xlsx})
    assert res.by_email["ros@example.com"][1:3] == ["Rosalind", "Elsie Franklin"]
    assert res.by_email["plato@example.com"][1:3] == ["Plato", ""]
    # all sheets are read, and lower-case names get Title Case
    assert res.by_email["ada@example.com"][1:3] == ["Ada", "Lovelace"]


def test_nested_zip(run_cli):
    inner = make_zip({"deep/list.csv": "email,first name\nnested@example.com,Nadia\n"})
    res = run_cli({"outer/inner.zip": inner, "top.txt": "contact top@example.com please"})
    assert res.by_email["nested@example.com"][1] == "Nadia"
    assert "top@example.com" in res.by_email
    assert res.status_of("inner.zip!/deep/list.csv") == ["OK"]


def test_docx_table_and_body(run_cli):
    docx = make_docx(
        paragraphs=["Write to office@example.org for details."],
        table=[["Name", "Email"], ["Ann", "ann@example.com"], ["Bob", "bob@example.com"]],
    )
    res = run_cli({"notes.docx": docx})
    assert {"office@example.org", "ann@example.com", "bob@example.com"} <= set(res.by_email)


def test_duplicates_across_files_are_merged(run_cli):
    res = run_cli({
        "a.csv": "email\nDup@Example.com\n",
        "b.csv": "email,first name,last name\ndup@example.com,Dee,\n",
        "c.csv": "email,first name,last name\nDUP@example.com,Other,Upton\n",
    })
    assert len(res.rows) == 2  # header + one row
    # blanks filled from later duplicates, but an existing name is never overwritten
    assert res.by_email["dup@example.com"][1:3] == ["Dee", "Upton"]


def test_name_cell_containing_email_is_ignored(run_cli):
    res = run_cli({"a.csv": "name,email\nsam@example.com,sam@example.com\n"})
    assert res.by_email["sam@example.com"][1:3] == ["", ""]


def test_bad_and_corrupt_files_do_not_stop_the_run(run_cli):
    res = run_cli({
        "good.csv": "email\ngood@example.com\n",
        "broken.xlsx": b"this is not really an excel file",
        "broken.zip": b"PK\x03\x04 garbage",
        "picture.png": b"\x89PNG\r\n\x1a\n",
        "__MACOSX/._good.csv": "junk@example.com",
        "~$lockfile.xlsx": b"lock",
        ".hidden.csv": "hidden@example.com",
    })
    assert set(res.by_email) == {"good@example.com"}
    assert res.status_of("good.csv") == ["OK"]
    assert res.status_of("broken.xlsx") == ["ERROR"]
    assert res.status_of("broken.zip") == ["ERROR"]
    assert res.status_of("picture.png") == ["SKIPPED"]
    assert res.status_of("__MACOSX") == [] and res.status_of("~$") == []
    assert "skipped or failed" in res.stdout


def test_non_utf8_csv(run_cli):
    data = "email,first name\nzoe@example.com,Zoë\n".encode("cp1252")
    res = run_cli({"latin.csv": data})
    assert res.by_email["zoe@example.com"][1] == "Zoë"


def test_reports_missing_names_and_per_file_summary(run_cli, tmp_path):
    res = run_cli({
        "a.csv": "email,first name\nnamed@example.com,Nia\nanon@example.com,\n",
        "b.txt": "anon@example.com and other@example.org",
    }, "--report-dir", str(tmp_path / "rep"))
    assert res.header == HEADER  # upload format untouched
    missing = read_csv(tmp_path / "rep" / "missing_names.csv")
    assert missing == [["email", "source file"],
                       ["anon@example.com", "a.csv"], ["other@example.org", "b.txt"]]
    summary = {r[0]: r[1:] for r in read_csv(tmp_path / "rep" / "per_file_summary.csv")}
    assert summary["file"] == ["emails found", "with name", "new unique"]
    assert summary["a.csv"] == ["2", "1", "2"]
    assert summary["b.txt"] == ["2", "0", "1"]
    assert "Without a name: 2" in res.stdout


def test_no_reports_by_default(run_cli, tmp_path):
    run_cli({"a.csv": "email\nx@example.com\n"})
    assert not (tmp_path / "missing_names.csv").exists()


def test_typos_reported_but_not_fixed_by_default(run_cli, tmp_path):
    res = run_cli({"a.csv": "email,first name\nann@gmial.com,Ann\n"}, "--report-dir", str(tmp_path / "rep"))
    assert set(res.by_email) == {"ann@gmial.com"}
    sus = read_csv(tmp_path / "rep" / "suspicious_emails.csv")
    assert sus[1] == ["ann@gmial.com", "possible domain typo", "ann@gmail.com", "a.csv"]


def test_fix_typos(run_cli):
    res = run_cli({"a.csv": "email,first name\nann@gmial.com,Ann\nbob@hotmail.con,Bob\n"}, "--fix-typos")
    assert res.header == HEADER
    assert res.by_email["ann@gmail.com"][1] == "Ann"
    assert set(res.by_email) == {"ann@gmail.com", "bob@hotmail.com"}
    assert "Typos fixed   : 2" in res.stdout
