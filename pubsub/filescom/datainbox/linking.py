"""Link a DataFile to its client's DataCard (DESIGN 4, step 6).

This is a **BEST-EFFORT** step: ``reconcile`` runs it inside
``ctx.best_effort("link-datacard")``, so anything raised here is logged and
recorded on the context rather than propagated, and the message still acks.

That makes the raise-vs-return distinction below load-bearing:

* **return None** for a shape we expect to see in normal traffic (an excluded
  folder, a client folder with no RMR code, a client with no DataCard). Not
  every file *has* a DataCard to link to, and recording those as failures would
  bury the real ones in noise.
* **raise** when something we depend on is broken (CoreDB unreachable, ClickUp
  rejecting the patch). ``best_effort`` turns that into a recorded failure that
  rides along on the ack and shows up in the consumer log.
"""

import logging

from .context import Context
from .utils import watch, convert_bool

log = logging.getLogger("datainbox.pipeline")


# folders whose files are deliberately never linked to a client
EXCLUDED_PATH_FRAGMENTS = ("File Feed Vendors", "ND Testing Info")

# Employee Navigator exports are named `<identifier>_XML_...`, and their
# identifier maps to an RMR code via a Firestore lookup we don't have yet.
EN_FILENAME_MARKER = "_XML_"

CONNECTION_USER_GROUP_ID = "75e50387-5a3b-47ec-968c-e75ec968acae"

TYPE_MAP = {
    "0": "FLEX",
    "1": "COBRA",
    "2": "Client Inbox",
    "3": "NDT",
    "4": "Cont",
    "5": "Unknown",
    "6": "Email Request",
    "7": "Balance Adjustments",
    "8": "Autopost Requests",
}

class LinkError(RuntimeError):
    """A dependency needed to link the DataFile was missing or broken."""


def is_excluded(path: str) -> bool:
    """True for paths we never link (vendor and ND-testing drop folders)."""
    return any(fragment in (path or "") for fragment in EXCLUDED_PATH_FRAGMENTS)


def rmrcode_from_path(path: str) -> str | None:
    """Pull the RMR code out of the client folder component of a path.

    ``/RMR/Acme Corp - RMR123/Files for RMR/x.csv`` -> ``"RMR123"``

    Returns None when the path is too short to have a client folder, or that
    folder carries no RMR code.
    """

    # TODO use EN rmrcode map in firestore

    parts = [p for p in (path or "").strip("/").split("/") if p]
    if len(parts) < 2:
        return None

    client_folder = parts[1]
    start = client_folder.find("RMR")

    return client_folder[start:] if start != -1 else None


def link_datacard(ctx: Context) -> str | None:
    """Link ``ctx``'s DataFile to its client's DataCard.

    Returns the DataCard id it linked to, or None when there was nothing to
    link. Raises :class:`LinkError` (or lets a service error through) when a
    dependency fails -- see the module docstring for why that split matters.
    """

    path = ctx.target_path

    if is_excluded(path):
        log.info(f"not linking {path}: excluded folder")
        return None

    if EN_FILENAME_MARKER in ctx.ftp_filename:
        log.warning(f"not linking {path}: Employee Navigator file, RMR code map not available yet")
        return None

    rmrcode = rmrcode_from_path(path)
    if rmrcode is None:
        log.info(f"not linking {path}: no RMR code in the client folder")
        return None

    identity_db = ctx.services.identity
    if identity_db is None:
        raise LinkError("identity service is not configured, cannot resolve the client")

    # TODO add error handling
    # what if the client doesn thave a datacard linked
    # what if the clickup id isnt in the identity database
    # what if the rmrcode isnt in the identity database
    client_id = identity_db.client_id_from_rmrcode(rmrcode)
    if client_id is None:
        log.info(f"not linking {path}: no clickup task id for {rmrcode} in identity database")
        return None

    client = ctx.services.clickup.get_task(client_id)
    datacard_ids = getattr(client, "client_data", None) or []
    if not datacard_ids:
        log.info(f"not linking {path}: client {client_id} has no DataCard")
        return None

    datacard_id = datacard_ids[0]
    ctx.services.clickup.link_datafile_to_datacard(ctx.task_id, datacard_id)

    ctx.set_datacard_id(datacard_id)
    ctx.set_client(client)

    log.info(f"linked DataFile {ctx.task_id} to DataCard {datacard_id} ({rmrcode})")
    return datacard_id


def assign_and_watch(ctx: Context) -> bool | None:

    # add account manager as a watcher
    ctx.services.clickup.watch(task_id=ctx.task_id, user_ids=ctx.client.account_manager)

    file_type = TYPE_MAP.get(str(ctx.datafile.file_category))

    # assign datafile based on auto assign fields
    cobra_auto = ctx.datacard.cobra_auto_assign
    flex_auto = ctx.datacard.flex_auto_assign
    cont_auto = ctx.datacard.cont_auto_assign

    if cobra_auto and file_type == "COBRA":
        ctx.services.clickup.assign(task_id=ctx.task_id, user_ids=cobra_auto)
        log.info("Assigning DataFile based on DataCard's COBRA auto assign field.")
        return True

    if flex_auto and file_type == "FLEX":
        ctx.services.clickup.assign(task_id=ctx.task_id, user_ids=cobra_auto)
        log.info("Assigning DataFile based on DataCard's FLEX auto assign field.")
        return True

    if cont_auto and file_type == "Cont":
        ctx.services.clickup.assign(task_id=ctx.task_id, user_ids=cont_auto)
        log.info("Assigning DataFile based on DataCard's Cont auto assign field.")
        return True

    # remove all assignees if the file is in `Files for SS Team to Process` directory
    directory = ctx.datafile.ftp_directory
    if "FILES FOR SS TEAM TO PROCESS" in directory.upper():
        ctx.services.clickup.assign(task_id=ctx.task_id, user_ids=[], remove_old=True)
        log.info("Fild found in `Files for SS Team to Process`, removing assignees.")
        return True

    # assign connection group if the file is in Test Directory
    folders = ctx.datafile.ftp_directory.split("/")
    if "FILE FEEDS" in folders[-2].upper() and "TEST" in folders[-1].upper():
        ctx.services.clickup.assign(task_id=ctx.task_id, group_id=[CONNECTION_USER_GROUP_ID])
        log.info("File found in Test Directory, assigning connection team.")

        return True

    # make sure client is loaded
    if ctx.client is None:
        log.info(f"DataCard ({ctx.datacard_id}) does not have a linked client")
        return False

    # Assign Account/COBRA Manager if permissions are False
    # sounds backwards but if permission is True then it gets
    # sent to dataprocessing, not the account manager. 
    cobra_permission = convert_bool(ctx.datacard.cobra_shared_services_processes)
    flex_permission = convert_bool(ctx.datacard.flex_shared_services_processes)
    cont_permission = convert_bool(ctx.datacard.cont_shared_services_processes)

    assignees = []
    if not any([flex_permission, cont_permission]):
        assignees.extend(ctx.client.account_manager)

    if not cobra_permission:
        assignees.extend(ctx.client.cobra_manager)

    ctx.services.clickup.assign(task_id=ctx.task_id, user_ids=assignees)
    log.info(f"Assigned Datafile {ctx.task_id} to {assignees}")
    return True