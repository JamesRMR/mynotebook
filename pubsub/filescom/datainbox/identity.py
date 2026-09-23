
import logging

from dataclasses import dataclass
from enum import Enum, auto

from .context import Context

log = logging.getLogger("datainbox.pipeline")



class Identity(Enum):
    FOUND = auto()
    NOT_FOUND = auto()
    AMBIGUOUS = auto()



@dataclass(frozen=True)
class IdentityResult:
    status: Identity
    task_id: str | None = None
    via: str | None = None # "metadata" or "search"
    match_count: int = 0


    @property
    def found(self) -> bool:
        return self.status is Identity.FOUND


    @property
    def needs_metadata_backfill(self) -> bool:
        """True when we fount it by sesarching. task id metadata should be written back"""
        return self.found and self.via == "search"



def resolve_datafile(ctx: Context, use_metadata: bool = True) -> IdentityResult:
    """Resolve the DataFile identity for ``ctx``, setting ``ctx.task_id`` on success."""
    # Primary: Files.com custom metadata
    if use_metadata:
        task_id = ctx.metadata_task_id
        if task_id:
            ctx.set_task_id(task_id)
            log.info(f"resolved {ctx.target_path} via metadata -> {task_id}")
            return IdentityResult(
                Identity.FOUND,
                task_id=task_id,
                via="metadata",
                match_count=1
            )

    matches = ctx.services.clickup.search_datafiles(
        ftp_filename=ctx.ftp_filename,
        ftp_directory=ctx.ftp_directory
    )
    
    if not matches:
        log.info(f"no Datafile found for {ctx.target_path}")
        return IdentityResult(Identity.NOT_FOUND, match_count=0)

    if len(matches) > 1:
        ctx.alerter.alert(f"Ambiguous DataFile identity for `{ctx.target_path}`\n\t{len(matches)} matches, refusing to guess.", at_channel=True)
        return IdentityResult(Identity.AMBIGUOUS, match_count=len(matches))

    task_id = matches[0].id
    ctx.set_task_id(task_id)
    log.info(f"resolved {ctx.target_path} via search -> {task_id} (backfill scheduled)")
    
    return IdentityResult(Identity.FOUND, task_id=task_id, via="search", match_count=1)