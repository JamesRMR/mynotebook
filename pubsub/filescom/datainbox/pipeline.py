import logging


from .alerts import Alerter
from .context import Context
from .services import Services
from .handlers import Handlers
from .messages import MessageParseError, parse_message
from .results import Result
from .routing import Route, is_temp, route



log = logging.getLogger("datainbox.pipeline")

_ROUTE_TO_HANDLER = {
    Route.RECONCILE: "reconcile",
    Route.DESTROY: "destroy",
    Route.DIR_RECONCILE: "dir_reconcile",
    Route.DIR_DESTROY: "dir_destroy",
}



def run_pipeline(data, handlers: Handlers, alerter: Alerter, services: Services) -> Result:
    """Run the full dispatch for one raw message body and return a result"""

    # 1. Parse
    #      - A malformed body will never become well-formed on redelivery,
    #        so alert and ack rather than nack-loop it toward the dead-letter topic
    try:
        msg = parse_message(data)

    except MessageParseError as e:
        alerter.alert(f"Discarding unparseable Files.com message: {e}", at_channel=True)
        return Result.ack(f"malformed: {e}")

    # 2. Temp Files
    #       - Don't do anything with temp files
    if is_temp(msg):
        log.info(f"ignoring temp file: {msg.target_path}")
        return Result.ack("temp-file")

    # 3. Route on type and action
    decision = route(msg)

    if decision is Route.NOOP:
        log.info(f"no-op: {msg.type}/{msg.action} {msg.target_path}")
        return Result.ack(f"noop: {msg.type}/{msg.action}")

    if decision is Route.UNKNOWN:
        alerter.alert(f"Unhandled Files.com event `{msg.type}/{msg.action}` for `{msg.target_path}`", at_channel=True)
        return Result.ack(f"unknown: {msg.type}/{msg.action}")

    # 4. Dispatch
    #       - dispatch to the matching handler (may raise -> callback nacks).
    ctx = Context(msg, services=services, alerter=alerter)
    handler = getattr(handlers, _ROUTE_TO_HANDLER[decision])
    return handler(ctx)