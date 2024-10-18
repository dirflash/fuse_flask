import logging
from logging.handlers import RotatingFileHandler

import modules.preferences.preferences as p

# pylint: disable=logging-fstring-interpolation, undefined-variable

console_formatter = logging.Formatter(
    "%(asctime)s - %(filename)s:%(lineno)d - %(name)s - %(levelname)s - %(message)s"
)

# Create a stream handler with the formatter
console_handler = logging.StreamHandler()
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.INFO)

# Create a file handler for file logging
file_handler = RotatingFileHandler(
    "./logs/se_select.log", maxBytes=10 * 1024 * 1024, backupCount=5
)  # 10 MB
file_handler.setFormatter(console_formatter)
file_handler.setLevel(logging.INFO)

# Logging to Flask console
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(console_handler)
logger.addHandler(file_handler)  # Add file handler to the logger
logger.propagate = False


def fuse_host(SEs: set):
    # Add FUSE host if odd number of SEs
    if len(SEs) % 2 != 0:
        logging.info("Odd number of SEs. Adding FUSE host to SEs list.")
        SEs.add(p.host)
    else:
        logging.info("Even number of SEs.")
    return SEs
