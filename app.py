import logging
import os
import time
from logging.handlers import RotatingFileHandler

import certifi
import pandas as pd
from flask import Flask, render_template, request, send_from_directory
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from werkzeug.utils import secure_filename

import modules.preferences.preferences as pref

# pylint: disable=logging-fstring-interpolation

app = Flask(__name__)

# Configure logging
file_handler = RotatingFileHandler("logging/flask_app.log", maxBytes=10000, backupCount=5)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
file_handler.setFormatter(file_formatter)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_formatter = logging.Formatter("%(name)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)

app.logger.addHandler(file_handler)
app.logger.addHandler(console_handler)
app.logger.setLevel(logging.DEBUG)
app.logger.info("Application started")

app.config["UPLOAD_FOLDER"] = "uploads/"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

ALLOWED_EXTENSIONS = {"csv"}

# Setup the MongoDB connection
Mongo_Connection_URI: MongoClient = MongoClient(
    f"{pref.MONGO_URI}?retryWrites=true&w=majority",
    tlsCAFile=certifi.where(),serverSelectionTimeoutMS=500
)

def check_mongo_connection():
    ''' Test the MongoDB connection '''
    try:
        Mongo_Connection_URI.server_info()
        app.logger.info("Test connection to MongoDB successful.")
        # Close connection to Mongo
        # Mongo_Connection_URI.close()
        # app.logger.info("Closed connection to MongoDB.")
    except ConnectionFailure:
        app.logger.error("Failed to connect to MongoDB")
        # app.logger.error(mongo_connection_failure)
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


def allowed_file(filename):
    """Defines allowed file extensions to be uploaded

    Args:
        filename (str): uploaded filename

    Returns:
        str: file extension if in ALLOWED_EXTENSIONS
    """
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.before_request
def before_request():
    response = check_mongo_connection()
    if response:
        return response

@app.before_request
def log_request_info():
    """Log the requestor information for each request"""
    remote_addr = request.remote_addr
    user_agent = request.headers.get("User-Agent")
    request_path = request.path
    request_method = request.method

    log_message = (
        f"Request from {remote_addr} - {user_agent} - {request_method} {request_path}"
    )
    app.logger.info(log_message)


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
    return render_template('index.html')

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


if __name__ == '__main__':
    app.run(debug=True)

# app.py
