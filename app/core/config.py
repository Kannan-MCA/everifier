import logging.config
from dotenv import load_dotenv
import os

load_dotenv()

class Settings:
    APP_PORT = int(os.getenv("APP_PORT", 8000))

    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default"
            }
        },
        "root": {
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "handlers": ["console"]
        }
    }

settings = Settings()
logging.config.dictConfig(settings.LOGGING_CONFIG)
logger = logging.getLogger(__name__)