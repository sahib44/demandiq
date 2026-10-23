"""Structured, value-minimal logs shared by requests and workers."""

import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record):
        value = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for key in (
            "request_id",
            "job_id",
            "kind",
            "status",
            "duration_seconds",
            "error_code",
            "method",
            "path",
            "status_code",
        ):
            if hasattr(record, key):
                value[key] = getattr(record, key)
        return json.dumps(value, sort_keys=True, allow_nan=False)


def configure_logging():
    logger = logging.getLogger("demandiq")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
