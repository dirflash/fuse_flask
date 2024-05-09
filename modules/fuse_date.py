import logging
from datetime import datetime, timezone

from pymongo import DESCENDING

import modules.preferences.preferences as pref

# pylint: disable=logging-fstring-interpolation

logger = logging.getLogger(__name__)


class FuseDate:
    """FuseDate class gets/sets the Fuse date from Mongo"""

    def get_fuse_date(self, mongo_connect_uri):
        # Get Fuse date from Mongo
        fuse_date_record = mongo_connect_uri[pref.MONGODB]["date"].find_one(
            {}, sort=[("date", DESCENDING)]
        )
        fuse_date = fuse_date_record["date"]
        logger.info(f"Fuse date found in MongoDB: {fuse_date}")
        return fuse_date


def timestamp():
    """Return a timestamp in UTC"""
    now = datetime.now(timezone.utc)
    dt_str = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-2] + "Z"
    updated_time_stamp = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ")
    return updated_time_stamp
