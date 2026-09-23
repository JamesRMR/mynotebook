"""RECONCILE path, REQUIRED steps 1-5 (DESIGN 4).

Run directly (``python test_reconcile.py``) or under pytest if it's installed.

The point of each test is the ack/nack contract plus *which writes happened* --
idempotency (DESIGN 9) means a redelivered message must not re-write anything.
"""

import datetime as dt

from fakes import (
    CATEGORY_NAMES,
    DeafFile,
    FakeClickUp,
    FakeDataFile,
    FakeFile,
    FakeFilescom,
    MissingFilescom,
    make_context,
)

from datainbox.categorize import COBRA, FLEX
from datainbox.handlers import reconcile
from datainbox.services import MetadataWriteError


def _existing(**kw):
    kw.setdefault("id", "T9")
    kw.setdefault("file_category", "FLEX")
    return FakeDataFile(**kw)


### step 1 -- load the Files.com file

def test_missing_file_nacks():
    ctx = make_context(filescom=MissingFilescom(), path="/RMR/A/x.csv")
    result = reconcile(ctx)

    assert not result.acked, "a file we can't load is treated as transient -> nack"


### step 2 -- identity

def test_ambiguous_identity_acks_without_writing():
    clickup = FakeClickUp(matches=[FakeDataFile(id="X"), FakeDataFile(id="Y")])
    filescom = FakeFilescom()
    ctx = make_context(filescom=filescom, clickup=clickup, path="/RMR/A/acme_demo.csv")

    result = reconcile(ctx)

    assert result.acked, "retrying can't disambiguate, so don't nack-loop toward the DLQ"
    assert clickup.created == []
    assert clickup.patched == []
    assert filescom.file.custom_metadata == {}, "must not guess a task_id into metadata"


### step 4 -- create branch

def test_creates_datafile_when_not_found():
    clickup = FakeClickUp()
    filescom = FakeFilescom()
    ctx = make_context(
        filescom=filescom,
        clickup=clickup,
        path="/RMR/Acme RMR123/acme_demo.csv",
        username="acme_ftp",
    )

    result = reconcile(ctx)

    assert result.acked
    assert len(clickup.created) == 1

    name, fields = clickup.created[0]
    assert name == "acme_demo.csv"
    assert fields["ftp_user"] == "acme_ftp"
    assert fields["ftp_filename"] == "acme_demo.csv"
    assert fields["ftp_directory"] == "/RMR/Acme RMR123"
    assert fields["file_category"] == FLEX
    assert fields["received"].date() == dt.date.today()
    # file_date comes off the Files.com file, not the event time
    assert fields["file_date"].year == 2026

    # step 5 ran
    assert filescom.file.custom_metadata["task_id"] == "NEW1"


### step 4 -- found branch, diff and patch

def test_already_up_to_date_writes_nothing():
    existing = _existing(
        name="acme_demo.csv",
        ftp_filename="acme_demo.csv",
        ftp_directory="/RMR/Acme RMR123",
    )
    clickup = FakeClickUp(datafile=existing)
    ctx = make_context(
        filescom=FakeFilescom(FakeFile({"task_id": "T9"})),
        clickup=clickup,
        path="/RMR/Acme RMR123/acme_demo.csv",
    )

    result = reconcile(ctx)

    assert result.acked
    assert result.reason == "already up to date"
    assert clickup.patched == []
    assert clickup.renamed == []
    assert clickup.created == []


def test_move_patches_only_the_directory():
    existing = _existing(
        name="acme_demo.csv", ftp_filename="acme_demo.csv", ftp_directory="/RMR/Old"
    )
    clickup = FakeClickUp(datafile=existing)
    ctx = make_context(
        filescom=FakeFilescom(FakeFile({"task_id": "T9"})),
        clickup=clickup,
        action="move",
        path="/RMR/Old/acme_demo.csv",
        destination="/RMR/New/acme_demo.csv",
    )

    reconcile(ctx)

    assert clickup.patched == [("T9", {"ftp_directory": "/RMR/New"})]
    assert clickup.renamed == []


def test_rename_patches_field_and_task_name():
    existing = _existing(
        name="old_demo.csv", ftp_filename="old_demo.csv", ftp_directory="/RMR/A"
    )
    clickup = FakeClickUp(datafile=existing)
    ctx = make_context(
        filescom=FakeFilescom(FakeFile({"task_id": "T9"})),
        clickup=clickup,
        action="move",
        path="/RMR/A/old_demo.csv",
        destination="/RMR/A/new_demo.csv",
    )

    reconcile(ctx)

    assert clickup.patched == [("T9", {"ftp_filename": "new_demo.csv"})]
    assert clickup.renamed == [("T9", "new_demo.csv")], "task name is top-level, not a custom field"


def test_reclassification_patches_category():
    # named _qb, so it categorizes COBRA while the task still says FLEX
    existing = _existing(name="acme_qb.csv", ftp_filename="acme_qb.csv", ftp_directory="/RMR/A")
    clickup = FakeClickUp(datafile=existing)
    ctx = make_context(
        filescom=FakeFilescom(FakeFile({"task_id": "T9"})),
        clickup=clickup,
        path="/RMR/A/acme_qb.csv",
    )

    reconcile(ctx)

    task_id, changes = clickup.patched[0]
    assert changes["file_category"] == COBRA, (
        f"got {CATEGORY_NAMES.get(changes['file_category'])}"
    )


def test_category_label_compared_not_id():
    """The model reads back a label ("FLEX"); a naive == against the option id
    would patch the category on every single message."""
    existing = _existing(
        name="acme_demo.csv",
        ftp_filename="acme_demo.csv",
        ftp_directory="/RMR/A",
        file_category="FLEX",
    )
    clickup = FakeClickUp(datafile=existing)
    ctx = make_context(
        filescom=FakeFilescom(FakeFile({"task_id": "T9"})),
        clickup=clickup,
        path="/RMR/A/acme_demo.csv",
    )

    reconcile(ctx)

    assert clickup.patched == [], "category was already FLEX, nothing to patch"


### step 5 -- metadata backfill

def test_search_hit_backfills_metadata():
    existing = _existing(
        id="T5", name="acme_demo.csv", ftp_filename="acme_demo.csv", ftp_directory="/RMR/A"
    )
    clickup = FakeClickUp(matches=[existing], datafile=existing)
    filescom = FakeFilescom()
    ctx = make_context(filescom=filescom, clickup=clickup, path="/RMR/A/acme_demo.csv")

    result = reconcile(ctx)

    assert result.acked
    assert filescom.file.custom_metadata["task_id"] == "T5", "found by search -> write it back"
    assert clickup.patched == [], "fields already matched, only the backfill was needed"


def test_backfill_preserves_other_metadata_keys():
    filescom = FakeFilescom(FakeFile({"keep": "me"}))
    ctx = make_context(filescom=filescom, path="/RMR/A/acme_demo.csv")

    reconcile(ctx)

    assert filescom.file.custom_metadata == {"keep": "me", "task_id": "NEW1"}, (
        "read-merge-write, or we clobber keys we don't own"
    )


def test_unconfirmed_metadata_write_raises():
    filescom = FakeFilescom(DeafFile())
    ctx = make_context(filescom=filescom, path="/RMR/A/acme_demo.csv")

    try:
        reconcile(ctx)
    except MetadataWriteError:
        return

    raise AssertionError("step 5 is REQUIRED; an unconfirmed write must raise so the callback nacks")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


if __name__ == "__main__":
    import traceback

    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {test.__name__}")
            traceback.print_exc()

    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)
