
import datetime as dt
import logging

from dataclasses import dataclass
from typing import Any, Callable

from .categorize import categorize, add_tags, set_status
from .context import Context
from .identity import Identity, resolve_datafile
from .linking import link_datacard, assign_and_watch
from .results import Result


log = logging.getLogger("datainbox.pipeline")

Handler = Callable[[Context], Result]


@dataclass(frozen=True)
class Handlers:
    """The set of handlers the pipeline dispatches to, one per non-trival note."""

    reconcile: Handler
    destroy: Handler
    dir_reconcile: Handler
    dir_destroy: Handler


def _file_date(ctx: Context) -> dt.datetime | None:
    """Best guess at the file's own timestamp, for the ``file_date`` field.

    Prefers what Files.com reports over the event time, since a redelivered or
    replayed message shouldn't move ``file_date``.
    """

    candidates = (
        getattr(ctx.rfc_file, "created_at", None),
        getattr(ctx.rfc_file, "provided_mtime", None),
        ctx.msg.at,
    )

    for value in candidates:
        if isinstance(value, dt.datetime):
            return value

        if isinstance(value, str) and value:
            try:
                return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue

    return None


def _today() -> dt.datetime:
    today = dt.date.today()
    return dt.datetime(year=today.year, month=today.month, day=today.day)


def reconcile(ctx: Context) -> Result:

    cu = ctx.services.clickup

    # 1. [REQUIRED] load the Files.com file at the target path
    if ctx.rfc_file is None:
        return ctx.nack(f"could not load Files.com file at {ctx.target_path}")

    # 2. [REQUIRED] resolve DataFile identity
    identity = resolve_datafile(ctx)
    if identity.status is Identity.AMBIGUOUS:
        # already alerted @channel. Retrying can't disambiguate, so ack rather
        # than nack-loop it into the dead-letter topic and wait for a human.
        
        # NOTE this is an instance of an ack where no datacard was created
        return ctx.ack(f"ambiguous identity ({identity.match_count} matches), alerted")

    # 3. [REQUIRED] determine category
    ctx.category_id = categorize(ctx.ftp_filename, ctx.ftp_directory)

    # 4. [REQUIRED] create or diff-and-patch
    if identity.found:
        existing = ctx.datafile
        if existing is None:
            return ctx.nack(f"resolved task {ctx.task_id} but could not load it from ClickUp")

        changes: dict[str, Any] = {}

        if existing.ftp_filename != ctx.ftp_filename:
            changes["ftp_filename"] = ctx.ftp_filename

        if existing.ftp_directory != ctx.ftp_directory:
            changes["ftp_directory"] = ctx.ftp_directory

        # the model reads the category back as a label, writes take the option id
        if existing.file_category != cu.category_label(ctx.category_id):
            changes["file_category"] = ctx.category_id

        renamed = existing.name != ctx.ftp_filename

        if not changes and not renamed and not identity.needs_metadata_backfill:
            return ctx.ack("already up to date")

        if renamed:
            cu.rename_task(ctx.task_id, ctx.ftp_filename)

        if changes:
            cu.update_datafile_fields(ctx.task_id, changes)
            log.info(f"patched {sorted(changes)} on DataFile {ctx.task_id}")

        patched = sorted(changes) + (["name"] if renamed else [])
        outcome = f"patched {patched}" if patched else "metadata backfill only"

    else:
        task_id = cu.create_datafile(
            name=ctx.ftp_filename,
            fields={
                "ftp_user": ctx.username,
                "ftp_filename": ctx.ftp_filename,
                "ftp_directory": ctx.ftp_directory,
                "file_date": _file_date(ctx),
                "received": _today(),
                "file_category": ctx.category_id,
            },
        )
        ctx.set_task_id(task_id)
        outcome = f"created DataFile {task_id}"

    # 5. [REQUIRED] backfill task_id into Files.com metadata so the next event is
    #    resolved by metadata instead of a search. No-op when it was already there.
    ctx.services.filescom.set_task_id(ctx.target_path, ctx.task_id)

    # 6. [BEST-EFFORT] link the DataFile to its client's DataCard.
    with ctx.best_effort("link-datacard"):
        link_datacard(ctx)

    # 7. [BEST-EFFORT] add account manager as watcher and perform assignee logic
    with ctx.best_effort("assign"):
        assign_and_watch(ctx)

    # 8. [BEST-EFFORT] add any relevant tags (`decrypt`, `debug`)
    with ctx.best_effort("add-tags"):
        add_tags(ctx)

    # 9. [BEST-EFFORT] set the status of datafile (`TERMED CLIENT`) if necessary,
    #    otherwise keep the status `NEW`
    with ctx.best_effort("set-status"):
        set_status(ctx)

    # 10. [BEST-EFFORT] add/update datafile record in datafiles db
    with ctx.best_effort("sync-datafiles-db"):
        ctx.services.datafiles.sync_datafile(ctx)

    # TODO remaining [BEST-EFFORT] steps: assign-or-add-watcher (the other half
    # of 6), decrypt tag, debug tag, termed status, completed-folder status,
    # datafiles db sync. Each goes in its own `with ctx.best_effort("<step>"):` block.

    print(outcome)
    return ctx.ack(outcome)


def destroy(msg: Context) -> Result:
    print(f"destroy: {msg}")
    return Result.ack("test destroy")


def dir_reconcile(msg: Context) -> Result:
    print("dir_reconcile:")
    print(msg)

    return Result.nack("test dir_reconcile")


def dir_destroy(msg: Context) -> Result:
    print("dir_destroy:")
    print(msg)

    return Result.nack("test dir_destroy")



def default_handlers() -> Handlers:
    return Handlers(
        reconcile=reconcile,
        destroy=destroy,
        dir_reconcile=dir_reconcile,
        dir_destroy=dir_destroy,
    )
