"""
██████╗░░█████╗░████████╗░█████╗░██╗███╗░░██╗██████╗░░█████╗░██╗░░██╗
██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗██║████╗░██║██╔══██╗██╔══██╗╚██╗██╔╝
██║░░██║███████║░░░██║░░░███████║██║██╔██╗██║██████╦╝██║░░██║░╚███╔╝░
██║░░██║██╔══██║░░░██║░░░██╔══██║██║██║╚████║██╔══██╗██║░░██║░██╔██╗░
██████╔╝██║░░██║░░░██║░░░██║░░██║██║██║░╚███║██████╦╝╚█████╔╝██╔╝╚██╗
╚═════╝░╚═╝░░╚═╝░░░╚═╝░░░╚═╝░░╚═╝╚═╝╚═╝░░╚══╝╚═════╝░░╚════╝░╚═╝░░╚═╝.functions
"""

# pylint: disable=broad-exception-caught

from os import path, getenv
import time
import json
from datetime import datetime as dt, UTC, date
from copy import deepcopy
from requests.exceptions import RequestException
from files_sdk import folder, set_api_key
from files_sdk.error import DestinationParentDoesNotExistError
from rockyclickup import clickup
from rockyclickup.utils import convert_datetime
from rockyclickup.wrapper import Query, Session
from rockyclickup.models import DataFile, DataCard
from rockyclickup.database_interface import get_field_by_name
from rockydb.connection import CoreDB
from rockydb.models import DataFile as cdb_DataFile, DataCard as cdb_DataCard
from rockyfilescom.wrapper import Session as RFC_sesh
from rmrhermes.chatterbox import Chatterbox

from apps.common.constants import GOOGLE_CREDS
from apps.common.utils import (
    string_to_bool,
    list_to_string,
    get_raw_clickup_task,
    get_custom_field_option,
    str_to_bool,
)
from apps.common.firestore_db import get_firestore_connection

from .schemas import FilescomWebhook
from .constants import FILTER_DICT, TYPE_MAP
from .datafile_obj import DataFileObj

cb = Chatterbox("DATAINBOX", details=["module", "value", "path", "line"])
handle_filescom_cb = Chatterbox(
    "HANDLE FILESCOM WEBHOOK", details=["module", "value", "path", "line"]
)
create_datafile_cb = Chatterbox("CREATE DATAFILE", details=["module", "value", "path", "line"])
update_datafile_cb = Chatterbox("UPDATE DATAFILE", details=["module", "value", "path", "line"])
update_folder_cb = Chatterbox("UPDATE FOLDER", details=["module", "value", "path", "line"])
core_db_cb = Chatterbox("DATAINBOX CORE DB", details=["module", "value", "path", "line"])


def set_task_id_on_filescom_file(datafile_obj: DataFileObj) -> bool:
    """Attempts to set the task id of the clickup task on the file in FilesCom

    Args:
        datafile_obj (DataFileObj): datafile object to get task id and path

    Returns:
            bool: True if the function worked else False
    """
    sesh = RFC_sesh()
    cb("attempting to set task id on FilesCom custom metadata")
    for i in range(1, 6):
        f = sesh.get_file(datafile_obj.full_path)
        f.update({"custom_metadata": {"task_id": datafile_obj.task_id}})
        # pylint: disable-next=no-member
        if len(sesh.get_file(datafile_obj.full_path).custom_metadata) > 0:
            cb(f"set task id {datafile_obj.task_id} on file on attempt: {i}")
            return True
        cb(f"attempt {i} failed, trying again")
        return False


def log_delete(payload: FilescomWebhook):
    """log deletion of a datafile in FireStore DB

    Args:
        payload (FilescomWebhook): webhook received
    """
    cb("logging deletion in firestore")
    fs = get_firestore_connection("filescom_delete_log")
    dict_payload = payload.dict()
    name = str(dt.now(tz=UTC))
    fs.add_to_collection(dict_payload, name)


def determine_file_type(data_file: DataFile) -> str | None:
    """iterates over filter dictionary in reverse and checks rules according to the filter dict

    Args:
        data_file (DataFile): datafile model without a type set

    Returns:
        str: string representation of the category
    """
    file_category = None

    # get list of reversed filter keys
    reversed_keys = list(FILTER_DICT.keys())[::-1]
    delims = [" ", "_", "-", "."]
    filename = data_file.ftp_filename.lower()
    for delim in delims:
        filename = filename.replace(delim, "|")
    name_split = filename.split("|")

    path_split = data_file.ftp_directory.split("/")

    # loop through file types
    for filter_type in reversed_keys:
        # look for substring filters in file name
        if "substrings" in FILTER_DICT[filter_type]["filters"]:
            # loop through filter_type substrings
            for substring in FILTER_DICT[filter_type]["filters"]["substrings"]:
                # loop through substrings in filename
                for i, filename_substring in enumerate(name_split):
                    # check individual substrings
                    if substring == filename_substring:
                        file_category = FILTER_DICT[filter_type]["id"]

                    # check for substring filters with spaces
                    if " " in substring:
                        subsubstrings = substring.split(" ")
                        for ii, subsubstring in enumerate(subsubstrings):
                            if subsubstring == filename_substring:
                                try:
                                    if subsubstrings[ii + 1] == name_split[i]:
                                        file_category = FILTER_DICT[filter_type]["id"]
                                except IndexError:
                                    continue

        # look for folder filters in file path
        if "folder_names" in FILTER_DICT[filter_type]["filters"]:
            for folder_name in FILTER_DICT[filter_type]["filters"]["folder_names"]:
                for fldr in path_split:
                    if folder_name.lower() == fldr.lower():
                        file_category = FILTER_DICT[filter_type]["id"]

    if not file_category:
        file_category = "433537c3-29b7-494d-afae-0d9603649c30"  # CLIENT_INBOX

    return file_category


def file_exists(datafile_obj: DataFileObj, original_name=None) -> DataFile | bool:
    """checks if file exists and returns datafile if it does

    Args:
        file_name (str): the name of the file to check if exists
        file_path (str): file path

    Returns:
        DataFile or Bool: if the file exists return the model, if it does not return False
    """
    # TODO use new cdb instead of querying clickup
    original_name = datafile_obj.file_name if original_name is None else original_name
    query = (
        Query(DataFile)
        .exactly("ftp_filename", original_name)
        .exactly("ftp_directory", datafile_obj.file_path)
    )

    res_files = clickup.search(query).data

    if not res_files or len(res_files) == 0:
        return False

    for file in res_files:
        name_field = [f for f in file["custom_fields"] if f["name"] == "FTP: Filename"]

        if not name_field or len(name_field) == 0:
            continue

        name = name_field[0]["value"]
        if name == original_name:
            data_file = DataFile(id=file["id"])
            return data_file

    return False


def set_status(datafile: DataFile) -> DataFile:
    """set status on clickup item

    Args:
        datafile (DataFile): datafile model

    Returns:
        DataFile: datafile model
    """
    session = Session()
    datafile_json = session.get(f"https://api.clickup.com/api/v2/task/{datafile.id}").json()
    if datafile_json["date_done"] is not None:
        cb("status is not 'open'")
        return datafile
    datafile_assignees = datafile_json["assignees"]
    if len(datafile_assignees) > 0:
        cb("has assignees marking as processed")
        datafile.status = "processed"
    else:
        cb("does not have assignees marking as not to process")
        datafile.status = "not to process"
    return datafile


def create_data_file(payload: FilescomWebhook, printed_payload: str) -> tuple[int, dict[str:str]]:
    """creates a datafile in clickup from a resource.upload

    Args:
        payload (EventData): files.com payload

    Returns:
        http response
    """
    try:
        datafile_obj = DataFileObj()
        datafile_obj.set_payload(payload=payload)

        # check if file is already in DataInbox
        try:
            existing_file = file_exists(datafile_obj)
            if existing_file:
                create_datafile_cb(
                    f"`DataFile with id: {existing_file.id} and file "
                    f"path: {existing_file.name} exists updating.`",
                    level='INFO',
                    slack=False,
                )
                return update_data_file(payload, printed_payload)

        except (RequestException, KeyError, IndexError, AttributeError) as e:
            create_datafile_cb(
                f"`Error checking existing data files.`\n{str(e)}",
                level="WARNING",
                slack=True,
            )

        # populate data file model with webhook data
        try:
            datafile = DataFile(
                name=datafile_obj.file_name,
                ftp_user=payload.username,
                ftp_filename=datafile_obj.file_name,
                ftp_directory=datafile_obj.resources.path.replace(datafile_obj.file_name, "")[:-1],
                file_date=datafile_obj.created_at,
                received=convert_datetime(
                    dt(year=date.today().year, month=date.today().month, day=date.today().day)
                ),  # TODO see if this can be done differently
                archived=False,
            )
        except Exception as e:
            return 400, {
                "message": create_datafile_cb(
                    f"`Error populating and creating DataFile ({datafile_obj.file_name})`\n{e}\nPAYLOAD:\n```{payload}```",
                    level="ERROR",
                    slack=True,
                )
            }

        # determine and set file type
        file_type = determine_file_type(datafile)
        if file_type:
            datafile.file_category = file_type
        else:
            create_datafile_cb(
                "`Unable to determine file type from " f"file name/path`\nPAYLOAD:```{payload}```",
            )

        # create card on clickup
        try:
            create_response = clickup.create(datafile)
        except Exception as e:
            return 400, {
                "message": create_datafile_cb(
                    f"@channel\n`Error creating DataFile ({datafile.name}) on ClickUp`\n{e}",
                    level="ERROR",
                    slack=True,
                )
            }

        try:
            datafile_obj.set_task_id(create_response["id"])

        except Exception as e:
            return 202, {
                "message": create_datafile_cb(
                    f"`Error capturing data file id ({datafile_obj.file_name}), unable to link client and DataCard.`",
                    level="WARNING",
                    slack=True,
                )
            }

        metadata_set = False
        try:
            metadata_set = set_task_id_on_filescom_file(datafile_obj)
        except Exception as e:
            create_datafile_cb(f"Error setting task id in FilesCom metadata\n\texception:\n{e}")

        datafile_obj.link()
        datafile_obj.assign_or_add_watcher()

        # add tags
        try:
            if ".pgp" in datafile_obj.datafile.ftp_filename:
                clickup.post(
                    endpoint=f"{clickup.base}/task/{datafile_obj.task_id}/tag/decrypt", payload={}
                )
        except Exception as e:
            create_datafile_cb(
                f"`Error adding decrypt tag to new DataFile`\n{e}",
                level="WARNING",
            )

        try:
            ftp_dir = datafile_obj.datafile.ftp_directory
            if "/Snow Globe Theater - RMRSNOW/" in ftp_dir or "testsite" in payload.accountName:
                clickup.post(
                    endpoint=f"{clickup.base}/task/{datafile_obj.task_id}/tag/debug", payload={}
                )
        except Exception as e:
            create_datafile_cb(
                f"`Error adding debug tag to new DataFile`\n{e}",
                level="WARNING",
            )

        if not metadata_set:
            try:
                set_task_id_on_filescom_file(datafile_obj)
            except Exception as e:
                create_datafile_cb(f"Error setting task id in FilesCom metadata\n\texception:\n{e}")

        try:
            ftp_dir = datafile_obj.datafile.ftp_directory.lower()
            if "archived" in ftp_dir or "termed" in ftp_dir:
                datafile_obj.datafile.status = "TERMED CLIENT"
                clickup.update(datafile_obj.datafile)
        except Exception as e:
            create_datafile_cb(
                f"`Error adding termed status to new DataFile`\n{e}",
                level="WARNING",
            )

        except Exception as e:
            create_datafile_cb(
                f"`Error assigning group to new DataFile`\n{e}",
                level="WARNING",
            )

        if datafile_obj.task_id is not None:
            added = add_or_update_datafile(datafile_obj.task_id)
            if not added:
                create_datafile_cb("could not add new DataFile to CoreDB")

        return 200, {
            "message": create_datafile_cb(
                f"`Sucessfully created new data file!`\n```{str(datafile_obj.task_id)}```"
            ),
            "id": datafile_obj.task_id,
            "id_source": "ClickUp",
        }
    except Exception as e:
        return 400, {
            "message": create_datafile_cb(
                f"`Error creating data file`({datafile_obj.file_name})\n{e}\nPAYLOAD:\n```{printed_payload}```",
                level="ERROR",
                slack=True,
            )
        }


def update_data_file(payload: FilescomWebhook, printed_payload: str) -> tuple[int, dict[str:str]]:
    """updates a clickup datafile if operation is resource.move

    Args:
        payload (EventData): files.com payload

    Returns:
        http response
    """
    try:
        try:
            datafile_obj = DataFileObj()
            datafile_obj.set_payload(payload)
            original_name = datafile_obj.resources.path.split("/")[-1]

        except Exception as e:
            return 400, {
                "message": update_datafile_cb(
                    f"`Error parsing payload to update data file`\n{e}",
                    level="ERROR",
                    slack=True,
                )
            }
        update_metadata = True

        find_count = find_delta = 5

        while True:
            if datafile_obj.datafile is None:
                original_datafile = file_exists(datafile_obj, original_name=original_name)
                datafile_obj.set_task_id(original_datafile.id)
            else:
                update_datafile_cb("loading DataFile from custom metadata")
                original_datafile = datafile_obj.datafile
                update_metadata = False

            if original_datafile is not False:
                break

            if find_count == 0:
                return 202, {
                    "message": update_datafile_cb(
                        f"unable to find DataFile `{original_name}` max retry attempts reached",
                        level="ERROR",
                        slack=True,
                    ),
                }

            time.sleep(
                find_delta + abs(find_count - find_delta)
            )  # Increase time sleep by one each iteration from 5 second to 9 seconds
            find_count -= 1
            update_datafile_cb(
                f"Could not find existing DataFile, trying again. Retrys left: {find_count}"
            )

        # get and update DataFile name
        if not original_datafile:
            return 202, {
                "message": update_datafile_cb(
                    f"unable to find DataFile `{original_name}`",
                    level="ERROR",
                    slack=True,
                ),
            }

        # update task name and ftp_filename field
        updated_datafile = deepcopy(original_datafile)
        if updated_datafile.ftp_filename != datafile_obj.file_name:
            updated_datafile.name = datafile_obj.file_name
            updated_datafile.ftp_filename = datafile_obj.file_name

        # check if file has moved
        if (
            datafile_obj.destination_resource
            and updated_datafile.ftp_directory != datafile_obj.destination_path
        ):

            # update DataFile FTP: File directory
            updated_datafile.ftp_directory = datafile_obj.destination_path
            update_datafile_cb(
                f"Updating DataFile filepath from\n\t{datafile_obj.file_path}"
                f"\n\tto\n\t{datafile_obj.destination_path}"
            )
            if "complete" in datafile_obj.destination_path.lower():
                update_datafile_cb("attempting status change check")
                updated_datafile = set_status(updated_datafile)

        # update DataFile in ClickUp
        if updated_datafile != original_datafile:
            update_datafile_cb("sending updated DataFile to ClickUp")
            try:
                res_patch = clickup.update(updated_datafile)
                update_datafile_cb(res_patch)
            except Exception as e:
                return 400, {
                    "message": update_datafile_cb(
                        f"`Error sending updated DataFile to ClickUp`\n{e}",
                        level="ERROR",
                        slack=True,
                    )
                }

            datafile_obj.update_datafile()
            datafile_obj.link(datafile_obj.destination_path)

            try:
                if (
                    "archived" in datafile_obj.destination_path.lower()
                    or "termed" in datafile_obj.destination_path.lower()
                ):
                    updated_datafile.status = "TERMED CLIENT"
                    clickup.update(updated_datafile)
            except Exception as e:
                update_datafile_cb(
                    f"`Error adding termed status to new DataFile`\n{e}",
                    level="WARNING",
                )

            try:
                if update_metadata:
                    set_task_id_on_filescom_file(datafile_obj)
            except Exception as e:
                update_datafile_cb(f"Error setting task id in FilesCom metadata\n\texception:\n{e}")

            return 200, {
                "message": update_datafile_cb(
                    f"`updated DataFile`\n```{updated_datafile.id}```",
                ),
                "id": updated_datafile.id,
                "id_source": "ClickUp",
            }

        return 208, {
            "message": update_datafile_cb(
                "`DataFile already up to date!`",
                level="INFO",
                slack=True,
            ),
            "id": updated_datafile.id,
            "id_source": "ClickUp",
        }
    except Exception:
        return 400, {
            "message": update_datafile_cb(
                f"`can't update DataFile`\nPAYLOAD:\n```{printed_payload}```",
                level="ERROR",
                slack=True,
            )
        }


def update_folder(payload: FilescomWebhook) -> tuple[int, dict[str:str]]:
    """updates a folders items in clickup when the folder is renamed or moved

    Args:
        payload (EventData): files.com payload item, see schemas

    Returns:
        http_response: 200 if successful, 400 if not
    """
    try:
        resource = payload.eventData.resources
        dst_resource = payload.eventData.destinationResource
        folder_path = dst_resource.path + "/" + resource.name
        ## get all files inside folder
        try:
            time.sleep(0.5)
            sesh = RFC_sesh()
            files = sesh.list_contents(folder_path)
            # get task id from the meta data of the file
            task_ids = [
                x.custom_metadata["task_id"] for x in files if "task_id" in x.custom_metadata.keys()
            ]
            ## iterate over files
        except Exception as e:
            return 400, {"message": f"Exception occurred loading FilesCom data\nexception:\n{e}"}
        for task_id in task_ids:
            try:
                field_id = get_field_by_name("ftp_directory").field_id
                url = f"https://api.clickup.com/api/v2/task/{task_id}/field/{field_id}"
                ## change ftp file directory
                payload = {"value": folder_path}
                ## update
                clickup.post(endpoint=url, payload=payload)
            except Exception as e:
                update_folder_cb(f"could not update DataFile with id: {task_id}\nexception: {e}")
        return 200, {
            "message": update_folder_cb("Files FTP directories changed to reflect folder move")
        }
    except Exception as e:
        return 400, {
            "message": update_folder_cb(
                f"an unknown exception has occured updating folder items: {e}"
            )
        }


def add_tag_deleted(task_id: str):
    """adds deleted tag to a datafile and logs it in firestore deleted log

    Args:
        task_id (str): task id to tag
    """
    try:
        url = f"https://api.clickup.com/api/v2/task/{task_id}/tag/Deleted"
        clickup.post(endpoint=url)

    except Exception as e:
        cb(f"could not tag deleted to DataFile with id: {task_id}\nexception: {e}")


def file_deleted(payload: FilescomWebhook) -> tuple[int, dict[str:str]]:
    """if file exists mark as deleted and log

    Args:
        payload (dict): filescom payload

    Returns:
        tuple(int, dict): response
    """
    datafile_obj = DataFileObj()
    datafile_obj.payload = payload

    existing_file = file_exists(datafile_obj)
    if not existing_file:
        return 200, {"message": cb("File does not exist")}
    add_tag_deleted(existing_file.id)
    log_delete(payload)
    return 200, {"message": cb("File Marked as deleted")}


def folder_deleted(payload: FilescomWebhook) -> tuple[int, dict[str:str]]:
    """
    iterate over files in folder and mark deleted and log
    """
    resource = payload.eventData.resources
    dst_resource = payload.eventData.destinationResource
    folder_path = dst_resource.path + "/" + resource.name

    sesh = RFC_sesh()
    files = sesh.list_contents(folder_path)
    # get task id from the meta data of the file
    task_ids = [
        fil.custom_metadata["task_id"] for fil in files if "task_id" in fil.custom_metadata.keys()
    ]

    for task_id in task_ids:
        add_tag_deleted(task_id)
    try:
        log_delete(payload)
    except Exception:
        return 202, {
            "message": update_folder_cb("Files FTP directories changed to reflect folder move")
        }
    return 200, {"message": update_folder_cb("Successfully Marked ")}


def is_temp(payload: FilescomWebhook) -> bool:
    """checks if the item uploaded is a temp file and returns true if it is"""
    return "~$" in payload.eventData.resources.path


def _400(printed_payload: str, e=None) -> tuple[int, dict[str:str]]:
    return 400, {
        "message": cb(
            f"`Invalid payload!`\nPAYLOAD:\n```{printed_payload}```\n{e}",
        ),
    }


def handle_filescom_webhook(payload: FilescomWebhook) -> tuple[int, dict[str:str]]:
    """
    Ingests filescom webhook and routes to the appropriate logic
    for the resource type and action combination.
    """

    handle_filescom_cb("handle_filescom_webhook called")

    try:
        printed_payload = json.dumps(payload, indent=4)
    except Exception as e:
        handle_filescom_cb(e)
        printed_payload = payload

    try:
        if is_temp(payload):
            return 202, {
                "message": handle_filescom_cb(
                    f"ignoring temporary file\n`{payload.eventData.resources.path}`",
                    level="INFO",
                    slack=False,
                )
            }
    except Exception as e:
        return _400(printed_payload, e)

    try:
        resource_type = payload.eventData.resources.type
        event = payload.event

        if not resource_type or not event:
            return _400(printed_payload)

    except Exception as e:
        return _400(printed_payload, e)

    if resource_type == "file":
        match event:
            case "resources.upload":
                return create_data_file(payload, printed_payload)
            case "resources.move":
                return update_data_file(payload, printed_payload)
            case "resources.delete":
                return file_deleted(payload)

    elif resource_type == "dir":
        match event:
            case "resources.upload":
                return 202, {"message": f"Unhandled {resource_type}.{event}"}
            case "resources.move":
                return update_folder(payload)
            case "resources.delete":
                return folder_deleted(payload)

    return 400, {
        "message": handle_filescom_cb(
            f"@channel\nUnhandled {resource_type}.{event}",
            slack=True,
            additional_log_val=printed_payload,
        )
    }


def move_file(cuid: str) -> tuple[int, dict[str:str]]:
    """
    file_type (str): COBRA or FLEX
    """
    set_api_key(getenv("FILESCOM_KEY"))

    inbox_item = DataFile(id=cuid)

    file_directory = inbox_item.ftp_directory
    file_name = inbox_item.ftp_filename
    file_type = inbox_item.file_category

    # get files from FTP file directory
    files = folder.list_for(
        file_directory,
        {"with_previews": True, "with_priority_color": True},  # "search_all": True,
    )

    # Find data inbox file
    inbox_file = [f for f in files.auto_paging_iter() if f.display_name == file_name]

    # cannot find file in directory
    if len(inbox_file) == 0:
        cb(f"{file_name} not in directory, unable to process...")
        return 400, {
            "message": cb({"message": f"{file_name} not in directory, unable to process..."}),
        }

    # multiple files with the same name
    if len(inbox_file) > 1:
        return 200, {
            "message": cb({"message": "Multiple files with the same name, unable to process..."}),
        }

    inbox_file = inbox_file[0]

    file_directory = path.dirname(inbox_file.path)

    # file_type = "COBRA" if file_type == "COBRA" else "FLEX"

    if file_type not in [0, 1]:
        return 200, {
            "message": "File is not of type COBRA or FLEX",
            "id": inbox_item.id,
            "id_source": "ClickUp",
        }
    # Get completed folder
    completed = [
        f
        for f in files.auto_paging_iter()
        if f"Completed {TYPE_MAP[file_type]}" == f.display_name and f.type == "directory"
    ]

    # Create Completed folder if it doesn't exist
    if len(completed) == 0:
        folder.create(
            f"{file_directory}/Completed {TYPE_MAP[file_type]}",
            {
                "mkdir_parents": False,
                "provided_mtime": dt.now().isoformat()[:-7],
            },
        )

    try:
        destination = f"{file_directory}/Completed {TYPE_MAP[file_type]}/{inbox_file.display_name}"
        inbox_file.move(
            {
                "destination": destination,
                "overwrite": False,
            }
        )
    except DestinationParentDoesNotExistError as e:
        return 200, {
            "message": cb(f"Error moving file: {e}"),
            "id": inbox_item.id,
            "id_source": "ClickUp",
        }
    return 200, {
        "message": cb({"message": "Successfully moved file"}),
        "id": inbox_item.id,
        "id_source": "ClickUp",
    }


def add_datafile_to_db(task_id: str, cdb: CoreDB) -> bool:
    """given a task id and the core connection add the task to the database

    Args:
        task_id (str): task id passed to add into db
        cdb (CoreDB): coredb connection

    Returns:
        bool: if the item got uploaded to coredb
    """
    core_db_cb("Adding DataFile to CoreDB")
    datafile = DataFile(id=task_id)
    status = datafile.status
    description = datafile.description
    date_card_created = datafile.date_created
    ftp_directory = datafile.ftp_directory
    ftp_file_name = datafile.ftp_filename
    date_ftp_file_date = datafile.file_date
    data_card_id = datafile.inbox[0] if datafile.inbox is not None else None

    file_type = TYPE_MAP[str(datafile.file_category)]
    assignee = None
    comments = str(
        clickup.get(endpoint="https://api.clickup.com/api/v2/task/" + task_id + "/comment").json(),
    )
    time_in_status = str(
        clickup.get(
            endpoint="https://api.clickup.com/api/v2/task/" + task_id + "/time_in_status",
        ).json(),
    )
    card_json = str(clickup.get(endpoint="https://api.clickup.com/api/v2/task/" + task_id).json())
    created_by = "RMRCLOUD"
    modified_by = "RMRCLOUD"

    flex_processing = False
    flex_notes = None

    if data_card_id is not None:
        datacard = DataCard(id=data_card_id)
        flex_processing = datacard.flex_shared_services_processes == "true"
        flex_notes = None
        if cdb.get_table_item_by_attribute("datacard", "task_id", data_card_id) is None:
            data_card_id = None

    flex_notes = str(flex_notes)
    date_created = dt.now()

    try:
        cdb.add_data_file(
            task_id=task_id,
            status=status,
            description=description,
            assignee=assignee,
            date_card_created=date_card_created,
            flex_processing=flex_processing,
            ftp_directory=ftp_directory,
            ftp_file_name=ftp_file_name,
            date_ftp_file_date=date_ftp_file_date,
            data_card_id=data_card_id,
            file_type=file_type,
            comments=comments,
            card_json=card_json,
            flex_notes=flex_notes,
            time_in_status=time_in_status,
            date_created=date_created,
            created_by=created_by,
            modified_by=modified_by,
            archived=False,
        )
        return True
    except Exception as e:
        core_db_cb(e)
        cdb.session.rollback()
        cdb.session.flush()
        return False


def update_datafile_in_db(task_id: str, model: cdb_DataFile, cdb: CoreDB) -> bool:
    """given a task id, the model and core db connection update the datafile in core

    Args:
        task_id (str): task id of card to update
        model (DataFile): Core DB model of task ids card
        cdb (CoreDB): Core DB connection

    Returns:
        bool: if operation successful
    """
    core_db_cb("Updating DataFile in CoreDB")
    try:
        update = False
        datafile = DataFile(id=task_id)
        datafile_map = {x.replace("_", ""): (x, y) for x, y in datafile.__dict__.items()}
        model_map = {x.replace("_", ""): (x, y) for x, y in model.__dict__.items()}
        for attribute, val in model_map.items():
            if attribute in datafile_map.keys() and attribute not in ["id", "_sa_instance_state"]:
                clickup_attribute = datafile_map[attribute][1]
                orig_attr_name = model_map[attribute][0]
                if val[1] != clickup_attribute:
                    update = True
                    setattr(model, orig_attr_name, clickup_attribute)

        if update:
            cdb.update_table_item(model, "RMRCLOUD")
        return True
    except Exception as e:
        cb(e)
        return False


def add_or_update_datafile(task_id: str) -> bool:
    """given a task id check if the id exists in the database and update or add

    Args:
        task_id (str): task id of item to add or update

    Raises:
        Exception: generic exception if creation failed

    Returns:
        bool: if operation succeeded
    """
    with CoreDB(google_creds=GOOGLE_CREDS) as cdb:
        datafile_model = cdb.get_table_item_by_attribute(cdb_DataFile, "task_id", task_id)
        try:
            if datafile_model is not None:
                created = update_datafile_in_db(task_id, datafile_model, cdb)
            else:
                created = add_datafile_to_db(task_id, cdb)

            if created:
                return True
            return False
        except Exception as e:
            core_db_cb(e)
            return False
    return False


def data_file_created(task_id: str) -> tuple[int, dict[str:str]]:
    """runs add or update datafile and returns 200 if successful, 400 if not

    Args:
        task_id (str): task id to add or update

    Returns:
        http_response: 200 if successful, 400 if failed
    """
    if add_or_update_datafile(task_id):
        return 200, {
            "message": "successfully uploaded DataFile",
            "id": task_id,
            "id_source": "ClickUp",
        }
    return 400, {
        "message": "Could not add or update DataFile",
        "id": task_id,
        "id_source": "ClickUp",
    }


def archive_and_delete_datafile(task_id: str) -> tuple[int, dict[str:str]]:
    """adds a datafile to core and deletes from clickup

    Args:
        task_id (str): task id of datafile to add or update in core, then delete

    Returns:
        http_response: 200 if successful, 400 if not
    """
    if add_or_update_datafile(task_id):
        clickup.delete(task_id)
        return 200, {
            "message": "successfully archived DataFile",
            "id": task_id,
            "id_source": "ClickUp",
        }
    return 400, {
        "message": "Could not add or update DataFile",
        "id": task_id,
        "id_source": "ClickUp",
    }


def archive_datafile(task_id: str) -> tuple[int, dict[str:str]]:
    """adds a datafile to core and archives that file in clickup

    Args:
        task_id (str): task id of datafile to add or update in core, then delete

    Returns:
        http_response: 200 if successful, 400 if not
    """
    if add_or_update_datafile(task_id):

        params = {"custom_task_ids": "true", "team_id": "9011096643"}
        clickup.put(f"{clickup.base}/task/{task_id}", payload={"archived": True}, query=params)

        return 200, {
            "message": "successfully archived DataFile",
            "id": task_id,
            "id_source": "ClickUp",
        }
    return 400, {
        "message": "Could not add or update DataFile",
        "id": task_id,
        "id_source": "ClickUp",
    }


def add_datacard_to_db(clickup_datacard: DataCard, cdb: CoreDB) -> bool:
    """add DataCard to db"""
    try:
        task = get_raw_clickup_task(clickup_datacard.id)
        flex_transmission_val = get_custom_field_option(
            "2c29401a-6e07-4e91-96f7-3afc217287ab",
            clickup_datacard.flex_transmission,
            task,
        )
        cobra_transmission_val = get_custom_field_option(
            "f6cb0a97-3b62-40be-b793-41537f25995f",
            clickup_datacard.cobra_transmission,
            task,
        )
        cont_transmission_val = get_custom_field_option(
            "cf22f654-296d-4eb6-a2fe-170ef9e6001a",
            clickup_datacard.cont_transmission,
            task,
        )
        cdb.add_data_card(
            task_id=clickup_datacard.id,
            tags=str(clickup_datacard.tags) if clickup_datacard.tags is not None else None,
            hris_payroll_vendor=clickup_datacard.hris_payroll_vendor,
            flex_shared_services_processes=string_to_bool(
                clickup_datacard.flex_shared_services_processes
            ),  # bool
            cobra_shared_services_processes=string_to_bool(
                clickup_datacard.cobra_shared_services_processes
            ),  # bool
            preserve_division=string_to_bool(clickup_datacard.preserve_division),  # bool
            preserve_subsidiary=string_to_bool(clickup_datacard.preserve_subsidiary),  # bool
            directory_file_feed=clickup_datacard.directory_file_feed,
            flex_directory_completed=clickup_datacard.flex_directory_completed,
            cobra_directory_completed=clickup_datacard.cobra_directory_completed,
            flex_transmission=flex_transmission_val,
            flex_frequency=list_to_string(clickup_datacard.flex_frequency),
            flex_notes=None,
            cobra_transmission=cobra_transmission_val,
            cobra_frequency=clickup_datacard.cobra_frequency,
            cobra_notes=None,
            cont_transmission=cont_transmission_val,
            cont_auto_post=list_to_string(clickup_datacard.cont_auto_post),
            cont_auto_post_frequency=list_to_string(clickup_datacard.cont_auto_post_frequency),
            cont_notes=None,
            directory_re_route_on=list_to_string(clickup_datacard.directory_re_route_on),
            directory_re_route=clickup_datacard.directory_re_route,
            inbox=list_to_string(clickup_datacard.inbox),
            cobra_data=list_to_string(clickup_datacard.cobra_data),
            project_data=list_to_string(clickup_datacard.project_data),
            date_data_start=None,  # datetime
            date_data_end=None,  # datetime
            date_created=dt.today(),  # datetime
            created_by="RMRCLOUD",
            date_modified=dt.today(),  # datetime
            modified_by="RMRCLOUD",
        )
        return True
    except Exception as e:
        cb(
            "An Exception occured creating DataCard:"
            f" '{clickup_datacard.id}'\n Exception:```{e}```"
        )
        return False


def update_datacard_in_db(
    datacard_model: cdb_DataCard, clickup_datacard: DataCard, cdb: CoreDB
) -> bool:
    """given a task id, the model and core db connection update the datafile in core

    Args:
        task_id (str): task id of card to update
        model (DataFile): Core DB model of task ids card
        cdb (CoreDB): Core DB connection

    Returns:
        bool: if operation successful
    """
    core_db_cb("Updating DataCard in CoreDB")
    try:
        update = False
        # normalize datafile map and db map
        data_card_map = {x.replace("_", ""): (x, y) for x, y in clickup_datacard.__dict__.items()}
        model_map = {x.replace("_", ""): (x, y) for x, y in datacard_model.__dict__.items()}
        # convert string bools to bools
        broken_bools = {
            x: y[0] for x, y in data_card_map.items() if y[1] == "true" or y[1] == "false"
        }
        for broken_bool_name, broken_bool_name_orig in broken_bools.items():
            data_card_map[broken_bool_name] = (
                broken_bool_name_orig,
                str_to_bool(data_card_map.get(broken_bool_name)[1]),
            )

        # iterate over model and find shared attributes and set them on model
        for attribute, val in model_map.items():
            if attribute in data_card_map.keys() and attribute not in ["id", "_sa_instance_state"]:
                clickup_attribute = data_card_map[attribute][1]
                orig_attr_name = model_map[attribute][0]
                if val[1] != clickup_attribute:
                    update = True
                    setattr(datacard_model, orig_attr_name, clickup_attribute)

        # update if needed
        if update:
            cdb.update_table_item(datacard_model, "RMRCLOUD")
        return True
    except Exception as e:
        core_db_cb(e)
        return False


def add_or_update_data_card(task_id: str) -> tuple[int, dict[str:str]]:
    """
    function to add or update datacards in coreDB
    """
    with CoreDB(google_creds=GOOGLE_CREDS) as cdb:
        clickup_datacard = DataCard(id=task_id)
        core_datacard_model = cdb.get_table_item_by_attribute(
            cdb_DataCard,
            "task_id",
            task_id,
        )
        if core_datacard_model is None:
            if add_datacard_to_db(clickup_datacard, cdb):
                return 200, {"message": core_db_cb("Added DataCard")}
            return 400, {"message": core_db_cb("Adding DataCard failed")}
        else:
            if update_datacard_in_db(core_datacard_model, clickup_datacard, cdb):
                return 200, {"message": core_db_cb("Updated Datacard")}
            return 400, {"message": core_db_cb("Updating DataCard failed")}
