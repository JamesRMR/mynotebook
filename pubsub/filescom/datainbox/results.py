from enum import Enum
from dataclasses import dataclass

"""
    REQUIRED failure  -> nack  (redeliver, eventually dead-letter)
    BEST-EFFORT fail  -> log + ack   (recorded in ``best_effort_failures``)
    no-op / handled   -> ack
    unknown-harmless  -> alert + ack
"""


class Disposition(Enum):
    """What the callback should do with the message once the pipeline returns."""

    ACK = "ack"
    NACK = "nack"



@dataclass(frozen=True)
class Result:
    """Outcome of running the pipeline for one message."""

    disposition: Disposition
    reason: str
    best_effort_failures: tuple[str, ...] = ()


    @classmethod
    def ack(cls, reason: str, best_effort_failures: tuple[str, ...] = ()) -> "Result":
        return cls(Disposition.ACK, reason, tuple(best_effort_failures))


    @classmethod
    def nack(cls, reason: str) -> "Result":
        return cls(Disposition.NACK, reason)


    @property
    def acked(self) -> bool:
        return self.disposition is Disposition.ACK

