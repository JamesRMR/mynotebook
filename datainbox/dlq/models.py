from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base

Base = declarative_base()



class MessageAttempt(Base):
    """One row per delivery of a Files.com notification to the datainbox push endpoint.

    Written by the endpoint after `run_pipeline` returns (or raises), so a message that
    dead-letters leaves five rows explaining why. A retry republished from Overwatch is
    a new message with `retry_of` pointing back at the original.
    """

    __tablename__ = "message_attempts"

    id = Column(Integer, primary_key=True)

    # pub/sub identity
    message_id = Column(String(30), nullable=False)
    subscription = Column(String(100))
    attempt = Column(Integer)                                   # deliveryAttempt; None when the subscription has no dead-letter policy
    publish_time = Column(DateTime(timezone=True))

    # outcome
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    duration_ms = Column(Integer)
    disposition = Column(String(10), nullable=False)            # ack | nack | raise
    reason = Column(Text)
    best_effort_failures = Column(JSONB)                        # list[str], steps that failed but did not block the ack
    task_id = Column(String(30))                                # ClickUp DataFile the attempt created or patched, if any

    # notification snapshot, so history survives the DLQ message being acked or expiring
    action = Column(String(30))
    type = Column(String(30))
    path = Column(String(550))
    body = Column(JSONB)
    attributes = Column(JSONB)

    # retry provenance (set from message attributes when republished by Overwatch)
    retry_of = Column(String(30))
    retry_count = Column(Integer)
    retried_by = Column(String(255))

    # runtime
    profile = Column(String(10))                                # prod | test
    revision = Column(String(100))                              # Cloud Run K_REVISION
    trace_id = Column(String(32))                               # X-Cloud-Trace-Context trace id; filter Cloud Logging with trace="projects/<project>/traces/<trace_id>"

    __table_args__ = (
        CheckConstraint("disposition IN ('ack', 'nack', 'raise')", name="ck_message_attempts_disposition"),
        Index("ix_message_attempts_message_id", "message_id"),
        Index("ix_message_attempts_retry_of", "retry_of"),
        Index("ix_message_attempts_path", "path"),
        Index("ix_message_attempts_received_at", "received_at"),
    )
