# Utilities and logging configurations for doctor-chemist mapping tool
import logging
import os
import sys

def setup_logger(name: str = "doctor_chemist_matcher") -> logging.Logger:
    """
    Sets up a consolidated logger that outputs to the console with human-readable formatting.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
    return logger
