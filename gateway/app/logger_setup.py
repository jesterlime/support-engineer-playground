import os, logging
from logging.handlers import RotatingFileHandler
from log import MyJSONFormatter

logger = logging.getLogger("gateway")
logger.setLevel(logging.INFO)

# Console log handler
# console_handler = logging.StreamHandler(sys.stdout)
# console_handler.setFormatter(MyJSONFormatter())
# logger.addHandler(console_handler)

# File log handler
log_dir = "./logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

file_handler = RotatingFileHandler(
    f"{log_dir}/gateway.log", 
    maxBytes=10485760, 
    backupCount=5
)
file_handler.setFormatter(MyJSONFormatter())
logger.addHandler(file_handler)