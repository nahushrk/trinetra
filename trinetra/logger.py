"""
Custom logging configuration for Trinetra application
Provides a centralized get_logger function with consistent formatting
"""

import logging
import os
import sys
from pathlib import Path

# Global flag to track if basic config has been set up
_logging_configured = False


def _configure_logging():
    """Configure basic logging settings once"""
    global _logging_configured
    if _logging_configured:
        return

    # Get configuration from environment variables
    log_level = os.getenv("TRINETRA_LOG_LEVEL", "INFO")
    log_file = os.getenv("TRINETRA_LOG_FILE", "trinetra.log")

    # Convert string to logging level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Setup handlers
    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        # Ensure log directory exists
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    # Configure root logger
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )

    # Set specific levels for noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.INFO)

    _logging_configured = True


def get_logger(name):
    """
    Get a properly configured logger instance for the Trinetra application.

    Args:
        name: Logger name (usually __name__ from the calling module)

    Returns:
        Configured logger instance with consistent formatting
    """
    # Ensure logging is configured
    _configure_logging()

    return logging.getLogger(name)
