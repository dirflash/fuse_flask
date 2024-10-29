import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from random import choice, randint
from statistics import median_high
from threading import Thread
from time import perf_counter, sleep
from typing import Dict

from pymongo.errors import ConnectionFailure

import modules.preferences.preferences as p
from modules import fuse_host, kobayashi_reset, se_dict_util, se_info_util, top_ses_util

# pylint: disable=logging-fstring-interpolation, undefined-variable, pointless-string-statement

count = 0
kobayashi_counter = 0
vips: set[str] = set()
region_index_cache = {}


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


# Custom class to return a value from a thread
class CustomThread(Thread):
    """
    This module sets up logging and defines a custom thread class for returning values from threads.

    Logging Configuration:
        - Configures logging to both the console and a file.
        - Sets the logging level to INFO.
        - Disables propagation to avoid duplicate logging.

    Classes:
        CustomThread(Thread):
            A custom thread class that allows returning a value from a thread.

            Methods:
                __init__(self, group=None, target=None, name=None, args=(), kwargs=None):
                    Initializes the thread with the given parameters.

                run(self):
                    Executes the target function with the provided arguments and stores the result.

                join(self, *args, **kwargs):
                    Joins the thread and returns the result of the target function.

    Functions:
        se_select(fuse_date, Mongo_Connection_URI, se_set):
            Logs the start of the SE select function and the number of SEs being tracked.
            Creates a dictionary of all SEs and their regions using threading.

            Args:
                fuse_date (str): The date for the fuse operation.
                Mongo_Connection_URI (str): The URI for the MongoDB connection.
                se_set (set): A set of SEs to be tracked.
    """

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None):
        super().__init__(
            group=group, target=target, name=name, args=args, kwargs=kwargs
        )
        self.result = None

    def run(self):
        if self._target:
            self.result = self._target(*self._args, **self._kwargs)

    def join(self, *args, **kwargs):
        super().join(*args, **kwargs)
        return self.result


def create_se_dict(SEs, full_SEs) -> Dict[int, list]:
    # Create a dict of all SEs and their regions
    se_dict: Dict[int, list] = {}
    start_se_dict = perf_counter()
    for x in SEs:
        se_info_result = se_dict_util.make_se_dict(x, se_dict)
        if se_info_result is None:
            logger.warning(f"Unknown SE: {x}")
            se_info_result = se_info_util.add_unknown_se(x, full_SEs, se_dict)
    # clear the temp lists, dicts, variables
    del_vars = ["x", "se_info_result"]
    for var in del_vars:
        if var in locals():
            del var
    end_se_dict = perf_counter()
    logger.info(f" Time to create se_dict: {end_se_dict - start_se_dict:.6f} seconds.")
    return se_dict


def make_sem_set(ses):
    # Create a list of SEs with SEM
    sem_set = set()
    for _ in range(5):
        try:
            sem = p.se_info.find({"sem": {"$eq": True}}, {"se": 1, "_id": 0})
            break
        except ConnectionFailure as e:
            logger.warning(" *** Connect error getting SEMs from se_info collection.")
            logger.warning(f" *** Sleeping for {pow(2, _)} seconds and trying again.")
            sleep(pow(2, _))
            logger.warning(e)
    for x in sem:
        if x["se"] in ses:
            sem_set.add(x["se"])
    if len(sem_set) > 0:
        logger.info(f"{len(sem_set)} SEM's to match: {sem_set}")
    else:
        logger.info(" No SEM's to match.")
    del sem, x
    return sem_set


'''def calculate_count(se_dict) -> int:
    """Calculate the count of SEs remaining."""
    # Only recalculate the count using this method
    counting = 0
    for _ in se_dict.values():
        counting += len(_[1])
    return counting'''

"""
This code ⬆️ replaced by this code ⬇️
"""


def calculate_count(se_dict) -> int:
    """Calculate the count of SEs remaining."""
    logger.info("Calculating count of SEs remaining.")
    counting = 0
    if se_dict is None or len(se_dict) == 0:
        logger.warning("se_dict is empty or None.")
        logger.info(f"Contents of se_dict: {se_dict}")
    else:
        for value in se_dict.values():
            if (
                isinstance(value, (list, tuple))
                and len(value) > 1
                and isinstance(value[1], list)
            ):
                counting += len(value[1])
            else:
                raise ValueError(
                    "Each value in se_dict must be a list or tuple with a list as the second element."
                )
    return counting


def sorted_running_count_func(se_dict) -> Dict[int, int]:
    # Create a dict of region:se_count -> sorted_running_count
    running_count: Dict[int, int] = {}
    for r in se_dict:
        if len(se_dict[r][1]) > 0:
            try:
                for x in se_dict[r][1]:
                    continue
                running_count[r] = len(se_dict[r][1])
            except KeyError:
                logger.error("KeyError")
                logger.error(f"Region: {r}")
                logger.error(f"SEs: {se_dict[r][1]}")
                logger.error(f"se_dict: {se_dict}")
                logger.error(f"SE: {x}")
                sys.exit(1)  # TODO: Handle this error more gracefully
    # sort running_count by key
    sorted_running_count: Dict[int, int] = dict(
        sorted(running_count.items(), key=lambda x: x[0])
    )
    # clear temp variables
    del r, x
    # clear running_count
    running_count = {}
    return sorted_running_count


def region_plus_median_func(sorted_running_count, se_median) -> list[int]:
    """Create a list of SE/Region above the median + 2."""
    median_pad = [
        x for x in sorted_running_count if sorted_running_count[x] > se_median + 2
    ]
    if len(median_pad) > 0:
        logger.info(f"Regions above median + 2: {median_pad}")
    else:
        logger.info(" No regions are above median + 2. Using calculated high_median.")
        median_pad = [
            x for x in sorted_running_count if sorted_running_count[x] >= se_median
        ]

    # Create a list of keys from sorted_running_count and add the median_pad list
    region_plus_median = [key for key in sorted_running_count.keys()] + median_pad
    logger.info(f" Region plus median pad: {region_plus_median}")
    clear_temp_vars = ["key", "x", "median_pad"]
    for var in clear_temp_vars:
        if var in locals():
            del var
    return region_plus_median


def cleanup_se(
    region: int, se: str, se_dict, sem_set, SEs, top_ses, vips, zero_set
) -> None:
    """Remove se1 from se_dict, region_plus_median, and sorted_running_count."""
    # Remove se1 from se_dict
    try:
        se_dict[region][1].remove(se)
    except ValueError:
        logger.error(f"ValueError: {se} not found in se_dict.")
        logger.error(f"Region: {region}")
        logger.error(f"SEs: {se_dict[region][1]}")
        logger.error(f"se_dict: {se_dict}")
        sys.exit(1)  # TODO: Handle this error more gracefully
    # Remove se1 from SEs
    # Verify that se is not in se_dict
    if se in se_dict[region][1]:
        logger.warning(f" {se} still in se_dict.")
    else:
        logger.info(f" {se} removed from se_dict.")

    sem_set.discard(se)
    SEs.discard(se)
    top_ses.discard(se)
    vips.discard(se)
    zero_set.discard(se)

    if len(se_dict[region][1]) == 0:
        print(f" Region {region} has no SEs.")
        se_dict.pop(region)


def lookup_region(se2):
    # lookup region for se2
    for _ in range(5):
        try:
            se2_info = p.se_info.find_one({"se": se2})
            break
        except ConnectionFailure as e:
            logger.warning(
                f" *** Connect error getting SE {se2} from se_info collection."
            )
            logger.warning(f" *** Sleeping for {pow(2, _)} seconds and trying again.")
            sleep(pow(2, _))
            logger.error(e)
    if se2_info:
        for _ in range(5):
            try:
                se2_region_name = se2_info.get("region")
                break
            except ConnectionFailure as e:
                logger.warning(
                    f" *** Connect error getting SE {se2} from se_info collection."
                )
                logger.warning(
                    f" *** Sleeping for {pow(2, _)} seconds and trying again."
                )
                sleep(pow(2, _))
                logger.error(e)
        if se2_region_name:
            # Use the cached value if available
            if se2_region_name not in region_index_cache:
                # Lookup and cache the region index if not already done
                for _ in range(5):
                    try:
                        se2_region_doc = p.cwa_regions.find_one(
                            {"Region": se2_region_name}
                        )
                        break
                    except ConnectionFailure as e:
                        logger.error(
                            f" *** Connect error getting SE {se2} from cwa_regions collection."
                        )
                        logger.error(
                            f" *** Sleeping for {pow(2, _)} seconds and trying again."
                        )
                        sleep(pow(2, _))
                        logger.warning(e)
                if se2_region_doc:
                    region_index_cache[se2_region_name] = se2_region_doc.get("Index")
        # Get the region index from the cache
        se2_region = region_index_cache.get(se2_region_name)
        return se2_region, se2_region_name


def waterline_target():
    """Determine the target date for a non unique match that's older than 2 years."""
    current_date = datetime.today().strftime("%m/%d/%Y")
    # get the last 4 digits of current_date
    year = int(current_date[-4:]) - 1
    # replace the last 4 digits of current_date with year
    target_date = current_date.replace(current_date[-4:], str(year))
    logger.info(f" Target date: {target_date}")
    # Convert target_date to datetime object
    target_date = datetime.strptime(target_date, "%m/%d/%Y").date()
    return target_date


def last_match_date(se1, se2, target_date):
    # Get the last match date for se1 and se2
    for _ in range(5):
        try:
            match_check = p.cwa_matches.find_one({"SE": se1})["assignments"]
            break
        except ConnectionFailure as e:
            logger.error(
                " *** Connect error getting last match date from cwa_matches collection."
            )
            logger.info(f" *** Sleeping for {pow(2, _)} seconds and trying again.")
            sleep(pow(2, _))
            logger.error(e)
    for x, y in match_check.items():
        if y == se2:
            match_date = x
            logger.info(f" {se1} was matched with {se2} on {match_date}.")
            break
    # Convert match_date to datetime object
    match_date = datetime.strptime(match_date, "%m/%d/%Y").date()
    # If the match_date older than target_date, allow the match
    if match_date < target_date:
        return True
    else:
        logger.warning(f" {se1} and {se2} cannot be matched.")
        return False


def update_cwa_matches(se, other_value, assignment_date, max_retries=5):
    attempts = 0
    while attempts < max_retries:
        try:
            p.cwa_matches.update_one(
                {"SE": se}, {"$set": {assignment_date: other_value}}, upsert=True
            )
            logger.info(f" Added {se} match to database.")
            return True  # Update successful
        except Exception as e:
            attempts += 1
            logger.error(
                f"Error updating {se} to cwa_matches collection on attempt {attempts}."
            )
            logger.error(e)
            if attempts == max_retries:
                # Decide how to handle the error after all retries fail
                logger.error(f"Failed to update {se} after {max_retries} attempts.")
                return False  # Update failed after retries


def write_matches_to_file(matches_filename, se_pair_list):
    """Write matches to file"""
    logger.info(f"Writing matches to {matches_filename}")
    matches_file = open(f".\\match_files\\{matches_filename}", "w", encoding="utf-8")
    matches_file.write("SE1_NAME,SE1_CCO,SE2_CCO,SE2_NAME\n")
    # Pre-fetch all SE info in a single query and create a dictionary for quick lookup.
    se_ids = {se for pair in se_pair_list for se in pair}
    for _ in range(5):
        try:
            se_info_dict = {
                doc["se"]: doc["se_name"]
                for doc in p.se_info.find({"se": {"$in": list(se_ids)}})
            }
            break
        except ConnectionFailure as e:
            logger.warning(
                " *** Connect error getting se_info from se_info collection."
            )
            logger.warning(f" *** Sleeping for {pow(2, _)} seconds and trying again.")
            sleep(pow(2, _))
            logger.error(e)

    # Use a context manager to handle the file writing.
    with open(
        f".\\match_files\\{matches_filename}", "a", encoding="utf-8"
    ) as matches_file:
        for x, y in se_pair_list:
            # Lookup SE names from the pre-fetched dictionary.
            x_name = se_info_dict.get(x, "Unknown")
            y_name = se_info_dict.get(y, "Unknown")
            matches_file.write(f"{x_name},{x},{y},{y_name}\n")
    matches_file.close()
    logger.info(" File written.")


def se_select(fuse_date, Mongo_Connection_URI, se_set, test_mode=False):
    start_time = perf_counter()
    logger.info("SE select function...")
    logger.info(f"Tracking {len(se_set)} SEs.")
    kobayashi_se_set = se_set.copy()
    SEs = se_set
    full_SEs = se_info_util.get_full_se_list(Mongo_Connection_URI, SEs)
    kobayashi_full_SEs = full_SEs.copy()
    se_pair_list = []

    # Add FUSE host if odd number of SEs
    SEs = fuse_host.fuse_host(SEs)

    count = len(SEs)

    logger.info(f"Tracking {count} SEs.")

    # Create a dict of all SEs and their regions using threading
    se_dict_thread = CustomThread(
        target=create_se_dict, args=(SEs, full_SEs), name="se_dict_thread"
    )
    # Create a dict of se:match_count using threading
    se_assignment_count_thread = CustomThread(
        target=se_dict_util.se_count_dict,
        args=(SEs,),
        name="se_assignment_count_thread",
    )

    se_dict_thread.start()
    se_assignment_count_thread.start()

    se_dict = se_dict_thread.join()
    se_assignment_count = se_assignment_count_thread.join()

    # Get the 80th percentile of the se_assignment_count
    unformatted_percentile = top_ses_util.top_percentile(se_assignment_count)
    percentile = round(unformatted_percentile)
    logger.info(f"80th percentile of SE assignments: {percentile}")

    # Get the top 20% of SEs
    top_ses = top_ses_util.top_ses(se_assignment_count, percentile)

    # Create the sem_set
    sem_set = make_sem_set(SEs)

    """ Main Loop Starts Here"""

    while count > 0 and kobayashi_counter < 5:
        logger.info(f"Count: {count}")
        kobayashi = False
        priority_region_select = False
        matchability = True

        count = calculate_count(se_dict)
        logger.info(f"SEs remaining: {count}")
        if count == 0:
            break

        # Using se_dict, create a dict of region:se_count -> sorted_running_count
        sorted_running_count = sorted_running_count_func(se_dict)

        logger.info(f"Number of regions: {len(sorted_running_count)}")
        logger.info(f" Running count of region/SEs: {sorted_running_count}")

        # The priority_region is the first region in sorted_running_count that has the most SEs
        # If there is a tie, the first region with the lowest index in sorted_running_count is selected.
        # On subsequent loops, the other regions will be selected.
        priority_region = max(sorted_running_count, key=sorted_running_count.get)
        logger.info(
            f"Region {str(priority_region)} has the most SEs: {sorted_running_count[priority_region]}"
        )

        # What is the total number of SEs minus highest_region_se_count?
        all_other_regions_se_count = count - sorted_running_count[priority_region]
        logger.info(
            f"Total number of SEs in all other regions: {all_other_regions_se_count}"
        )

        # if number of regions > 2 and priority region selection conditions are met, select SE from priority region
        if (
            len(sorted_running_count) > 2
            and sorted_running_count[priority_region]
            == all_other_regions_se_count  # noqa: W503
        ):
            logger.warning(
                f"Region {priority_region} has the same number of SEs as all other regions combined."
            )
            logger.warning(f"Select next SE from region {priority_region}.")
            priority_region_select = True

        # clean up temporary variables
        del all_other_regions_se_count

        # Create a set of SEs in region 0 representing SE leadership
        zero_set = set()
        if 0 in se_dict:
            zero_set = set(se_dict[0][1])

        # calculate the percentage of SSEMs and SEMs to SEs
        if len(SEs) > 0:
            leader_percent = round((len(zero_set) + len(sem_set)) / len(SEs) * 100, 2)
            logger.info(f" {leader_percent}% of SEs are leaders.")

        if len(sorted_running_count) == 1 and count >= 1:
            logger.warning(f"---> Remaining SEs are in one region: {SEs}")
            logger.warning("  *** Kobayashi Maru. Trigger reset. ***")
            kobayashi = True

        if kobayashi is False:
            # Calculate the SE/Region median and pad the sorted_running_count
            if count > 10:
                se_median = median_high(list(se_assignment_count.values()))
                logger.info(f"SE/Region median: {se_median}")
                region_plus_median = region_plus_median_func(
                    sorted_running_count, se_median
                )
            else:
                se_median = 0
                # Create a list of keys from sorted_running_count
                region_plus_median = list(sorted_running_count.keys())
                logger.info(f"Regions: {region_plus_median}")

            """
            SE1 section steps

            If a VIP is attending, select first and second SE not in region 0.
            """

            logger.info("SE1 selection begins.")

            # Is a VIP attending?
            if 100 in region_plus_median:
                logger.info(f" VIPs in region 100: {len(se_dict[100][1])}")
                # Randomly select VIP in region 100
                se_choice = randint(0, len(se_dict[100][1]) - 1)
                se1 = se_dict[100][1][se_choice]
                logger.info(f" SE1 {se1} selected as VIP from region 100.")
                se1_region = 100

            # Select an SE from top_ses
            elif len(top_ses) > 0 and leader_percent <= 30:
                se1 = choice(list(top_ses))
                # lookup region for se1
                for se_region, se_values in se_dict.items():
                    if se1 in se_values[1]:
                        se1_region = se_region
                        logger.info(
                            f" SE1 {se1} in region {str(se1_region)} {se_values[0]} selected from top_ses."
                        )
                        if len(top_ses) > 0:
                            logger.info(f" Remaining top SEs: {top_ses}")
                        break

            # If leader percentage is greater than 20%, select a leader
            elif leader_percent > 20:
                # Select a random leader from zero_set or sem_set
                leader_set = zero_set.union(sem_set)
                se1 = choice(list(leader_set))
                # lookup region for se1
                for se_region, se_values in se_dict.items():
                    if se1 in se_values[1]:
                        se1_region = se_region
                        logger.info(
                            " ---> High percentage of leaders. Selecting leader."
                        )
                        logger.info(
                            f"        SE1 {se1} selected from region {se1_region}."
                        )
                        break

            # If priority_region_select is True, select SE1 from priority_region
            elif priority_region_select is True:
                se1_region = priority_region
                # Select a random SE from the selected region
                se1 = choice(se_dict[se1_region][1])
                logger.info(" ----> Priority selection:")
                logger.info(f"         SE1 {se1} from region {se1_region}.")
                # Clean up temporary variables
                del priority_region

            else:
                # Select a random SE of those remaining from region_plus_median
                se1_region = choice(region_plus_median)
                logger.info(
                    f"Selected region {se1_region} with {len(se_dict[se1_region][1])} SEs."
                )
                # Select a random SE from the selected region
                se1 = choice(se_dict[se1_region][1])
                logger.info(f"SE1 {se1} selected from region {se1_region}.")

            """ End of SE1 section steps """

            """ Profile SE1 """

            VIP = False
            SSEM = False
            SEM = False
            SE = False

            # If SEM not attending, remove from sem_present_set
            sem_set = sem_set.intersection(SEs)

            # Is se1 a VIP?
            if se1_region == 100:
                VIP = True
                # create a set of SEs in region 100
                # vips = set()
                if 100 in se_dict:
                    vips = set(se_dict[100][1])
                logger.info(f" --> {se1} is a VIP.")

            # Is se1 a senior leader?
            elif se1 in zero_set:
                SSEM = True
                logger.info(f" --> {se1} is a senior leader.")
                logger.info(f" SSEM's in region 0: {zero_set}")

            # Is se1 a SEM?
            elif se1 in sem_set:
                SEM = True
                logger.info(f" --> {se1} is a SEM.")
                logger.info(f" SEM's to match: {sem_set}")

            else:
                SE = True
                logger.info(f" --> {se1} is a regular SE.")

            """ Clean up se_dict and region_plus_median list before selecting SE2 """
            logger.info("Clean up before selecting SE2.")

            # Clean up after selecting se1
            cleanup_se(se1_region, se1, se_dict, sem_set, SEs, top_ses, vips, zero_set)

            # Using se_dict, recreate sorted_running_count -> a dict of region:se_count
            sorted_running_count = {}
            sorted_running_count = sorted_running_count_func(se_dict)
            logger.info(f" Running count of region/SEs: {sorted_running_count}")

            # Calculate the SE/Region median and pad the sorted_running_count
            if count > 10:
                se_median = median_high(list(se_assignment_count.values()))
                logger.info(f"SE/Region median: {se_median}")
                region_plus_median = region_plus_median_func(
                    sorted_running_count, se_median
                )
            else:
                se_median = 0
                region_plus_median = [key for key in sorted_running_count.keys()]
                logger.info(f"Regions: {region_plus_median}")

            """ Begin SE2 section steps """
            logger.info("SE2 selection begins.")

            # Select a random SE from the selected region
            if VIP is True:
                logger.info(" SE2 selection for SE1 VIP.")
                # if se1 is VIP, select an se not in sem_list
                se2 = choice(list(SEs - sem_set - zero_set - vips))
                # lookup region for se2
                se2_region, se2_region_name = lookup_region(se2)
                logger.info(f" SE2 {se2} selected from region {se2_region}.")
                del se2_region_name
                # del vips, valid_ses, zero_set <- TODO: Move this down, after selecting SE2
            elif SSEM is True:
                logger.info(" SE2 selection for SE1 SSEM.")
                # if se1 is SSEM, select an se not in sem_list
                se2 = choice(list(SEs - sem_set - zero_set))
                # lookup region for se2
                se2_region, se2_region_name = lookup_region(se2)
                logger.info(f" SE2 {se2} selected from region {se2_region}.")
            elif SEM is True:
                logger.info(" SE2 selection for SE1 SEM.")
                # if se1 is SEM, select an se not in sem_list
                se2 = choice(list(SEs - sem_set - zero_set))
                # lookup region for se2
                se2_region, se2_region_name = lookup_region(se2)
                logger.info(f" SE2 {se2} selected from region {se2_region}.")
            elif SE is True:
                logger.info(" SE2 selection for SE1 SE.")
                # if se1 is SE, select from SSEM, SEM, or SE
                se2_region_select = [
                    region for region in region_plus_median if region != se1_region
                ]
                se2_region = choice(se2_region_select)
                # Select a random region from se2_region_select
                se2 = choice(se_dict[se2_region][1])
                logger.info(f" SE2 {se2} selected from region {se2_region}.")

            if kobayashi is False:
                # Has se1 and se2 been paired before?
                for _ in range(5):
                    try:
                        check_pairing_se2 = p.cwa_matches.find_one({"SE": se2})
                        break
                    except ConnectionFailure as e:
                        logger.error(
                            " *** Connect error getting SE2 from cwa_matches collection."
                        )
                        logger.warning(
                            f" *** Sleeping for {pow(2, _)} seconds and trying again."
                        )
                        sleep(pow(2, _))
                        logger.error(e)

                # is assignments empty?
                if not check_pairing_se2["assignments"]:
                    logger.info(
                        f"{se2} has no assignment history. {len(check_pairing_se2["assignments"])}"
                    )
                    logger.info(f"SE1 {se1} and SE2 {se2} have not been paired before.")
                    del check_pairing_se2
                else:
                    # Create a set of previous matches for se2
                    se2_assignments = {
                        x for x in check_pairing_se2["assignments"].values()
                    }
                    del check_pairing_se2

                    # check if se1 is in se2_assignment
                    if se1 not in se2_assignments:
                        logger.info(f" {se1} and {se2} have not been paired before.")

                    # Paired before. Logic to select a different SE2.
                    else:
                        logger.info(f" {se1} and {se2} have been paired before.")

                        # Can a unique match be made?
                        if len(SEs) == 1:
                            logger.warning("Only one SE left and not a good match.")
                            # Was a match made with SE1 in the last 2 years?
                            target_date = waterline_target()
                            # Check if se1 and se2 were matched in the last 2 years
                            match_check = last_match_date(se1, se2, target_date)
                            if match_check is False:
                                kobayashi = True
                            else:
                                print(
                                    "  Previously matched longer than 2 years ago. Good match."
                                )

                        else:
                            # Create a list of previous matches for se1
                            for _ in range(5):
                                try:
                                    se1_matches = list(
                                        p.cwa_matches.find_one({"SE": se1})[
                                            "assignments"
                                        ].values()
                                    )
                                    break
                                except ConnectionFailure as e:
                                    logger.error(
                                        " *** Connect error getting SE1 from cwa_matches collection."
                                    )
                                    logger.info(
                                        f" *** Sleeping for {pow(2, _)} seconds and trying again."
                                    )
                                    sleep(pow(2, _))
                                    logger.debug(e)
                            # Create a list of SEs that se1 has not been paired with
                            se1_matchables = [x for x in SEs if x not in se1_matches]
                            logger.info(
                                f" Potential matches for se1: {len(se1_matchables)}"
                            )

                            if len(se1_matchables) > 0:
                                # Select new se2 from se1_matchables
                                se2 = choice(se1_matchables)
                                se2_region, se2_region_name = lookup_region(se2)
                                logger.info(
                                    f" SE2 {se2} selected from region {se2_region_name}."
                                )
                                try_count = 1

                                # Is se2 in the same region as se1?
                                while se2_region == se1_region or (
                                    se1_region == 100 and se2_region == 0
                                ):
                                    logger.warning(
                                        f" {se1} and {se2} are not a good pairing. Try again."
                                    )
                                    # Remove previous se2 selection from se1_matchables
                                    se1_matchables.remove(se2)
                                    logger.info(
                                        f" Potential matches: {len(se1_matchables)}"
                                    )

                                    if len(se1_matchables) == 0:
                                        # No more potential matches for se1
                                        logger.warning(
                                            f" No more potential matches for {se1}."
                                        )
                                        logger.warning(
                                            "  *** Kobayashi Maru. Trigger reset. ***"
                                        )
                                        kobayashi = True
                                        break

                                    # Select a random SE from se1_matchables
                                    se2 = choice(se1_matchables)
                                    # lookup region for se2
                                    se2_region, se2_region_name = lookup_region(se2)
                                    logger.info(
                                        f" Selected region {se2_region} with {len(se_dict[se2_region][1])} SEs."
                                    )
                                    logger.info(
                                        f" SE2 {se2} selected from region {se2_region_name}."
                                    )
                                    try_count += 1

                                logger.info(f" Selected {se2} in {try_count} attempts.")
                            else:
                                # No more potential matches for se1
                                logger.warning(f" No more potential matches for {se1}.")
                                logger.warning(
                                    "  *** Kobayashi Maru. Trigger reset. ***"
                                )
                                kobayashi = True
                                break

                            # clear temp variables
                            se1_matches = []
                            se1_matchables = []

                    # Clear temp variables
                    se2_assignments = []

                if kobayashi is False:
                    """Profile SE2"""

                    VIP2 = False
                    SSEM2 = False
                    SEM2 = False
                    SE2 = False

                    # If SEM not attending, remove from sem_present_set
                    sem_set = sem_set.intersection(SEs)

                    # Is se1 a VIP?
                    if se2 in vips:
                        VIP2 = True
                        logger.info(f" --> {se2} is a VIP.")

                    # Is se2 a senior leader?
                    elif se2 in zero_set:
                        SSEM2 = True
                        logger.info(f" --> {se2} is a senior leader.")
                        logger.info(f" SSEM's in region 0: {zero_set}")

                    # Is se2 a SEM?
                    elif se2 in sem_set:
                        SEM2 = True
                        logger.info(f" --> {se2} is a SEM.")

                    else:
                        SE = True
                        logger.info(f" --> {se2} is a regular SE.")

                    # Clean up after selecting se2
                    logger.info("Clean up after selecting SE2.")
                    cleanup_se(
                        se2_region, se2, se_dict, sem_set, SEs, top_ses, vips, zero_set
                    )
                    if se2 in top_ses:
                        top_ses.discard(se2)
                        logger.info(f" Removed {se2} from top_ses.")

            # Clean up region_plus_median list
            region_plus_median = []

            if kobayashi is False:
                # recalculate count
                count = calculate_count(se_dict)
                logger.info(f"SEs remaining: {count}")

                # Create a list of SE pairs and append to se_pair_list
                se_pair = [se1, se2]
                se_pair_list.append(se_pair)
                logger.debug(f"Paired {se_pair}")
                se_pair = []

            # Clear se1 and se2 temp variables
            temp_vars = [
                "se1",
                "se2",
                "se1_region",
                "se2_region",
                "se2_region_name",
                "se_pair",
                "se2_assignments",
                "se_choice",
                "se_median",
                "region_plus_median",
                "se2_region_select",
                "se_region",
                "priority_region",
            ]

            for _ in temp_vars:
                try:
                    del globals()[_]
                except KeyError:
                    pass

            if len(SEs) > 0:
                logger.info("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
                logger.info(f"  {len(SEs - sem_set - zero_set - vips)} SEs to match.")
                logger.info(f"  SSEM's to match: {zero_set}")
                logger.info(f"  {len(sem_set)} SEM's to match: {sem_set}")
                # calculate the percentage of SSEMs and SEMs to SEs
                if len(SEs) > 0:
                    leader_percent = round(
                        (len(zero_set) + len(sem_set)) / len(SEs) * 100, 2
                    )
                if leader_percent:
                    logger.info(f"  {leader_percent}% of SEs are leaders.")
                logger.info(f"  Total number of SEs: {len(SEs)}")
                logger.info("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")

        if kobayashi is True:
            # Reset and start over
            if kobayashi_counter == 5:
                logger.warning("Kobayashi Maru scenario encountered 5 times. Exiting.")
                return 500
            se_pair_list = []
            # SEs is a set of SEs to be tracked
            SEs, full_SEs, se_assignment_count, percentile, top_ses = (
                kobayashi_reset.kobayashi(
                    kobayashi_counter, kobayashi_se_set, kobayashi_full_SEs
                )
            )

            # Create se_dict
            se_dict = create_se_dict(SEs, full_SEs)

            # Create the sem_set
            sem_set = make_sem_set(SEs)
            logger.info(f"Reset number {kobayashi_counter} complete.")

    if kobayashi is False:

        logger.info("No more SEs remaining.")

        logger.info(se_pair_list)
        logger.info(f"Number of pairs: {len(se_pair_list)}")

        collection_updates = 0

        if test_mode is False:
            # Add se_pair_list to cwa_matches collection
            for x, y in se_pair_list:
                # Add se1 and se2 to cwa_matches collection
                assignment_date = f"assignments.{fuse_date}"

                for _ in range(5):
                    try:
                        add_se = p.cwa_matches.update_one(
                            {"SE": x},
                            {"$set": {assignment_date: y}},
                            upsert=True,
                        )
                        logger.info(f" Added {x} match to database.")
                        collection_updates += 1
                        break
                    except Exception as e:
                        logger.error(f"Error updating {x} to cwa_matches collection.")
                        logger.error(e)
                        return 500

                for _ in range(5):
                    try:
                        add_se = p.cwa_matches.update_one(
                            {"SE": y},
                            {"$set": {assignment_date: x}},
                            upsert=True,
                        )
                        logger.info(f" Added {y} match to database.")
                        collection_updates += 1
                    except Exception as e:
                        logger.error(f"Error adding {y} to cwa_matches collection.")
                        logger.error(e)
                        return 500

                # Update SE x
                if update_cwa_matches(x, y, assignment_date):
                    collection_updates += 1
                else:
                    # Decide how to handle the cumulative error case
                    pass

                # Update SE y
                if update_cwa_matches(y, x, assignment_date):
                    collection_updates += 1
                else:
                    # Decide how to handle the cumulative error case
                    pass

                logger.info(f"Collection updates: {collection_updates}")

        # remove / from fuse_date
        f_date = fuse_date.replace("/", "")

        # create a csv file of the matches
        try:
            date_name = fuse_date.replace("/", "_")
            matches_filename = f"{date_name}-matches.csv"
            write_matches_to_file(matches_filename, se_pair_list)
        except PermissionError:
            logger.error("PermissionError writing matches to file.")
            filename_count = randint(1, 100)
            matches_filename = f"{f_date}-matches-PE{filename_count}.csv"
            write_matches_to_file(matches_filename, se_pair_list)
        except Exception as e:
            logger.error("Error writing matches to file.")
            logger.error(e)
            return 500

    end_time = perf_counter()
    logger.info(f"Total time to complete: {end_time - start_time:.6f} seconds.")

    if test_mode is False:
        return matches_filename
    else:
        return NA
