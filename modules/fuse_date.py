import logging
from datetime import datetime, timezone

from pymongo import DESCENDING
from pymongo.errors import PyMongoError

# pylint: disable=logging-fstring-interpolation

# Logging to Flask console
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FuseDate:
    """FuseDate class gets/sets the Fuse date from Mongo"""

    def get_fuse_date(self, mongo_connect_uri, db, area, mode):
        if mode == "debug":
            logger.info("Get Fuse Date - Debug mode")
            date_collection = "date"
        else:
            date_collection = area + "_date"
        try:
            # Attempt to get the fuse date from MongoDB
            logger.info(f"Fetching fuse date from MongoDB: {db}")
            try:
                fuse_date_record = mongo_connect_uri[db][date_collection].find_one(
                    {}, sort=[("timestamp", DESCENDING), ("_id", DESCENDING)]
                )
            except Exception as e:
                logger.error(f"Error fetching fuse date from MongoDB: {e}")

            # Check if a record was found
            if fuse_date_record is None:
                logger.error("No fuse date records found in MongoDB.")
                return None

            # Attempt to retrieve the 'date' field from the record
            fuse_date = fuse_date_record.get("date")
            if fuse_date is None:
                logger.error("The 'date' field is missing in the fuse date record.")
                return None

            logger.info(f"Fuse date found in MongoDB: {fuse_date}")
            return fuse_date
        except PyMongoError as e:
            # Handle general PyMongo errors
            logger.error(f"An error occurred while fetching the fuse date from MongoDB: {e}")
            return None
        except Exception as e:
            # Handle other unexpected errors
            logger.error(f"An unexpected error occurred: {e}")
            return None

    def set_fuse_date(self, mongo_connect_uri, db, area, fuse_date, mode):
        """Set Fuse date in Mongo"""
        logger.info(
            f"Setting fuse date in MongoDB (mode: {mode} db: {db}): {fuse_date}"
        )
        if mode == "debug":
            date_collection = "date"
        else:
            date_collection = area + "_date"
        new_fuse_date = mongo_connect_uri[db][date_collection].update_one(
            {"date": fuse_date},
            {
                "$set": {
                    "timestamp": timestamp(),
                    "date": fuse_date,
                }
            },
            upsert=True,  # Insert a new document if no match is found
        )

        document_id = (
            new_fuse_date.upserted_id
            if new_fuse_date.upserted_id is not None
            else "fuse_date"
        )
        logger.info(f"Inserted document id: {document_id}")


def timestamp():
    """Return a timestamp in UTC"""
    now = datetime.now(timezone.utc)
    dt_str = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-2] + "Z"
    updated_time_stamp = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ")
    return updated_time_stamp
