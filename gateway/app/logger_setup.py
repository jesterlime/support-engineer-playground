import logging
import json
import datetime
import os, logging
from logging.handlers import RotatingFileHandler
import sys

class MyJSONFormatter(logging.Formatter):
    # standard LogRecord attributes to ignore
    RESERVED_ATTRS = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName"
    }

    def format(self, record):
        log_record = {
            "timestamp": datetime.datetime.fromtimestamp(
                record.created
            ).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "function": record.funcName,
        }

        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS:
                log_record[key] = value

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record)


logger = logging.getLogger("app_logger")
logger.setLevel(logging.INFO)

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.INFO)

stdout_handler.setFormatter(MyJSONFormatter())

logger.addHandler(stdout_handler)