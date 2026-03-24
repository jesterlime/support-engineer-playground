import logging
import json
import datetime

class MyJSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        optional_fields = ["method", 
                           "path", 
                           "status_code", 
                           "duration_s", 
                           "client_ip", 
                           "correlation_id",
                           "event",
                           "error_detail",
                           "order_id",
                           "payment_id"]
        for field in optional_fields:
            if hasattr(record, field):
                log_record[field] = getattr(record, field)

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record)