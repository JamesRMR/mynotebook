"""Fixture filename/path -> expected category (DESIGN 7).

Run directly (``python test_categorize.py``) or under pytest if it's installed.

These are the tests that make changing category rules boring: add a row to
CASES, not a debugging session. Rules are always passed in explicitly so a
change to DEFAULT_RULES can't silently rewrite what the tests assert.
"""

from fakes import CATEGORY_NAMES

from datainbox.categorize import (
    CLIENT_INBOX,
    COBRA,
    CONT,
    DEFAULT_RULES,
    FLEX,
    NDT,
    CategoryRule,
    categorize,
    tokenize,
)


# (filename, directory, expected category)
CASES = [
    # plain substring hits
    ("acme_demo_2024.csv",     "/RMR/Acme RMR123",  FLEX),
    ("acme_XML_feed.xml",      "/RMR/Acme RMR123",  FLEX),
    ("acme_qb_list.csv",       "/RMR/Acme RMR123",  COBRA),
    ("acme_payroll_0401.csv",  "/RMR/Acme RMR123",  CONT),
    ("acme_ndt.xlsx",          "/RMR/Acme RMR123",  NDT),

    # priority: NDT > CONT > COBRA > FLEX
    ("acme_ndt_cont.csv",      "/RMR/A",            NDT),
    ("acme_cont_qb.csv",       "/RMR/A",            CONT),
    ("acme_qb_demo.csv",       "/RMR/A",            COBRA),

    # folder rules, case-insensitive
    ("anything.xlsx",          "/RMR/Uploaded ND Testing Inbox", NDT),
    ("anything.xlsx",          "/RMR/uploaded nd testing inbox", NDT),

    # tokens must match whole, not as substrings: 'in' inside 'index' is not COBRA
    ("acme_index_report.csv",  "/RMR/A",            CLIENT_INBOX),
    ("continental.csv",        "/RMR/A",            CLIENT_INBOX),

    # multi-word rules match only as adjacent tokens
    ("acme_new_hire_list.csv", "/RMR/A",            COBRA),
    ("initial notice acme.pdf", "/RMR/A",           COBRA),
    ("acme_new_and_hire.csv",  "/RMR/A",            CLIENT_INBOX),

    # nothing matches -> default
    ("random_document.pdf",    "/RMR/A",            CLIENT_INBOX),
    ("acme_flex.csv",          "",                  FLEX),
]


def test_default_rules():
    for filename, directory, expected in CASES:
        got = categorize(filename, directory, rules=DEFAULT_RULES)
        assert got == expected, (
            f"{filename!r} in {directory!r}: "
            f"got {CATEGORY_NAMES.get(got, got)}, want {CATEGORY_NAMES.get(expected, expected)}"
        )


def test_tokenize_splits_on_every_delimiter():
    assert tokenize("acme demo-elec_2024.csv") == ("acme", "demo", "elec", "2024", "csv")
    assert tokenize("") == ()
    assert tokenize("__--..") == ()


def test_rules_are_injected_not_global():
    only = (CategoryRule(category_id="ZZZ", priority=1, label="TEST", substrings=("acme",)),)
    assert categorize("acme_demo.csv", "/RMR/A", rules=only) == "ZZZ"
    # 'demo' would be FLEX under DEFAULT_RULES, but those rules weren't passed
    assert categorize("nope_demo.csv", "/RMR/A", rules=only) == CLIENT_INBOX


def test_explicit_priority_decides_not_rule_order():
    low = CategoryRule(category_id="LOW", priority=1, substrings=("acme",))
    high = CategoryRule(category_id="HIGH", priority=99, substrings=("acme",))

    # same rules, opposite list order, same winner
    assert categorize("acme.csv", "", rules=(low, high)) == "HIGH"
    assert categorize("acme.csv", "", rules=(high, low)) == "HIGH"


def test_custom_default():
    assert categorize("nothing_matches.pdf", "/RMR/A", rules=(), default="MINE") == "MINE"


def test_folder_rule_needs_a_whole_component():
    rule = (CategoryRule(category_id="F", priority=1, folder_names=("Inbox",)),)
    assert categorize("x.csv", "/RMR/Inbox", rules=rule) == "F"
    assert categorize("x.csv", "/RMR/Inboxes", rules=rule) == CLIENT_INBOX


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


if __name__ == "__main__":
    import traceback

    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError:
            failed += 1
            print(f"  FAIL {test.__name__}")
            traceback.print_exc()

    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)
