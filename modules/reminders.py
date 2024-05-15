import logging
from time import sleep

from pymongo.errors import ConnectionFailure

import modules.preferences.preferences as pref

# pylint: disable=logging-fstring-interpolation


console_formatter = logging.Formatter(
    "%(asctime)s - %(filename)s:%(lineno)d - %(name)s - %(levelname)s - %(message)s"
)

# Create a stream handler with the formatter
console_handler = logging.StreamHandler()
console_handler.setFormatter(console_formatter)

# Logging to Flask console
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
logger.addHandler(console_handler)


class Reminders:
    """
    Class to process attachments
    """

    def __init__(self, fuse_date, mongo_connect_uri):
        """
        Constructor
        """
        self.fuse_date = fuse_date
        self.mongo_connect_uri = mongo_connect_uri
        self.logger = logging.getLogger(__name__)

    def send_reminders(self):
        """
        Process reminders
        """
        try:
            # Retrieve the attendees record from the database
            self.logger.info("Retrieving attendees record")
            attendees = self.mongo_connect_uri[pref.MONGODB]["cwa_prematch"].find_one(
                {"date": self.fuse_date}
            )
            if attendees is None:
                self.logger.info("No attendees record found")
                return (None, set(), set(), set(), set())
            self.logger.info(attendees)
            accepted_set = set(attendees["accepted"])
            declined_set = set(attendees["declined"])
            tentative_set = set(attendees["tentative"])
            no_response_set = set(attendees["no_response"])
            self.logger.info("Retrieved attendees record")
            return True, accepted_set, declined_set, tentative_set, no_response_set
        except ConnectionFailure as cf:
            self.logger.error(" Connection Failure looking up attendees record: ", cf)
            self.logger.warning("  *** Sleeping for {pow(2, _)} seconds and trying again ***")
            sleep(pow(2, _))
            return
        except KeyError:
            self.logger.error("  *** No attendees record found ***")
