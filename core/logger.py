"""Shared console and daily file logging configuration."""

import logging
import os
from datetime import datetime
from pathlib import Path


_LOG_FORMAT = "%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(name: str) -> logging.Logger:
    """Return an INFO logger with console and date-based file handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        project_root = Path(__file__).resolve().parents[1]
        log_directory = project_root / "logs"
        os.makedirs(log_directory, exist_ok=True)
        log_path = log_directory / f"{datetime.now():%Y-%m-%d}.log"

        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger


__all__ = ["setup_logger"]
