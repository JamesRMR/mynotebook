"""DataInbox Pub/Sub handler.

Consumes Files.com action notifications off a Pub/Sub subscription and
reconciles the corresponding ClickUp DataFile. See ``DESIGN.md`` one directory up.

Typical use::

    from datainbox import run_consumer

    run_consumer("filescom-events-sub", max_messages=10)

Everything the consumer depends on is injectable, so a test can swap the
services, handlers, and alerter for fakes::

    from datainbox import Services, run_pipeline

    run_pipeline(body, handlers=fake_handlers, alerter=fake_alerter, services=fake_services)
"""

from .alerts import Alerter, LoggingAlerter, default_alerter
from .categorize import DEFAULT_RULES, CategoryRule, categorize
from .client import PubSubClient
from .consumer import DEFAULT_MAX_MESSAGES, build_callback, run_consumer
from .context import Context
from .handlers import Handler, Handlers, default_handlers
from .identity import Identity, IdentityResult, resolve_datafile
from .linking import LinkError, link_datacard, rmrcode_from_path
from .messages import InboundMessage, MessageParseError, parse_message
from .pipeline import run_pipeline
from .results import Disposition, Result
from .routing import Route, is_temp, route
from .services import (
    ClickUpService,
    IdentityService,
    DataFileCreateError,
    FieldResolutionError,
    FilescomService,
    MetadataWriteError,
    Services,
    default_services,
)

__all__ = [
    # runtime shell
    "run_consumer",
    "build_callback",
    "PubSubClient",
    "DEFAULT_MAX_MESSAGES",
    # pipeline
    "run_pipeline",
    "Context",
    "Result",
    "Disposition",
    # dispatch
    "Route",
    "route",
    "is_temp",
    "Handler",
    "Handlers",
    "default_handlers",
    # message parsing
    "InboundMessage",
    "MessageParseError",
    "parse_message",
    # identity resolution
    "Identity",
    "IdentityResult",
    "resolve_datafile",
    # categorization
    "categorize",
    "CategoryRule",
    "DEFAULT_RULES",
    # linking (best-effort)
    "link_datacard",
    "rmrcode_from_path",
    "LinkError",
    # injectable dependencies
    "Services",
    "default_services",
    "ClickUpService",
    "FilescomService",
    "IdentityService",
    "MetadataWriteError",
    "FieldResolutionError",
    "DataFileCreateError",
    "Alerter",
    "LoggingAlerter",
    "default_alerter",
]
