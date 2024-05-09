import logging
import os
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler

import certifi
import pandas as pd
from flask import (
    Flask,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from pymongo import MongoClient
from werkzeug.utils import secure_filename

import modules.preferences.preferences as pref
from modules.fuse_date import FuseDate

# pylint: disable=logging-fstring-interpolation

app = Flask(__name__)

# Set up console logging
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
console_handler.setFormatter(console_formatter)

# Set up file logging
log_file = os.path.join(app.root_path, "logs", "flask_app.log")
file_handler = RotatingFileHandler(log_file, maxBytes=10000, backupCount=5)
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
file_handler.setFormatter(file_formatter)

# Configure the root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

app.logger.info("Application started")

app.config["UPLOAD_FOLDER"] = "uploads/"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

ALLOWED_EXTENSIONS = {"csv"}

# Setup the MongoDB connection
Mongo_Connection_URI: MongoClient = MongoClient(
    f"{pref.MONGO_URI}?retryWrites=true&w=majority",
    tlsCAFile=certifi.where(),serverSelectionTimeoutMS=500
)

"""def check_mongo_connection():
    # Test the MongoDB connection
    try:
        Mongo_Connection_URI.server_info()
        app.logger.info("Test connection to MongoDB successful.")
    except ConnectionFailure as mongo_connection_failure:
        app.logger.error("Failed to connect to MongoDB")
        app.logger.error(mongo_connection_failure)
        return render_template(
            "notification.html"
        ), 503  # Return notification page with 503 Service Unavailable status
    except OperationFailure as mongo_operation_failure:
        error_details = mongo_operation_failure.details
        app.logger.error(
            f"*** Failed to connect to MongoDB.***"
            f"Error Message: {error_details['errmsg']}"
        )
        return render_template(
            "notification.html"
        ), 500  # Return notification page with 500 Internal Server Error
    else:
        # Close connection to Mongo
        Mongo_Connection_URI.close()
        app.logger.info("Closed connection to MongoDB.")"""


"""scheduler = BackgroundScheduler()
scheduler.add_job(
    func=lambda: print("Scheduler task running."), trigger="interval", seconds=60
)
scheduler.start()

# Ensure that the scheduler is shut down properly on application exit
atexit.register(lambda: scheduler.shutdown(wait=False))"""


def allowed_file(filename):
    """Defines allowed file extensions to be uploaded

    Args:
        filename (str): uploaded filename

    Returns:
        str: file extension if in ALLOWED_EXTENSIONS
    """
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/upload", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        # Check if a file was uploaded
        if "file" not in request.files:
            return render_template("upload.html", error="No file uploaded")

        file = request.files["file"]

        # Check if the file has a name
        if file.filename == "":
            return render_template("upload.html", error="No file selected")

        # Check if the file extension is allowed
        if not allowed_file(file.filename):
            return render_template("upload.html", error="File type not allowed")

        if file.content_length > app.config["MAX_CONTENT_LENGTH"]:
            return render_template("upload.html", error="File size exceeds the limit")

        # Check if the uploads folder exists
        if not os.path.exists(app.config["UPLOAD_FOLDER"]):
            os.makedirs(app.config["UPLOAD_FOLDER"])

        # If the file already exists, delete it and upload the new file
        if os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], file.filename)):
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], file.filename))

        # Record the start time
        start_time = time.time()

        # Save the file to the uploads folder
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        # Read the file into a Pandas DataFrame
        df = pd.read_csv(file_path)

        # Calculate the upload time with a maximum of 4 decimal places
        upload_time = round(time.time() - start_time, 4)

        # Get file metadata
        file_size = os.path.getsize(file_path)

        return render_template(
            "upload.html",
            message="File uploaded successfully",
            filename=filename,
            data=df.to_html(index=False, classes='table table-striped'),
            file_size=file_size,
            upload_time=upload_time,
        )

    return render_template("upload.html")


# Define a route for the home page
@app.route('/')
def home():
    """Get the Fuse date"""
    fuse_date = FuseDate().get_fuse_date(Mongo_Connection_URI)
    if fuse_date is None:
        fuse_date = "Not set"
    else:
        fuse_date_obj = datetime.strptime(fuse_date, "%Y-%m-%d")
        current_time = datetime.now()
        if fuse_date_obj < current_time:
            fuse_date = "Expired"
            return redirect(url_for("set_fuse_date"))
        else:
            app.logger.info(f"Fuse date: {fuse_date_obj}")
            app.logger.info(f"Current time: {current_time}")
    return render_template("index.html", fuse_date=fuse_date)


# Define a route for the about page
@app.route('/about')
def about():
    return render_template('about.html')

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )

@app.route("/set_fuse_date", methods=["GET", "POST"])
def set_fuse_date():
    if request.method == "POST":
        # Get the new fuse date from the form
        new_fuse_date = request.form["new_fuse_date"]
        app.logger.info(f"New fuse date: {new_fuse_date}")

        try:
            # Convert the new fuse date to a datetime object
            new_fuse_date_obj = datetime.strptime(new_fuse_date, "%Y-%m-%d")

            # Update the MongoDB document with the new fuse date

            # Redirect to the home page after updating
            return redirect(url_for("home"))
        except ValueError:
            # Handle invalid date format
            error_message = (
                "Invalid date format. Please enter the date in YYYY-MM-DD format."
            )
            return render_template("set_fuse_date.html", error=error_message)

    return render_template("set_fuse_date.html")


if __name__ == "__main__":
    try:
        app.run(
            debug=True, use_reloader=False
        )  # Disable reloader if you handle the shutdown manually
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        # scheduler.shutdown(wait=False)
        print("Scheduler has been shut down.")

# app.py
