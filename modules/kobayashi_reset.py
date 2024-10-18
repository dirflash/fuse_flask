import logging
import sys
from logging.handlers import RotatingFileHandler

from modules import fuse_host, top_ses_util
from modules.se_dict_util import se_count_dict

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
    "./logs/kobayashi_reset.log", maxBytes=10 * 1024 * 1024, backupCount=5
)  # 10 MB
file_handler.setFormatter(console_formatter)
file_handler.setLevel(logging.INFO)

# Logging to Flask console
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(console_handler)
logger.addHandler(file_handler)  # Add file handler to the logger
logger.propagate = False


def kobayashi(kobayashi_counter, kobayashi_se_set, kobayashi_full_SEs):
    # Reset and start over
    if kobayashi_counter == 5:
        logger.error("Kobayashi Maru scenario encountered 5 times. Exiting.")
        sys.exit(1)
    kobayashi_counter += 1
    logger.warning(
        f"Kobayashi Maru scenario number {kobayashi_counter}. Reset and start over."
    )
    SEs = kobayashi_se_set.copy()
    full_SEs = kobayashi_full_SEs.copy()
    # Convert full_SEs to SEs
    # SEs, full_SEs = csv_process.csv_process()
    # Add FUSE host if odd number of SEs
    SEs = fuse_host.fuse_host(SEs)
    # Create se_dict
    # se_dict = create_se_dict()
    # Create se_assignment_count
    se_assignment_count = se_count_dict(SEs)
    # Calculate the 80th percentile
    percentile = top_ses_util.top_percentile(se_assignment_count)
    # Create top_ses list
    top_ses = top_ses_util.top_ses(se_assignment_count, percentile)
    logger.warning(f"Reset number {kobayashi_counter} complete.\n")
    return SEs, full_SEs, se_assignment_count, percentile, top_ses  # , se_dict
