"""Logging configuration utility."""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str = 'mcp_file_handler',
    level: str = 'INFO',
    log_file: Optional[str] = None,
    format_string: Optional[str] = None
) -> logging.Logger:
    """Setup and configure logger.

    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        format_string: Custom format string

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Clear any existing handlers
    logger.handlers.clear()

    # Set level
    logger.setLevel(getattr(logging, level.upper()))

    # Default format
    if not format_string:
        format_string = '[%(asctime)s] %(levelname)-8s %(name)s - %(message)s'

    formatter = logging.Formatter(format_string)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get logger instance.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return logging.getLogger(name)