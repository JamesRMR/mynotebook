import logging
import signal
import threading

from typing import Callable

from google.cloud.pubsub_v1.subscriber.message import Message

from .client import PubSubClient

from .services import Services, default_services
from .alerts import Alerter, default_alerter
from .handlers import Handlers, default_handlers
from .pipeline import run_pipeline
from .results import Disposition


log = logging.getLogger("datainbox.pipeline")

DEFAULT_MAX_MESSAGES = 10


def build_callback(*, handlers, alerter, services) -> Callable[[Message], None]:
    """Build the pub/sub callback that runs the pipeline and acks/nacks."""

    def callback(message: Message):
        try:
            result = run_pipeline(message.data, handlers=handlers, alerter=alerter, services=services)

        except Exception:
            log.exception(f"pipeline raised for message {message.message_id}, nacking")
            message.nack()
            return

        for failure in result.best_effort_failures:
            log.warning(f"best-effort step failed (message {message.message_id}): {failure}")

        if result.disposition is Disposition.ACK:
            log.info(f"ack {message.message_id}: {result.reason}")
            message.ack()

        else:
            log.warning(f"nack {message.message_id}: {result.reason}")
            message.nack()

    return callback



def run_consumer(
    subscription: str,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    handlers: Handlers | None = None,
    alerter: Alerter | None = None,
    services: Services | None = None,
    client: PubSubClient | None = None,
):
    """Start the streaming pull and block until SIGTERM/SIGINT, then drain."""

    handlers = handlers or default_handlers()
    alerter = alerter or default_alerter()
    services = services or default_services()
    client = client or PubSubClient()

    callback = build_callback(handlers=handlers, alerter=alerter, services=services)
    future = client.subscribe(subscription, callback, max_messages=max_messages)

    log.info(f"datainbox consumer listening on {subscription} (max_messages={max_messages})")

    stop = threading.Event()

    def _shutdown(signum, _frame):
        log.info(f"received signal {signum}, shutting down")
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        stop.wait()

    finally:
        future.cancel()
        try:
            future.result(timeout=30)
        except Exception:
            pass

        log.info("datainbox consumer stopped")