from enum import Enum, auto

from .messages import InboundMessage


TEMP_MARKER = "~$"

_RECONCILE_ACTIONS = frozenset({"create", "move", "update"})
_DIR_NOOP_ACTIONS = frozenset({"create", "update"})


class Route(Enum):
    RECONCILE = auto()
    DESTROY = auto()
    DIR_RECONCILE = auto()
    DIR_DESTROY = auto()
    NOOP = auto()
    UNKNOWN = auto()



def is_temp(msg: InboundMessage):
    """True if either the source or destination path names is a temp file"""
    return TEMP_MARKER in (msg.path or "") or TEMP_MARKER in (msg.destination or "")



def route(msg: InboundMessage) -> Route:
    """Map a message's ``type`` and ``action`` to a :class:`Route`."""

    action = (msg.action or "").strip().lower()
    rtype = (msg.type or "").strip().lower()
    if action == "read":
        return Route.NOOP

    if rtype == "file":
        if action in _RECONCILE_ACTIONS:
            return Route.RECONCILE
        
        if action == "destroy":
            return Route.DESTROY
        
        return Route.UNKNOWN

    if rtype == "dir":
        if action == "move":
            return Route.DIR_RECONCILE
        
        if action == "destroy":
            return Route.DIR_DESTROY
        
        if action in _DIR_NOOP_ACTIONS:
            return Route.NOOP
        
        return Route.UNKNOWN

    return Route.UNKNOWN
