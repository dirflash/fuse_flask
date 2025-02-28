import logging
from logging.handlers import RotatingFileHandler
from threading import current_thread
from time import perf_counter, sleep
from typing import Any, Dict, List

from pymongo.errors import ConnectionFailure

import modules.preferences.preferences as p
from modules import se_info_util

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

se_dict: Dict[int, list] = {}


def make_se_dict(x: str, se_dict: dict, user_db: str, mode: str) -> Any:
    # Look up the SE in the SE info collection and return the SE info.
    # get_se_info does the lookup and builds an entry in the se_dict
    se_info_result = se_info_util.get_se_info(x, se_dict, user_db, mode)
    if se_info_result is not None:
        return se_info_result
    else:
        return None


def se_count_dict(SEs: List[str]) -> Dict[str, int]:
    # Create a dict of se:match_count
    se_assignment_count: Dict[str, int] = {}
    start_se_assignment_dict = perf_counter()
    for x in SEs:
        if current_thread().name == "MainThread":
            for _ in range(5):
                try:
                    y = p.cwa_matches.find_one({"SE": x})
                    break
                except ConnectionFailure as e:
                    logger.warning(
                        f" *** Connect error getting SE {x} from cwa_matches collection."
                    )
                    logger.warning(
                        f" *** Sleeping for {pow(2, _)} seconds and trying again."
                    )
                    sleep(pow(2, _))
                    logger.warning(e)
            logger.error(
                " *** Failed attempt to connect to cwa_matches collection. Mongo is down."
            )
        else:
            y = p.cwa_matches.find_one({"SE": x})
        if y is not None:
            # count the number of assignments for x
            count_assignments = len(y["assignments"])
            # add the se and count to the dict
            se_assignment_count[x] = count_assignments
    end_se_assignment_dict = perf_counter()
    # clear temp variables: x, y, count_assignments
    del count_assignments, x, y
    logger.info(
        f" Time to create se_assignment_count: {end_se_assignment_dict - start_se_assignment_dict:.6f} seconds."
    )
    return se_assignment_count
