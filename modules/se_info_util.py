import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from logging.handlers import RotatingFileHandler
from random import randint
from threading import current_thread
from time import sleep
from typing import Any, Dict, List, Optional

import certifi
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

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


def get_se_name(Mongo_Connection_URI, x, user_db):
    """Helper function to get SE name with retry logic."""
    # log contents of session
    for _ in range(5):
        try:
            # Lookup name from cwa_SEs collection
            se_name = Mongo_Connection_URI[user_db]["cwa_SEs"].find_one({"se": x})
            if se_name is not None:
                return [x, se_name["se_name"]]
            else:
                logger.warning(f"Unknown SE: {x}")
                return None
        except ConnectionFailure as e:
            logger.error(f"Connect error getting SE {x} from cwa_SEs collection.")
            logger.error(f"Sleeping for {pow(2, _)} seconds and trying again.")
            sleep(pow(2, _))
            logger.error(e)
    return None


def get_full_se_list(Mongo_Connection_URI, SEs, user_db) -> list:
    """Get full list of SEs from se_info collection."""
    logger.info("Getting full SE list")
    full_SEs = []

    # Test MongoDB connection
    try:
        Mongo_Connection_URI.admin.command("ping")
        logger.info("MongoDB connection successful.")
    except ConnectionFailure as e:
        logger.error("MongoDB connection failed.")
        logger.error(e)

    logger.info("Launching ThreadPoolExecutor to get SE names.")

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_se = {
            executor.submit(get_se_name, Mongo_Connection_URI, x, user_db): x
            for x in SEs
        }
        for future in as_completed(future_to_se):
            se_name = future.result()
            if se_name:
                full_SEs.append(se_name)
                logger.info(f"Added SE name to full_SEs: {se_name}")

    return full_SEs


def get_se_info(
    x: str, se_dict: dict, mode: str, user_db: str
) -> Optional[Dict[str, Any]]:

    logger.info(f"Start get_se_info for {x} in mode {mode}.")

    # MongoDB connection setup
    if mode == "debug":
        Mongo_Uri = (
            f"mongodb+srv://{p.MONGOUN}:{p.MONGO_BEARER}@{p.MONGOHOST}/{user_db}"
        )
        Mongo_Connection_URI: MongoClient = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )
    else:
        Mongo_Uri = (
            f"mongodb+srv://{p.CWA_SE_USER}:{p.CWA_SE_BEARER}@{p.MONGOHOST}/{user_db}"
        )
        Mongo_Connection_URI: MongoClient = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )

    # Get SE info from se_info collection and add SE/Region details to se_dict.

    if current_thread().name == "MainThread":
        for _ in range(5):
            try:
                se_info_result = Mongo_Connection_URI[user_db]["cwa_SEs"].find_one(
                    {"se": x}
                )
                break
            except ConnectionFailure as e:
                logger.warning(
                    f" *** Connect error getting SE {x} from se_info collection."
                )
                logger.warning(
                    f" *** Sleeping for {pow(2, _)} seconds and trying again."
                )
                sleep(pow(2, _))
                logger.warning(e)
        logger.error(
            " *** Failed attempt to connect to se_info collection. Mongo is down."
        )
    else:
        # logger.info(x)
        se_info_result = Mongo_Connection_URI[user_db]["cwa_SEs"].find_one({"se": x})
    if se_info_result is not None:
        se_region = se_info_result["region"]
        se_record = [[se_region], [x]]
        if current_thread().name == "MainThread":
            for _ in range(5):
                try:
                    region_numb_result = p.cwa_regions.find_one({"Region": se_region})
                    break
                except ConnectionFailure as e:
                    logger.warning(
                        f" *** Connect error getting SE {x} from cwa_regions collection."
                    )
                    logger.warning(
                        f" *** Sleeping for {pow(2, _)} seconds and trying again."
                    )
                    sleep(pow(2, _))
                    logger.warning(e)
            logger.error(
                " *** Failed attempt to connect to cwa_regions collection. Mongo is down."
            )
        else:
            region_numb_result = p.cwa_regions.find_one({"Region": se_region})
        if region_numb_result is not None:
            region_numb = region_numb_result["Index"]
        if region_numb in se_dict:
            # Append se_dict with se_region and se
            se_dict[region_numb][1].append(x)
        else:
            # Add se_dict with se_region and se
            se_dict[region_numb] = se_record
    return se_info_result


def add_unknown_se(
    x: str,
    full_SEs: List[List[str]],
    se_dict: Dict[int, List[List[str]]],
    mode: str,
    user_db: str,
) -> Optional[Dict[str, Any]]:

    logger.info(f"Start add_unknown_se for {x} in mode {mode}.")
    logger.info(f"user_db: {user_db}")

    logger.info(f"full_SEs: {full_SEs}")

    # MongoDB connection setup
    if mode == "debug":
        Mongo_Uri = (
            f"mongodb+srv://{p.MONGOUN}:{p.MONGO_BEARER}@{p.MONGOHOST}/{user_db}"
        )
        Mongo_Connection_URI: MongoClient = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )
    else:
        Mongo_Uri = (
            f"mongodb+srv://{p.CWA_SE_USER}:{p.CWA_SE_BEARER}@{p.MONGOHOST}/{user_db}"
        )
        Mongo_Connection_URI = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )

    # find x in full_SEs and get the name
    unknown_se = [y for y in full_SEs if y[1] == x]

    # Get highest se_idx from se_info collection and return it
    for _ in range(5):
        try:
            hi_idx = Mongo_Connection_URI[user_db]["cwa_SEs"].find_one(
                sort=[("se_idx", -1)]
            )
            logging.info(f"hi_idx: {hi_idx}")
            break
        except ConnectionFailure as e:
            logger.warning(
                " *** Connect error getting highest se_idx from se_info collection."
            )
            logger.warning(f" *** Sleeping for {pow(2, _)} seconds and trying again.")
            sleep(pow(2, _))
            logger.warning(e)
    if hi_idx is not None:
        next_se_idx = int(hi_idx["se_idx"]) + 1
    else:
        next_se_idx = randint(100000, 999999)

    # Add SE to se_info collection
    logger.info(f"Adding SE {x} with se_idx {next_se_idx} to {user_db} collection.")
    logger.info(f"unknown_se: {unknown_se}")
    # if unknown_se is an empty list, add a default name
    if not unknown_se:
        logger.warning(f"Unknown SE: {x}")
        unknown_se = [[x, "Unknown name"]]
    for _ in range(5):
        try:
            Mongo_Connection_URI[user_db]["cwa_SEs"].insert_one(
                {
                    "se_idx": next_se_idx,
                    "se": x,
                    "se_name": unknown_se[0][0],
                    "op": "VIP",
                    "region": "VIP",
                }
            )
            logger.info(f"SE {x} added to se_info collection.")
            break
        except ConnectionFailure as e:
            logger.warning(
                " *** Connect error getting highest se_idx from se_info collection."
            )
            logger.warning(f" *** Sleeping for {pow(2, _)} seconds and trying again.")
            sleep(pow(2, _))
            logger.warning(e)
    # logger.error(f"Error adding SE {x} to se_info collection.")

    # Add x to cwa_matches collection if not already there
    for _ in range(5):
        try:
            if Mongo_Connection_URI[user_db]["cwa_matches"].find_one({"SE": x}) is None:
                Mongo_Connection_URI[user_db]["cwa_matches"].insert_one(
                    {"SE": x, "assignments": {}}
                )
                logger.info(f"SE {x} added to cwa_matches collection.")
            else:
                logger.info(f"SE {x} already in cwa_matches collection.")
            break
        except ConnectionFailure as e:
            logger.warning(
                " *** Connect error getting highest se_idx from se_info collection."
            )
            logger.warning(f" *** Sleeping for {pow(2, _)} seconds and trying again.")
            sleep(pow(2, _))
            logger.warning(e)
    # logger.error(f"Error adding SE {x} to cwa_matches collection.")

    # Add SE to se_dict
    se_info_result = get_se_info(x, se_dict, mode, user_db)

    return se_info_result
