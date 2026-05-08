import logging
import json
import datetime
import os, logging
from logging.handlers import RotatingFileHandler

class MyJSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        optional_fields = ["order_id", 
                           "amount_minor", 
                           "currency", 
                           "status", 
                           "customer_email", 
                           "created_at",
                           "correlation_id"]
        for field in optional_fields:
            if hasattr(record, field):
                log_record[field] = getattr(record, field)

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record)
    
logger = logging.getLogger("webhook-sink")
logger.setLevel(logging.INFO)

log_dir = "./logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

file_handler = RotatingFileHandler(
    f"{log_dir}/webhook-sink.log", 
    maxBytes=10485760, 
    backupCount=5
)
file_handler.setFormatter(MyJSONFormatter())
logger.addHandler(file_handler)