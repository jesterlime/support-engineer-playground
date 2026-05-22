import os

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME", "payments")
DB_USER = os.getenv("DB_USER", "processor_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "processor_pass")

BANK_HOST = os.getenv("BANK_HOST", "localhost")
BANK_PORT = int(os.getenv("BANK_PORT", 8001))
BANK_AUTH = os.getenv("BANK_AUTH", "PROCESSOR-BANK-SECRET")

MQ_HOST = os.getenv("MQ_HOST", "message-broker")
MQ_PORT = os.getenv("MQ_PORT", 5672)
MQ_USER = os.getenv("MQ_USER", "pay_user")
MQ_PASSWORD = os.getenv("MQ_PASSWORD", "pay_password")
