import json
import hashlib
from ast import literal_eval
from rockyclickup.utils import response_to_model


def watch(task_id: str, user_id: int):
    pass


def convert_bool(value: any):
    return bool(literal_eval(str(value).capitalize()))


    
def narrow_task(raw_task: dict):
    model = response_to_model(raw_task)

    print([str(a.get("id", "?")) for a in model.assignees])

    return {
        "task_id": model.id,
        "task_name": model.name,
        "status": model.status,
        "archived": model.archived,
        "assignees": [str(a.get("id", "?")) for a in model.assignees],
        "file_name": model.ftp_filename,
        "file_directory": model.ftp_directory,
        "category": model.file_category,
        "date_received": model.received,
        "date_task_created": raw_task.get("date_created"),
        "date_task_updated": raw_task.get("date_updated"),
        "datacard": model.inbox,
        "raw_json": raw_task
    }


def generate_checksum(narrowed_task):
    exclude = {"raw_json", "date_received", "date_task_created", "date_task_updated"}
    dict_to_encode = {k: v for k, v in narrowed_task.items() if k not in exclude}

    encoded = json.dumps(dict_to_encode, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
