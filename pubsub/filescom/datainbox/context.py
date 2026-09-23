import logging

from contextlib import contextmanager
from typing import Iterator

from files_sdk.models import File
from rockyclickup.models import Client, DataCard, DataFile

from .messages import InboundMessage
from .alerts import Alerter
from .results import Result
from .services import Services

log = logging.getLogger("datainbox.pipeline")


class _Unset:
    """distinct from ``None`` so "not loaded yet" != "loaded, abset"."""


_UNSET = _Unset()


class Context:
    def __init__(self, msg: InboundMessage, services: Services, alerter: Alerter):
        self.msg: InboundMessage = msg
        self.services: Services = services
        self.alerter: Alerter = alerter

        self.task_id: str | None = None
        self.category_id: str | None = None
        self.datacard_id: str | None = None

        self._rfc_file: File = _UNSET
        self._datafile: DataFile = _UNSET
        self._datacard: DataCard = _UNSET
        self._client: Client = _UNSET
        self._failures: list[str] = []


    ### raw message fields

    @property
    def action(self) -> str:
        return self.msg.action

    
    @property
    def type(self) -> str:
        return self.msg.type

    
    @property
    def path(self) -> str:
        return self.msg.path

    
    @property
    def destination(self) -> str:
        return self.msg.destination

    
    @property
    def username(self) -> str:
        return self.msg.username

    
    @property
    def target_path(self) -> str:
        """path to act on. destination for a move, otherwise the source path."""
        return self.msg.target_path

    
    @property
    def ftp_filename(self) -> str:
        """Filename component of the target path (matches the ClickUp field)."""
        return self.target_path.rsplit("/", 1)[-1]

    
    @property
    def ftp_directory(self) -> str:
        """Directory component of the target path (no trailing slash)."""
        p = self.target_path
        return p.rsplit("/", 1)[0] if "/" in p else ""


    ### lazy Files.com file

    @property
    def rfc_file(self) -> File:
        """The Files.com file at the target path, loaded once (``None`` if absent)."""
        if self._rfc_file is _UNSET:
            self._rfc_file = self.services.filescom.get_file(self.target_path)

        return self._rfc_file


    @property
    def metadata_task_id(self) -> str | None:
        """``task_id`` stored in the Files.com custom metadata, if any."""
        f = self.rfc_file
        if f is None:
            return None

        meta = getattr(f, "custom_metadata", None) or {}

        try:
            return meta.get("task_id")

        except AttributeError:
            return None


    ### lazy ClickUp DataFile

    @property
    def datafile(self) -> DataFile:
        if self._datafile is _UNSET:
            self._datafile = self.services.clickup.get_task(self.task_id) if self.task_id else None

        return self._datafile


    def set_task_id(self, task_id: str | None):
        """Set the resolved task id and invalidate any cached DataFile."""
        self.task_id = task_id
        self._datafile = _UNSET


    def set_datafile(self, datafile: DataFile):
        """Cache an already-loaded DataFile (skips the lazy fetch)"""
        self._datafile = datafile


    ### lazy ClickUp DataCard / Client
    #   `datacard_id` is set by the linking step; both of these stay None until
    #   it is, so a file with no DataCard never triggers a fetch.

    @property
    def datacard(self) -> DataCard | None:
        """The DataCard this DataFile is linked to (``None`` if unlinked)."""
        if self._datacard is _UNSET:
            self._datacard = (
                self.services.clickup.get_task(self.datacard_id) if self.datacard_id else None
            )

        return self._datacard


    @property
    def client(self) -> Client | None:
        """The client behind the DataCard (``None`` if either is missing)."""
        if self._client is _UNSET:
            datacard = self.datacard
            client_ids = (getattr(datacard, "client_data", None) or []) if datacard else []
            self._client = self.services.clickup.get_task(client_ids[0]) if client_ids else None

        return self._client


    def set_datacard_id(self, datacard_id: str | None):
        """Set the linked DataCard id and invalidate anything derived from it."""
        self.datacard_id = datacard_id
        self._datacard = _UNSET
        self._client = _UNSET


    def set_datacard(self, datacard: DataCard):
        """Cache an already-loaded DataCard (skips the lazy fetch)."""
        self._datacard = datacard


    def set_client(self, client: Client):
        """Cache an already-loaded Client (skips the lazy fetch)."""
        self._client = client


    ### best-effort failure tracking
    
    def record_failure(self, step: str, error: object):
        self._failures.append(f"{step}: {error}")


    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(self._failures)


    @contextmanager
    def best_effort(self, step: str) -> Iterator[None]:
        """Run a best-effort step. Log and return its failure but never raise.
        
        Usage::
            with ctx.best_effort("link-datacard"):
                link(...)                
        """

        try:
            yield

        except Exception as e:
            log.warning(f"best-effort step {step} failed for {self.target_path}: {e}")
            self.record_failure(step, e)


    ### result helpers

    def ack(self, reason: str) -> Result:
        return Result.ack(reason, self.failures)


    def nack(self, reason: str) -> Result:
        return Result.nack(reason) 