import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
from time import sleep

import aiohttp
import certifi
from pymongo import MongoClient, UpdateOne
from pymongo.errors import BulkWriteError, ConnectionFailure

import modules.preferences.preferences as pref
from cards import reminder_card as rc

# pylint: disable=logging-fstring-interpolation, undefined-variable

Mongo_Connection_URI: MongoClient = MongoClient(
    f"{pref.MONGO_URI}?retryWrites=true&w=majority",
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=500,
)

console_formatter = logging.Formatter(
    "%(asctime)s - %(filename)s:%(lineno)d - %(name)s - %(levelname)s - %(message)s"
)

# Create a stream handler with the formatter
console_handler = logging.StreamHandler()
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.INFO)

# Create a file handler for file logging
file_handler = RotatingFileHandler(
    "./logs/reminders.log", maxBytes=10 * 1024 * 1024, backupCount=5
)  # 10 MB
file_handler.setFormatter(console_formatter)
file_handler.setLevel(logging.INFO)

# Logging to Flask console
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(console_handler)
logger.addHandler(file_handler)  # Add file handler to the logger
logger.propagate = False

message_counter = {
    "accepted": 0,
    "tentative": 0,
    "no_response": 0,
}
message_sets: dict[str, set] = {}

headers = {
    "Authorization": pref.fusebot_help_bearer,
    "Content-Type": "application/json",
}

reminders_collection = Mongo_Connection_URI["fuse-test"]["cwa_reminders"]


async def send_message(session, email, payload, message_type):
    max_retries = 3
    too_many_requests_counter = 0
    too_many_requests_limit = 1
    for i in range(max_retries):
        try:
            async with session.post(
                pref.WEBEX_MSG_URL, json=payload, headers=headers
            ) as response:
                if response.status == 429:
                    # Use the Retry-After header to determine how long to wait
                    retry_after = int(
                        response.headers.get("Retry-After", 5)
                    )  # Default to 5 seconds if Retry-After header is not provided
                    if too_many_requests_counter < too_many_requests_limit:
                        print(
                            f" Too many requests, retrying in {retry_after} seconds..."
                        )
                        too_many_requests_counter += 1
                    await asyncio.sleep(
                        retry_after
                    )  # Pause execution for 'retry_after' seconds
                    continue
                if response.status == 200:
                    logger.info(
                        f" Sent {message_type} message to {email} ({response.status})"
                    )
                    response_text = await response.text()
                    message_id = json.loads(response_text)["id"]
                    # Increment the counter for the message type
                    message_counter[message_type] += 1
                    return [message_id, email, 200]
                logger.warning(
                    f" Unexpected status ({response.status}) sending to {email}"
                )
                return None
        except Exception as e:
            logger.error(
                f" Failed to send {message_type} message to {email} due to {str(e)}"
            )


async def main(fuse_date):
    async with aiohttp.ClientSession() as session:
        tasks = []
        markdown_msg = (
            "Adaptive card response. Open the message on a supported client to respond."
        )
        for message_type, message_set in message_sets.items():
            if message_set:
                # Create the attachment inside the loop
                attachment = rc.reminder_card(fuse_date, message_type)
                for person in message_set:
                    email = f"{person}@cisco.com"  # < --- change to p.test_email for test. person in prod mode
                    payload = {
                        "toPersonEmail": email,
                        "markdown": markdown_msg,
                        "attachments": attachment,
                    }
                    tasks.append(send_message(session, email, payload, message_type))

        results = await asyncio.gather(*tasks)

        # Update the reminders database with the message status and message id
        if results:
            logger.info(f"Processing {len(results)} results")
            operations = []
            for result in results:
                logger.info(f"Processing result: {result}")
                # Assuming that result[1] is the email
                alias = result[1].replace("@cisco.com", "") if len(result) > 1 else None
                try:
                    # Attempt to unpack the tuple
                    message_id, email, status = result
                    logger.info(f"Adding {email} message to reminders database")
                    # Add the UpdateOne operation to the list
                    operations.append(
                        UpdateOne(
                            {"date": fuse_date, "alias": alias},
                            {
                                "$set": {
                                    "message_id": message_id,
                                    "email": email,
                                    "status": status,
                                }
                            },
                            upsert=True,
                        )
                    )
                except (TypeError, ValueError) as te:
                    # Log an error message if unpacking fails
                    logger.error(
                        f"Error unpacking result for record {alias}: {te} - skipping record"
                    )

            if operations:
                logger.info(f"Operations to execute: {len(operations)}")
            else:
                logger.info("No operations to execute")

            # Only perform the bulk write if there are operations to execute
            if operations:
                logger.info(f"Operations to execute: {len(operations)}")
                logger.info("Updating reminders database")
                for attempt in range(5):
                    try:
                        reminder_updates = reminders_collection.bulk_write(operations)
                        if reminder_updates.upserted_ids:
                            logger.info(
                                f"MongoDB upserted {len(reminder_updates.upserted_ids)} records."
                            )
                        break  # Exit the retry loop if successful
                    except BulkWriteError as bwe:
                        print("Bulk Write Error: ", bwe.details)
                        sleep_duration = pow(2, attempt)
                        logger.warning(
                            f"*** Sleeping for {sleep_duration} seconds and trying again ***"
                        )
                        sleep(sleep_duration)  # Exponential backoff
                    except Exception as e:
                        logger.error(f"An unexpected error occurred: {e}")
                        logger.error(f"operations: {operations}")
                        break  # Exit the retry loop if an unexpected exception occurs
            else:
                logger.info("No operations to execute")

        # Print the message counter at the end
        logger.info(f"Sent message count by type: {message_counter}")
        logger.info(f"Total messages sent: {sum(message_counter.values())}")


class Reminders:
    """
    Class to process attachments
    """

    def __init__(self, inside_fuse_date, mongo_connect_uri):
        """
        Constructor
        """
        self.fuse_date = inside_fuse_date
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
            # make message_sets a global variable
            global message_sets  # pylint: disable=global-statement
            message_sets = {
                "accepted": accepted_set,
                "tentative": tentative_set,
                "no_response": no_response_set,
            }
            logger.info(f" **** MESSAGE SETS: {message_sets}")
            asyncio.run(main(self.fuse_date))
            self.logger.info("Main function finished")
            return True, accepted_set, declined_set, tentative_set, no_response_set
        except ConnectionFailure as cf:
            self.logger.error(f" Connection Failure looking up attendees record: {cf}")
            self.logger.warning(
                "  *** Sleeping for {pow(2, _)} seconds and trying again ***"
            )
            sleep(pow(2, _))  # noqa: F821  # type: ignore
            return False, 0, 0, 0, 0
        except KeyError:
            self.logger.error("  *** No attendees record found ***")


if __name__ == "__main__":
    pass
