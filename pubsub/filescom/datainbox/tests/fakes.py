"""Fakes for the injectable seams, so tests never touch ClickUp or Files.com.

``FakeFilescom`` subclasses the real :class:`FilescomService` on a fake session,
so the read-merge-write and retry-and-verify logic in ``set_custom_metadata``
is genuinely exercised rather than stubbed out.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datainbox.alerts import LoggingAlerter
from datainbox.categorize import CLIENT_INBOX, COBRA, CONT, FLEX, NDT
from datainbox.context import Context
from datainbox.messages import parse_message
from datainbox.services import FilescomService, Services


CATEGORY_NAMES = {
    CLIENT_INBOX: "CLIENT_INBOX",
    NDT: "NDT",
    CONT: "CONT",
    COBRA: "COBRA",
    FLEX: "FLEX",
}


class FakeFile:
    """Stands in for a files_sdk File, including its PATCH-style update."""

    def __init__(self, custom_metadata=None, created_at="2026-08-01T10:00:00Z"):
        self.custom_metadata = dict(custom_metadata or {})
        self.created_at = created_at
        self.path = "fake"

    def update(self, params):
        self.custom_metadata = dict(params["custom_metadata"])


class DeafFile(FakeFile):
    """Accepts a write and silently drops it, to exercise retry-and-verify."""

    def update(self, params):
        pass


class _FakeFilescomSession:
    def __init__(self, f):
        self.f = f

    def get_file(self, path):
        return self.f

    def list_contents(self, path):
        return []


class FakeFilescom(FilescomService):
    def __init__(self, f=None):
        super().__init__()
        self._session = _FakeFilescomSession(f if f is not None else FakeFile())

    @property
    def file(self):
        return self._session.f


class MissingFilescom(FilescomService):
    """Files.com has no file at the path."""

    def __init__(self):
        super().__init__()

    def get_file(self, path):
        return None


class FakeDataFile:
    """Stands in for a rockyclickup DataFile read back off a task."""

    def __init__(self, id="T1", name=None, ftp_filename=None, ftp_directory=None, file_category=None):
        self.id = id
        self.name = name
        self.ftp_filename = ftp_filename
        self.ftp_directory = ftp_directory
        self.file_category = file_category


class FakeClient:
    """Stands in for a rockyclickup Client task."""

    def __init__(self, client_data=None, account_manager=None, cobra_manager=None):
        self.client_data = list(client_data) if client_data is not None else []
        self.account_manager = list(account_manager) if account_manager is not None else []
        self.cobra_manager = list(cobra_manager) if cobra_manager is not None else []


class FakeDataCard:
    """Stands in for a rockyclickup DataCard task."""

    def __init__(
        self,
        client_data=None,
        cobra_auto_assign=None,
        flex_auto_assign=None,
        cont_auto_assign=None,
        cobra_shared_services_processes=None,
        flex_shared_services_processes=None,
        cont_shared_services_processes=None,
    ):
        self.client_data = list(client_data) if client_data is not None else []
        self.cobra_auto_assign = cobra_auto_assign
        self.flex_auto_assign = flex_auto_assign
        self.cont_auto_assign = cont_auto_assign
        self.cobra_shared_services_processes = cobra_shared_services_processes
        self.flex_shared_services_processes = flex_shared_services_processes
        self.cont_shared_services_processes = cont_shared_services_processes


class FakeIdentity:
    """Resolves an RMR code to a ClickUp client id, or raises."""

    def __init__(self, client_id=None, error=None):
        self.client_id = client_id
        self.error = error
        self.looked_up = []

    def client_id_from_rmrcode(self, rmrcode):
        self.looked_up.append(rmrcode)
        if self.error is not None:
            raise self.error

        return self.client_id


class FakeClickUp:
    """Records writes instead of making them."""

    LABELS = {
        FLEX: "FLEX",
        COBRA: "COBRA",
        CONT: "Cont",
        NDT: "NDT",
        CLIENT_INBOX: "Client Inbox",
    }

    def __init__(
        self,
        matches=(),
        datafile=None,
        new_task_id="NEW1",
        client=None,
        datacard=None,
        link_error=None,
    ):
        self.matches = list(matches)
        self._datafile = datafile
        self.new_task_id = new_task_id
        self._client = client
        self._datacard = datacard
        self.link_error = link_error

        self.created = []
        self.patched = []
        self.renamed = []
        self.links = []

    def get_datafile(self, task_id):
        return self._datafile

    def get_client(self, task_id):
        return self._client

    def get_datacard(self, task_id):
        return self._datacard

    def link_datafile_to_datacard(self, datafile_id, datacard_id):
        if self.link_error is not None:
            raise self.link_error

        self.links.append((datafile_id, datacard_id))

    def search_datafiles(self, ftp_filename, ftp_directory):
        return self.matches

    def category_label(self, category_id):
        return self.LABELS.get(category_id)

    def create_datafile(self, name, fields):
        self.created.append((name, fields))
        return self.new_task_id

    def update_datafile_fields(self, task_id, changes):
        self.patched.append((task_id, changes))

    def rename_task(self, task_id, name):
        self.renamed.append((task_id, name))


def make_context(filescom=None, clickup=None, identity=None, **message_fields):
    """Build a Context around a message, defaulting to a file/create event."""
    fields = {"type": "file", "action": "create"}
    fields.update(message_fields)

    return Context(
        parse_message(fields),
        Services(
            filescom=filescom if filescom is not None else FakeFilescom(),
            clickup=clickup if clickup is not None else FakeClickUp(),
            identity=identity,
        ),
        LoggingAlerter(),
    )
