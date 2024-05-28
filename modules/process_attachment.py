import logging
import re
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


class ProcessAttachment:
    """
    Class to process attachments
    """

    def __init__(self, fuse_date, attachment, mongo_connect_uri):
        """
        Constructor
        """
        self.fuse_date = fuse_date
        self.attachment = attachment
        self.mongo_connect_uri = mongo_connect_uri
        self.logger = logging.getLogger(__name__)

    def process(self):
        """
        Process attachment
        """
        try:
            self.logger.info(f"Processing attachment {self.attachment}")
            # Open the attachment file properly
            with open(f"./uploads/{self.attachment}", "r", encoding="utf-8-sig") as data_file:
                lines = data_file.read().splitlines()
                remaining_lines = lines[1:]  # Skip first line if needed
        except ConnectionFailure as err:
            self.logger.error(f"Unable to open {self.attachment}: {err}")
            # TODO: Add proper error handling to let the user know the file is not there
            return

        pre_attendees = []
        for line in remaining_lines:
            transformed_line = re.sub(r"\((.*?)\)", r", \1", line)
            line_list = [item.strip() for item in transformed_line.split(",")]
            pre_attendees.append(line_list)

        accept = set()
        decline = set()
        tentative = set()
        no_response = set()

        for attendee in pre_attendees:
            if attendee[3] == "Accepted":
                accept.add(attendee[1])
            elif attendee[3] == "Declined":
                decline.add(attendee[1])
            elif attendee[3] == "Tentative":
                tentative.add(attendee[1])
            else:
                no_response.add(attendee[1])

        self.logger.info(
            f"Attendees:\n"
            f" Accepted: {len(accept)}\n"
            f" Declined: {len(decline)}\n"
            f" Tentative: {len(tentative)}\n"
            f" No response: {len(no_response)}"
        )

        # Does cwa_attendees record exist for this date?
        for _ in range(5):
            try:
                if self.mongo_connect_uri[pref.MONGODB]["cwa_prematch"].find_one(
                    {"date": self.fuse_date}
                ):
                    self.logger.info(f" Record for {self.fuse_date} exists in prematch table.")
                else:
                    # Create the record
                    self.mongo_connect_uri[pref.MONGODB]["cwa_prematch"].insert_one(
                        {"date": self.fuse_date}
                    )
                    self.logger.info(f" Record for {self.fuse_date} created in prematch table.")
                break
            except ConnectionFailure as cf:
                self.logger.error(f" Connection Failure looking up attendees record: {cf}")
                self.logger.warning("  *** Sleeping for {pow(2, _)} seconds and trying again ***")
                sleep(pow(2, _))

        # Add responses to the database
        self.logger.info("Adding SE responses to attendees database")
        for _ in range(5):
            try:
                # Convert sets to lists for MongoDB update
                accept_list = list(accept)
                decline_list = list(decline)
                tentative_list = list(tentative)
                no_response_list = list(no_response)

                # Combine all entries to ensure removal from all statuses
                all_entries = accept_list + decline_list + tentative_list + no_response_list

                # First, remove entries from all statuses
                update_result = self.mongo_connect_uri[pref.MONGODB]["cwa_prematch"].update_one(
                    {"date": self.fuse_date},
                    {
                        "$pull": {
                            "accepted": {"$in": all_entries},
                            "declined": {"$in": all_entries},
                            "tentative": {"$in": all_entries},
                            "no_response": {"$in": all_entries},
                        }
                    }
                )
                self.logger.info(f"Updated {update_result.modified_count} documents.")

                # Remove any documents that are not in any of the lists
                # WARNING: This operation will delete data from your database. Use with caution.
                update_result = self.mongo_connect_uri[pref.MONGODB]["cwa_prematch"].update_many(
                    {"date": self.fuse_date},
                    {
                        "$pull": {
                            "accepted": {"$nin": accept_list},
                            "declined": {"$nin": decline_list},
                            "tentative": {"$nin": tentative_list},
                            "no_response": {"$nin": no_response_list},
                        }
                    }
                )
                self.logger.info(f"Updated {update_result.modified_count} documents.")

                # Next, add entries to their respective current status using $addToSet
                update_result = self.mongo_connect_uri[pref.MONGODB]["cwa_prematch"].update_one(
                    {"date": self.fuse_date},
                    {
                        "$addToSet": {
                            "accepted": {"$each": accept_list},
                            "declined": {"$each": decline_list},
                            "tentative": {"$each": tentative_list},
                            "no_response": {"$each": no_response_list},
                        }
                    }
                )
                self.logger.info(f"Updated {update_result.modified_count} documents.")
                break
            except ConnectionFailure as cf:
                self.logger.error(
                    f" Connection Failure adding responses to attendees database: {cf}"
                )
                self.logger.warning("  *** Sleeping for {pow(2, _)} seconds and trying again ***")
                sleep(pow(2, _))
        return (len(accept), len(decline), len(tentative), len(no_response))
