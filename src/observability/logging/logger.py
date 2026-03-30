import logging
import sys

from src.config import get_settings

settings = get_settings()

def setup_logging() -> None:
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    fmt = (
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        if settings.ENVIRONMENT != "production"
        else (
            '{"time":"%(asctime)s","level":"%(levelname)s",'
            '"logger":"%(name)s","message":"%(message)s"}'
        )
    )

    logging.basicConfig(
        level=log_level,
        format=fmt,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialised | level=%s env=%s",
        logging.getLevelName(log_level),
        settings.ENVIRONMENT,
    )
