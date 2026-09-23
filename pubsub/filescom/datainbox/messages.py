import json
from typing import Any
from pydantic import BaseModel, ValidationError



class MessageParseError(ValueError):
    """The Pub/Sub body could not be parsed into an :class:`InboundMessage`."""



class InboundMessage(BaseModel):
    """A single Files.com action notifiction."""

    action: str
    type: str
    path: str
    destination: str | None = None
    username: str | None = None
    interface: str | None = None
    ip: str | None = None
    at: str | None = None
    size: int | None = None
    source: str | None = None

    @property
    def target_path(self) -> str:
        """Path to act on, the destination for moves, otherwise the source path."""
        return self.destination or self.path



def parse_message(data: bytes | str | dict [str, Any]) -> InboundMessage:
    """Decode ``message.data`` into an :class:`InboundMessage`.
    
    Accepts raw bytes (as delivered by Pub/Sub), a JSON string, or an already decoded dict.

    Raises
        :class:`MessageParseError` for anything that is not a well formed action notificiton.
    """

    if isinstance(data, (bytes, bytearray)):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise MessageParseError(f"Message body is not valid UTF-8: {e}") from e

    if isinstance(data, str):
        try:
            data = json.loads(data)    
        except json.JSONDecodeError as e:
            raise MessageParseError(f"Message body is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise MessageParseError(f"message body must be a JSON object, got {type(data).__name__}")

    payload = dict(data)

    default = payload.pop("default", None)
    if isinstance(default, dict) and payload.get("source") is None:
        payload["source"] = default.get("source")

    try:
        return InboundMessage.model_validate(payload)

    except ValidationError as e:
        raise MessageParseError(f"missing/invalid fields: {e}") from e