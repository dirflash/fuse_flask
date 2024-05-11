import logging
import os
import time
from datetime import date, datetime

import certifi
import pandas as pd
from flask import (Flask, redirect, render_template, request,
                   send_from_directory, url_for)
from pymongo import MongoClient
from werkzeug.utils import secure_filename

import modules.preferences.preferences as pref
from modules.fuse_date import FuseDate

# pylint: disable=logging-fstring-interpolation

app = Flask(__name__)

# Set up console logging
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
console_handler.setFormatter(console_formatter)

"""# Set up file logging
log_file = os.path.join(app.root_path, "logs", "flask_app.log")
file_handler = RotatingFileHandler(log_file, maxBytes=10000, backupCount=5)
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
file_handler.setFormatter(file_formatter)"""

# Configure the root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(console_handler)
# root_logger.addHandler(file_handler)

app.logger.info("Application started")

app.config["UPLOAD_FOLDER"] = "uploads/"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

ALLOWED_EXTENSIONS = {"csv"}

# Setup the MongoDB connection
Mongo_Connection_URI: MongoClient = MongoClient(
    f"{pref.MONGO_URI}?retryWrites=true&w=majority",
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=500,
)


def allowed_file(filename):
    """Defines allowed file extensions to be uploaded"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Define a route for the home page
@app.route("/")
def home():
    app.logger.info("Home page route...")
    current_date = datetime.now().date()

    # Get the Fuse date
    fuse_date = FuseDate().get_fuse_date(Mongo_Connection_URI)
    if fuse_date is None:
        fuse_date = "Not set"
    else:
        fuse_date_obj = datetime.strptime(fuse_date, "%Y-%m-%d").date()
        app.logger.info(f"Fuse date: {fuse_date}")
        app.logger.info(f"Current date: {current_date}")
    return render_template(
        "index.html", fuse_date=fuse_date_obj, current_date=current_date
    )


@app.route("/set_fuse_date", methods=["GET", "POST"])
def set_fuse_date():
    if request.method == "POST":
        app.logger.info("Set fuse date route...")
        # Get the new fuse date from the form
        new_fuse_date = request.form["new_fuse_date"]
        app.logger.info(f"New fuse date: {new_fuse_date}")

        try:
            # Update the Fuse date in MongoDB
            FuseDate().set_fuse_date(Mongo_Connection_URI, new_fuse_date)

            # Redirect to the home page after updating
            return redirect(url_for("home"))
        except ValueError:
            # Handle invalid date format
            error_message = (
                "Invalid date format. Please enter the date in YYYY-MM-DD format."
            )
            return render_template("set_fuse_date.html", error=error_message)

    app.logger.info("Get fuse date route...")
    # Get the Fuse date
    fuse_date = FuseDate().get_fuse_date(Mongo_Connection_URI)
    current_date = date.today()

    if fuse_date is None:
        fuse_date = "Not set"
    else:
        try:
            fuse_date_obj = datetime.strptime(fuse_date, "%Y-%m-%d").date()
        except ValueError:
            app.logger.error(f"Invalid date format: {fuse_date}")
            fuse_date = "Invalid date"
        else:
            if fuse_date_obj < current_date:
                fuse_date = fuse_date_obj
            else:
                app.logger.info(f"Fuse date: {fuse_date_obj}")
                app.logger.info(f"Current date: {current_date}")

    return render_template(
        "set_fuse_date.html", fuse_date=fuse_date_obj, current_date=current_date
    )


@app.route("/upload", methods=["GET", "POST"])
def upload_file():
    app.logger.info("File upload route...")
    if request.method == "POST":
        app.logger.info("File upload post route...")
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
            data=df.to_html(index=False, classes="table table-striped"),
            file_size=file_size,
            upload_time=upload_time,
        )

    return render_template("upload.html")


# Define a route to process the uploaded CSV file
@app.route("/process_csv", methods=["GET", "POST"])
def process_csv():
    app.logger.info("Process CSV file route...")
    filename = "None"
    app.logger.info(f"File name: {filename}")
    if filename is None:
        return render_template("process_csv.html", filename="None")
    return render_template("process_csv.html", filename=filename)


# Define a route for the about page
@app.route("/about")
def about():
    app.logger.info("About page route...")
    return render_template("about.html")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


if __name__ == "__app__":
    app.run(debug=True)

# flask --app app run --debug
# app.py
