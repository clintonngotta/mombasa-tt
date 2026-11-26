"""The shared cache's wire format and what happens when it can't be reached.

Values go to Redis as JSON, never pickle, so whoever could write to Redis still couldn't make an API
process run code by reading it back. Whole numbers go as plain numbers so Redis can add to them in place
(the rate-limit counts in core/throttling.py)."""

import json
import logging
import time

logger = logging.getLogger(__name__)

# One warning a minute per process while Redis is down, not one per request.
WARN_EVERY = 60.0
_last_warned = {"at": 0.0}


class JsonSerializer:
    def dumps(self, value):
        if type(value) is int:
            return value
        return json.dumps(value, separators=(",", ":")).encode()

    def loads(self, data):
        try:
            return int(data)
        except ValueError:
            return json.loads(data)


def warn_unavailable(what: str) -> None:
    now = time.monotonic()
    if now - _last_warned["at"] >= WARN_EVERY:
        _last_warned["at"] = now
        logger.warning("shared cache unavailable", extra={"what": what})
