import os

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME", "payments")
DB_USER = os.getenv("DB_USER", "gateway_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "gateway_pass")
