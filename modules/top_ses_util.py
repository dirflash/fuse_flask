import logging
from logging.handlers import RotatingFileHandler

import numpy as np

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


def top_percentile(se_assignment_count):
    # Get the 80th percentile of the se_assignment_count
    unformatted_percentile = np.percentile(list(se_assignment_count.values()), 80)
    percentile = round(unformatted_percentile)
    logger.info(f"80th percentile: {percentile}")
    return percentile


def top_ses(se_assignment_count, percentile):
    # Get the top 20% of SEs
    top_ses_set = set()
    for x in se_assignment_count:
        if se_assignment_count[x] > percentile:
            top_ses_set.add(x)
    # top_ses_set = {x for x in se_assignment_count if se_assignment_count[x] > percentile}
    logger.info(f"Top SES: {top_ses_set}")
    return top_ses_set
