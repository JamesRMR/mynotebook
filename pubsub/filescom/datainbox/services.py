import os
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from rockyclickup.database_interface import get_custom_field_by_name, get_all_users
from rockyclickup.wrapper import Session as RCU
from rockyclickup.models import DataFile
from rockyclickup.utils import convert_datetime, response_to_model

from rockyfilescom.wrapper import Session as RFC

from odin import PostgresWrapper

from .utils import generate_checksum, narrow_task


log = logging.getLogger("datainbox.pipeline")

METADATA_ATTEMPTS = 5


class MetadataWriteError(RuntimeError):
    """A custom-metadata write could not be confirmed after every attempt."""


class FieldResolutionError(RuntimeError):
    """A DataFile field name has no matching ClickUp custom field."""


class DataFileCreateError(RuntimeError):
    """A DataFile create call came back without a usable task id."""



class ClickUpService:
    def __init__(self):
        self._session = None
        self._fields: dict[str, Any] = {}
        self._category_labels: dict[str, str] | None = None
        self._users = None


    @property
    def session(self):
        if self._session is None:
            self._session = RCU()

        return self._session


    @property
    def all_users(self):
        if not self._users:
            self._users = get_all_users()

        return [u.clickup_id for u in self._users]


    def _field(self, name: str):
        """Resolve (and cache) the ClickUp custom field behind a DataFile attribute."""
        if name not in self._fields:
            found = get_custom_field_by_name(name)
            if found is None:
                raise FieldResolutionError(f"no ClickUp custom field named {name!r}")

            self._fields[name] = found

        return self._fields[name]


    def field_id(self, name: str) -> str:
        return self._field(name).field_id


    def category_label(self, category_id: str | None) -> str | None:
        """Map a ``file_category`` option id to its label (e.g. -> ``"FLEX"``).

        The DataFile model reads ``file_category`` back as a label while writes
        take the option id, so a diff has to compare in one or the other.
        """
        if category_id is None:
            return None

        if self._category_labels is None:
            self._category_labels = {o.option_id: o.name for o in self._field("file_category").options}

        return self._category_labels.get(category_id)


    def task_comments(self, task_id: str | None):
        if not task_id:
            return None

        res = self.session.get(
            f"{self.session.base}/task/{task_id}/comment"
        )

        return str(res)


    @staticmethod
    def _field_value(value: Any) -> Any:
        return convert_datetime(value) if isinstance(value, dt.datetime) else value


    def create_datafile(self, name: str, fields: dict[str, Any]) -> str:
        """Create a DataFile task and return its new task id.

        Args:
            name:   the task name (top-level, not a custom field).
            fields: DataFile attribute name -> value, written as custom fields.
        """
        custom_fields = []
        for field_name, value in fields.items():
            if value is None:
                continue

            custom_fields.append({"id": self.field_id(field_name), "value": self._field_value(value)})

        payload = {"name": name, "custom_fields": custom_fields}
        url = f"{self.session.base}/list/{DataFile.list_id}/task"
        response = self.session.post(endpoint=url, payload=payload)

        task_id = response.get("id")
        if not task_id:
            raise DataFileCreateError(f"create returned no task id for {name!r}: {response}")

        log.info(f"created DataFile {task_id} for {name!r}")
        return task_id


    def update_datafile_fields(self, task_id: str, changes: dict[str, Any]):
        """Patch only the given custom fields on an existing DataFile."""
        for field_name, value in changes.items():
            self.session.patch(task_id, self.field_id(field_name), self._field_value(value))
            log.info(f"patched {field_name} on {task_id}")


    def rename_task(self, task_id: str, name: str):
        """Set the task's top-level name (not a custom field, so not patchable)."""
        self.session.put(f"{self.session.base}/task/{task_id}", payload={"name": name})
        log.info(f"renamed {task_id} to {name!r}")


    def get_task(self, task_id: str, raw: bool = False):

        # TODO add error handling
        # what if we are searching for a task id found in Files.com file custom metadata that no longer exists in clickup ([401] team not authorized)
        # what if we are searching for a bogus task id  ([401] team not authorized)

        response = self.session.get_task_by_id(task_id)

        if raw:
            return response
        
        return response_to_model(response)


    def link_datafile_to_datacard(self, datafile_id: str, datacard_id: str):
        """Add the DataFile to the DataCard's `inbox` relationship field.

        The link lives on the DataCard side, so this patches the DataCard.
        """
        self.session.patch(datacard_id, self.field_id("inbox"), add=[datafile_id])
        log.info(f"linked DataFile {datafile_id} to DataCard {datacard_id}")


    def search_datafiles(self, ftp_filename: str, ftp_directory: str) -> list[DataFile]:
        query = self.session.query(DataFile).equals("ftp_filename", ftp_filename).equals("ftp_directory", ftp_directory).include_closed()
        result = query.all()

        return [response_to_model(r) for r in result]


    def assign(self, task_id: str, user_ids: list[int] | None = None, group_ids: list[str] | None = None, remove_old: bool = False):
        if not task_id or not isinstance(task_id, str):
            raise TypeError(f"assign needs a task id, got {task_id!r}")

        payloads = []

        if user_ids is not None:
            try:
                user_ids = [int(u) for u in user_ids]
            except (TypeError, ValueError) as e:
                raise TypeError(f"user_ids must be ClickUp user ids, got {user_ids!r}") from e

            rem = []
            if remove_old:
                keep = set(user_ids)
                rem = [u for u in self.current_assignees(task_id) if u not in keep]

            payloads.append({"assignees": {"add": user_ids, "rem": rem}})

        if group_ids:
            payloads.append({"group_assignees": {"add": list(group_ids)}})

        for payload in payloads:
            self.session.put(
                f"{self.session.base}/task/{task_id}",
                payload=payload
            )


    def watch(self, task_id: str, user_ids: list[int] | None = None):
        if user_ids is None:
            return

        try:
            user_ids = [int(u) for u in user_ids]

        except (TypeError, ValueError) as e:
            raise TypeError(f"user_ids mst be ClickUp user ids, got {user_ids!r}") from e

        self.session.put(
            f"{self.session.base}/task/{task_id}/",
            payload={
                "watchers": {
                    "add": user_ids
                }
            }
        )


    def current_assignees(self, task_id: str) -> list[int]:
        return [a["id"] for a in self.session.get_task_by_id(task_id).get("assignees", [])]


    def tag(self, task_id: str, tag: str):
        if not task_id or not isinstance(task_id, str):
            raise ValueError(f"Must provide task_id to tag, got {task_id!r}.")

        self.session.post(f"{self.session.base}/task/{task_id}/tag/{tag}")


    def set_status(self, task_id: str, status):
        if not task_id or not isinstance(task_id, str):
            raise ValueError(f"Must provide task_id to set status, got {task_id!r}.")

        self.session.put(
            f"{self.session.base}/task/{task_id}",
            payload={
                "status": status
            }
        )


    def time_in_status(self, task_id: str):
        if not task_id or not isinstance(task_id, str):
            raise ValueError(f"Must provide task_id to get time_in_status, got {task_id!r}")

        res = self.session.get(
            f"{self.session.base}/task/{task_id}/time_in_status"
        )

        return str(res)



class FilescomService:
    def __init__(self):
        self._session = None


    @property
    def session(self):
        if self._session is None:
            self._session = RFC()

        return self._session


    def get_file(self, path: str):
        # TODO distinguish "not found" form transient errors so the
        # reconsile REQUIRED load can nack on transient an no-op on gone

        try:
            return self.session.get_file(path)

        except Exception as e:
            log.warning (f"Files.com get_file({path}) returned nothing: {e}")
            return None


    def list_contents(self, path: str) -> list[Any]:
        return self.session.list_contents(path)


    ### custom metadata (DESIGN 8)

    def set_custom_metadata(self, path: str, metadata: dict[str, Any], attempts: int = METADATA_ATTEMPTS) -> bool:
        """Merge ``metadata`` into the file's custom metadata, confirming the write.

        Read-merge-write, so keys we don't own survive: Files.com takes
        ``custom_metadata`` as a whole object on PATCH, so writing a bare
        ``{"task_id": ...}`` risks dropping everything else. Each attempt reads
        the file back and only reports success once the values are actually there.

        Returns:
            True once every requested key reads back with the expected value.

        Raises:
            MetadataWriteError: if no attempt could be confirmed.
        """

        desired = {k: str(v) for k, v in metadata.items()}
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                current = self._custom_metadata(path)
                if all(current.get(k) == v for k, v in desired.items()):
                    log.info(f"custom metadata on {path} already up to date")
                    return True

                f = self.session.get_file(path)
                f.update({"custom_metadata": {**current, **desired}})

                written = self._custom_metadata(path)
                if all(written.get(k) == v for k, v in desired.items()):
                    log.info(f"set custom metadata {list(desired)} on {path} (attempt {attempt})")
                    return True

                last_error = MetadataWriteError(f"read back {written} after writing {desired}")

            except Exception as e:
                last_error = e

            log.warning(f"custom metadata attempt {attempt}/{attempts} on {path} failed: {last_error}")

        raise MetadataWriteError(f"could not confirm custom metadata on {path} after {attempts} attempts: {last_error}")


    def set_task_id(self, path: str, task_id: str) -> bool:
        """Write ``task_id`` into the file's custom metadata (DESIGN 8)."""
        return self.set_custom_metadata(path, {"task_id": task_id})


    def _custom_metadata(self, path: str) -> dict[str, str]:
        f = self.session.get_file(path)
        if f is None:
            raise MetadataWriteError(f"no Files.com file at {path}")

        return dict(getattr(f, "custom_metadata", None) or {})



class IdentityService:
    def __init__(self):
        self._db = None
        self._connection_params = None


    @property
    def db(self):
        if self._db is None:
            conn = self.connection_params
            self._db = PostgresWrapper(**conn)
            self._db.test_connection()

        return self._db


    @property
    def connection_params(self):
        if self._connection_params is None:
            self._connection_params = {
                "instance_connection_name": os.getenv("IDENTITY_DB_CONNECTION_NAME"),
                "db_name": os.getenv("IDENTITY_DB_NAME"),
                "user": os.getenv("IDENTITY_USER"),
                "password": os.getenv("IDENTITY_PASSWORD"),
            }


        return self._connection_params


    def client_id_from_rmrcode(self, rmrcode: str) -> str | None:
        return self.db.query_scalar(
            """
                SELECT cu.external_id
                FROM identity_crosswalk     src
                JOIN source_systems         src_sys ON src_sys.id = src.system_id
                JOIN identity_crosswalk     cu      ON cu.entity_id = src.entity_id
                JOIN source_systems         cu_sys  ON cu_sys.id = cu.system_id
                WHERE src.external_id   =   %s
                AND src_sys.code        =   %s
                AND cu_sys.code         =   'clickup'
            """,
            [rmrcode, "rmr"]
        )


class DataFileDBService:
    def __init__(self):
        self._db = None


    @property
    def db(self)-> PostgresWrapper:
        if self._db is None:
            self._db = PostgresWrapper(
                instance_connection_name = os.getenv("DATAINBOX_DB_CONNECTION_NAME"),
                db_name = os.getenv("DATAINBOX_DB_NAME"),
                user = os.getenv("DATAINBOX_USER"),
                password = os.getenv("DATAINBOX_PASSWORD"),
                ip_type = os.getenv("DATAINBOX_DB_IP_TYPE", "public"),
            )

        return self._db


    def test_connection(self, verbose, trace):
        return self.db.test_connection(verbose=verbose, trace=trace)


    def sync_datafile(self, ctx):

        # check to see if task_id appears in the database
        exists = self.db.get_table_item_by_attribute("datafiles", "task_id", ctx.task_id)

        # if not found, add to database
        if exists is None:
            return self.add_datafile(ctx)

        else:
            return self.update_datafile(ctx, exists)


    def add_datafile(self, ctx) -> dict:

        # fetch fresh datafile from clickup
        raw_json = ctx.services.clickup.get_task(ctx.task_id, raw=True)

        narrow = narrow_task(raw_json)
        checksum = generate_checksum(narrow)

        narrow['checksum'] = checksum
        narrow['raw_json'] = raw_json

        new_row = self.db.add_item_to_table("datafiles", values=narrow)

        return new_row


    def update_datafile(self, ctx, existing_row) -> dict:

        # fetch fresh datafile from clickup
        raw_json = ctx.services.clickup.get_task(ctx.task_id, raw=True)

        # check if clickups `date_updated` matches what we have recorded in the database
        task_last_update = raw_json.get("date_updated")
        row_last_update = existing_row.get("date_task_updatd")

        # if they match, we dont need to update anything
        if task_last_update == row_last_update:
            return existing_row

        narrow = narrow_task(raw_json)
        new_checksum = generate_checksum(narrow)

        narrow["checksum"] = new_checksum
        narrow["raw_json"] = raw_json
        narrow['date_modified'] = dt.datetime.now() # this should be getting updated automatcially by the database, idk why its not

        # send changes to database"
        updated_row = self.db.update_table_item("datafiles", values=narrow, where={"task_id": ctx.task_id})

        return updated_row



@dataclass(frozen=True)
class Services:
    """The external services the pipeline depends on, bundled for injection."""

    filescom: FilescomService
    clickup: ClickUpService
    identity: IdentityService
    datafiles: DataFileDBService


def default_services() -> Services:
    return Services(
        filescom=FilescomService(),
        clickup=ClickUpService(),
        identity=IdentityService(),
        datafiles=DataFileDBService(),
    )