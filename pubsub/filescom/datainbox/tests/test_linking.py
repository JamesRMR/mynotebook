"""DataCard linking, and the best-effort contract around it (DESIGN 4, step 6).

Run directly (``python test_linking.py``) or under pytest if it's installed.

Half of these test ``link_datacard`` in isolation; the rest go through
``reconcile`` to pin the thing that actually matters operationally -- a linking
failure is recorded and the message still acks.
"""

from fakes import (
    FakeClickUp,
    FakeClient,
    FakeFile,
    FakeFilescom,
    FakeIdentity,
    make_context,
)

from datainbox.handlers import reconcile
from datainbox.linking import LinkError, is_excluded, link_datacard, rmrcode_from_path


### pulling the RMR code out of a path

def test_rmrcode_from_path():
    assert rmrcode_from_path("/RMR/Acme Corp - RMR123/Files for RMR/x.csv") == "RMR123"
    assert rmrcode_from_path("/RMR/RMR456/x.csv") == "RMR456"
    assert rmrcode_from_path("RMR/Acme - RMR789/x.csv") == "RMR789", "leading slash optional"


def test_rmr_code_missing_or_unparseable():
    assert rmrcode_from_path("/RMR/Acme Corp/x.csv") is None, "no RMR code in the folder"
    assert rmrcode_from_path("/RMR/x.csv") is None, "no client folder component"
    assert rmrcode_from_path("") is None
    assert rmrcode_from_path(None) is None


def test_excluded_folders():
    assert is_excluded("/RMR/File Feed Vendors/acme/x.csv")
    assert is_excluded("/RMR/Acme - RMR1/ND Testing Info/x.csv")
    assert not is_excluded("/RMR/Acme - RMR1/Files for RMR/x.csv")


### link_datacard on its own

def _linkable(client_data=("DC1",), known_client=True, **kw):
    clickup = FakeClickUp(client=FakeClient(client_data=client_data), **kw)
    identity = FakeIdentity(client_id="CLIENT1" if known_client else None)
    ctx = make_context(
        clickup=clickup,
        identity=identity,
        path="/RMR/Acme Corp - RMR123/Files for RMR/acme_demo.csv",
    )
    ctx.set_task_id("T1")
    return ctx, clickup, identity


def test_links_datafile_to_the_clients_datacard():
    ctx, clickup, identity = _linkable()

    assert link_datacard(ctx) == "DC1"
    assert clickup.links == [("T1", "DC1")], "the DataFile is added to the DataCard"
    assert identity.looked_up == ["RMR123"]
    assert ctx.datacard_id == "DC1", "cached for the assignment step to reuse"


def test_returns_none_for_expected_shapes():
    """Not every file has a DataCard. These are normal, not failures."""
    # excluded folder
    ctx, clickup, _ = _linkable()
    ctx.msg.path = "/RMR/File Feed Vendors/acme/x.csv"
    assert link_datacard(ctx) is None
    assert clickup.links == []

    # no RMR code in the client folder
    ctx, clickup, _ = _linkable()
    ctx.msg.path = "/RMR/Acme Corp/Files for RMR/x.csv"
    assert link_datacard(ctx) is None
    assert clickup.links == []

    # the identity database doesn't know that RMR code
    ctx, clickup, _ = _linkable(known_client=False)
    assert link_datacard(ctx) is None
    assert clickup.links == []

    # client exists but has no DataCard
    ctx, clickup, _ = _linkable(client_data=())
    assert link_datacard(ctx) is None
    assert clickup.links == []


def test_employee_navigator_file_is_skipped_not_mislinked():
    ctx, clickup, identity = _linkable()
    ctx.msg.path = "/RMR/Acme Corp - RMR123/Files for RMR/ACME123_XML_20260801.xml"

    assert link_datacard(ctx) is None, "without the EN map, guessing the client is worse than skipping"
    assert clickup.links == []
    assert identity.looked_up == []


def test_missing_identity_raises():
    clickup = FakeClickUp(client=FakeClient(client_data=("DC1",)))
    ctx = make_context(clickup=clickup, identity=None, path="/RMR/Acme - RMR123/x.csv")
    ctx.set_task_id("T1")

    try:
        link_datacard(ctx)
    except LinkError:
        return

    raise AssertionError("a missing dependency is a real failure and must raise")


def test_identity_error_propagates():
    clickup = FakeClickUp(client=FakeClient(client_data=("DC1",)))
    identity = FakeIdentity(error=ConnectionError("identity db is down"))
    ctx = make_context(clickup=clickup, identity=identity, path="/RMR/Acme - RMR123/x.csv")
    ctx.set_task_id("T1")

    try:
        link_datacard(ctx)
    except ConnectionError:
        return

    raise AssertionError("service errors must reach best_effort rather than be swallowed here")


### the best-effort contract, through reconcile

def _reconcile_ctx(identity, clickup):
    return make_context(
        filescom=FakeFilescom(FakeFile()),
        clickup=clickup,
        identity=identity,
        path="/RMR/Acme Corp - RMR123/Files for RMR/acme_demo.csv",
        username="acme_ftp",
    )


def test_reconcile_links_after_creating():
    clickup = FakeClickUp(client=FakeClient(client_data=("DC1",)))
    ctx = _reconcile_ctx(FakeIdentity(client_id="CLIENT1"), clickup)

    result = reconcile(ctx)

    assert result.acked
    assert clickup.links == [("NEW1", "DC1")], "links the task id we just created"
    assert result.best_effort_failures == ()


def test_link_failure_is_recorded_but_still_acks():
    clickup = FakeClickUp(client=FakeClient(client_data=("DC1",)), link_error=RuntimeError("clickup 500"))
    ctx = _reconcile_ctx(FakeIdentity(client_id="CLIENT1"), clickup)

    result = reconcile(ctx)

    assert result.acked, "a best-effort failure must not block the ack"
    assert result.reason == "created DataFile NEW1", "the REQUIRED work still succeeded"
    assert len(result.best_effort_failures) == 1
    failure = result.best_effort_failures[0]
    assert failure.startswith("link-datacard:"), failure
    assert "clickup 500" in failure


def test_expected_skip_is_not_recorded_as_a_failure():
    clickup = FakeClickUp(client=FakeClient(client_data=()))
    ctx = _reconcile_ctx(FakeIdentity(client_id="CLIENT1"), clickup)

    result = reconcile(ctx)

    assert result.acked
    assert result.best_effort_failures == (), "no DataCard to link to isn't a failure"


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
