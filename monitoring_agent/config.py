import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_user: str = os.getenv("DB_USER", "postgres")
    db_pass: str = os.getenv("DB_PASS", "")
    db_name: str = os.getenv("DB_NAME", "emaildb")
    api_gateway_url: str = os.getenv("API_GATEWAY_URL", "http://localhost:8000")
    channel: str = "new_email"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

settings = Settings()