import logging
from typing import Protocol


log = logging.getLogger("datainbox.pipeline")



class Alerter(Protocol):
    """Anything that can raise a human-visible alert."""

    def alert(self, message: str, at_channel: bool = False):
        ...


class LoggingAlerter:
    """Fallback alerter that only logs"""

    def alert(self, message: str, at_channel: bool = False):
        log.warning(f"ALERT{' @channel' if at_channel else ''}: {message}")



class _ChatterboxAlerter:
    def __init__(self, chatterbox):
        self._cb = chatterbox


    def alert(self, message: str, at_channel: bool = False):
        text = f"@channel\n{message}" if at_channel else message
        self._cb(text, level="ERROR", slack=True)



def default_alerter() -> Alerter:
    try:
        from rmrhermes.chatterbox import Chatterbox

    except ImportError:
        log.warning("rmrhermes not installed; alerts will only be logged")
        return LoggingAlerter()
    
    return _ChatterboxAlerter(Chatterbox("DATAINBOX"))