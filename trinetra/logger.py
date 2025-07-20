"""
Custom logging configuration for Trinetra application
Provides a centralized get_logger function with consistent formatting
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# Global flag to track if basic config has been set up
_logging_configured = False
_config = None


def configure_logging(config: Optional[Dict[str, Any]] = None):
    """Configure basic logging settings once using config file"""
    global _logging_configured, _config

    if _logging_configured:
        return

    # Store config for later use
    _config = config or {}

    # Get configuration from config file
    log_level = _config.get("log_level") or os.getenv("TRINETRA_LOG_LEVEL", "INFO")
    log_file = _config.get("log_file") or os.getenv("TRINETRA_LOG_FILE", "trinetra.log")

    # Require log_level to be specified in config
    if not log_level:
        raise ValueError("log_level must be specified in config file")

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
    # If logging is not configured yet, return a basic logger
    if not _logging_configured:
        # Create a basic logger that will be configured later
        logger = logging.getLogger(name)
        # Set a reasonable default level
        logger.setLevel(logging.INFO)
        # Add a handler if none exists
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    return logging.getLogger(name)
