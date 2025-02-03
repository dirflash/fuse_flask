import logging
import os
import time
from collections import OrderedDict
from datetime import date, datetime
from functools import wraps
from logging.handlers import RotatingFileHandler

import certifi
import pandas as pd
from flask import (
    Flask,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from werkzeug.utils import secure_filename

import modules.preferences.preferences as pref
from flask_session import Session
from modules.fuse_date import FuseDate
from modules.process_attachment import ProcessAttachment
from modules.reminders import Reminders
from modules.se_select import se_select

# pylint: disable=logging-fstring-interpolation


app = Flask(__name__)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config['SESSION_FILE_DIR'] = 'flask_session'
app.config["SESSION_FILE_THRESHOLD"] = 500
app.config["UPLOAD_FOLDER"] = "uploads/"
app.secret_key = pref.FLASK_SECRET_KEY
Session(app)

# Set up logging
log_formatter = logging.Formatter(
    "%(asctime)s - %(filename)s:%(lineno)d - %(name)s - %(levelname)s - %(message)s"
)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# File handler - rotating file handler
file_handler = RotatingFileHandler('./logs/flask_app.log', maxBytes=1000000, backupCount=5)
file_handler.setFormatter(log_formatter)

handlers = app.logger.handlers[:]
for handler in handlers:
    app.logger.removeHandler(handler)

app.logger.addHandler(console_handler)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)

app.logger.info("Application started")

app.config["UPLOAD_FOLDER"] = "uploads/"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

ALLOWED_EXTENSIONS = {"csv"}

# List of admin users
admin_users = ["admin"]


def mongodb_setup_un():
    """
    Setup the MongoDB connection
    """

    if "mode" in session:
        mode = session.get("mode")
        user_db = session.get("user_db")
    else:
        mode = "debug"
        user_db = "fuse-test"

    # Setup the MongoDB connection
    # if mode exists in the session, get the value of mode
    if mode == "debug":
        app.logger.info("Debug mode database connection...")
        Mongo_Connection_URI = MongoClient(
            f"mongodb+srv://{pref.MONGOUN}:{pref.MONGO_BEARER}@{pref.MONGOHOST}/{user_db}"
            f"?retryWrites=true&w=majority&tlsCAFile={certifi.where()}"
            f"&serverSelectionTimeoutMS=500"
        )
    else:
        app.logger.info("Production mode database connection...")
        Mongo_Connection_URI = MongoClient(
            f"mongodb+srv://{pref.MONGOUN}:{pref.MONGO_BEARER}@{pref.MONGOHOST}/{user_db}"
            f"?retryWrites=true&w=majority&tlsCAFile={certifi.where()}"
            f"&serverSelectionTimeoutMS=500"
        )

    try:
        Mongo_Connection_URI.admin.command("ping")
    except Exception as e:
        app.logger.error(f"Error connecting to MongoDB: {e}")
        return None
    app.logger.info("Connected to MongoDB")
    return Mongo_Connection_URI


def allowed_file(filename):
    """Defines allowed file extensions to be uploaded"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def sample_accepted_message(next_date):
    current_message = (
        f"Your current Outlook status for the upcoming FUSE session on {next_date} is <<STATUS>>. "
        f"\n\nTHANK YOU for participating and contributing to strengthening the best group of SAs at Cisco. "
        f"\n\nWe are excited to welcome a special guest, XXXXXXXXX. "
        f"\n\nYou will be assigned a FUSE partner, so please get in touch with that person "
        f"once you have been assigned during the session. "
        f"\n\nIf your plans change, please send an ACCEPT or DECLINE to the Outlook invite "
        f"as soon as possible so that the pairings can be adjusted for the day."
    )
    return current_message


def se_present(Mongo_Connect_URI, fuse_date, db, area):
    prematch = area + "_prematch"
    attendees = Mongo_Connect_URI[db][prematch].find_one(
        {"date": fuse_date}, {"_id": 0}
    )  # type: ignore
    if attendees:
        se_list = sorted(
            set(
                attendees["accepted"]
                + attendees["no_response"]
                + attendees["tentative"]
            )
        )
        # convert se_list to a set
        se_set = set(se_list)
    else:
        se_set = set()
    return se_set


def mongo_attendance(Mongo_Connect_URI, fuse_date, names_list, db, area):
    attendance_area = area + "_attendance"
    attendance_collection = Mongo_Connect_URI[db][attendance_area]
    attendance = attendance_collection.find_one(
        {"date": fuse_date}, {"_id": 0}
    )  # type: ignore
    if attendance:
        app.logger.info("Found existing attendance record")
        # Delete existing documents in names_list
        attendance_collection.delete_many({"date": fuse_date})

        # Update with the new names_list
        names_list = sorted(set(names_list))
        attendance_collection.insert_one({"date": fuse_date, "attended": names_list})
    else:
        app.logger.info("No existing attendance record found")
        # Add date record
        attendance_collection.insert_one({"date": fuse_date, "attended": names_list})
    # Count the number of records in the collection for the specific fuse_date
    total_records = attendance_collection.count_documents({"date": fuse_date})
    app.logger.info(f"Total records for {fuse_date}: {total_records}")
    return total_records


# Function to get attendance
def get_attendance(Mongo_Connect_URI, fuse_date, db, area):
    # attendance_collection = Mongo_Connect_URI[pref.MONGODB]["cwa_attendance"]
    attendance_area = area + "_attendance"
    attendance_collection = Mongo_Connect_URI[db][attendance_area]
    attendance = attendance_collection.find_one(
        {"date": fuse_date}, {"_id": 0}
    )  # type: ignore
    if attendance:
        app.logger.info("Found existing attendance record")
        attended_list = attendance["attended"]
        attended_set = set(attended_list)
    else:
        app.logger.info("No existing attendance record found")
        attended_set = set()
    return attended_set


# Function to process letter list
def letter_list(first_letter_sets):
    sorted_list = {
        letter: sorted(list(names)) for letter, names in first_letter_sets.items()
    }
    return sorted_list


def attendee_dict(se_set):
    # Initialize an empty dictionary
    first_letter_dict = {}

    # Iterate over each name in the set
    for name in se_set:
        # Get the first letter of the name
        first_letter = name[
            0
        ].lower()  # Use .lower() to handle case insensitivity if needed

        # If the first letter is not already a key in the dictionary, add it with an empty set
        if first_letter not in first_letter_dict:
            first_letter_dict[first_letter] = set()

        # Add the name to the set corresponding to the first letter
        first_letter_dict[first_letter].add(name)
    return first_letter_dict


def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        app.logger.info(f"Session contents: {session}")
        if "logged_in" in session:
            app.logger.info("Logged in...")
            return f(*args, **kwargs)
        app.logger.info("Not logged in. Redirect to login...")
        flash("You need to login first.")
        return redirect(url_for("login"))
    return wrap


def is_valid_fuse_date(fuse_date):
    """
    Check if the provided Fuse date is valid.
    """
    if fuse_date is None:
        app.logger.info("Fuse date not set")
        flash("Fuse date needs to be set.")
        return False
    try:
        fuse_date_obj = datetime.strptime(fuse_date, "%Y-%m-%d").date()
    except ValueError:
        app.logger.error(f"Invalid date format: {fuse_date}")
        flash("Invalid date format.")
        return False
    if fuse_date_obj < date.today():
        app.logger.info("Fuse date expired")
        flash("Fuse date needs to be set.")
        return False
    return True


# Define a route for the default page
@app.route("/")
def default():
    app.logger.info("Default page route...")
    username = session.get("username")
    app.logger.info(f"Username: {username}")
    return redirect(url_for("home"))


@app.route("/set_mode", methods=["POST"])
def set_mode():
    if "username" in session and session["username"] in admin_users:
        session["mode"] = request.form["mode"]
    return redirect(url_for("home"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Get the username and password from the form
        username = request.form["username"]
        password = request.form["password"]

        # Check if the username and password are valid
        if username == "admin" and password == "admin":
            # Store the username in the session
            session["username"] = username
            session["logged_in"] = True

            # Redirect to the home page
            return redirect(url_for("home"))

        # If the username or password is invalid, show an error message
        flash("Invalid username or password. Please try again.")

    # If the request method is GET, show the login form
    return render_template("login.html")


@app.route("/logout/")
def logout():
    app.logger.info("Logout route...")
    # Clear the session
    session.clear()
    # Redirect to the home page
    return redirect(url_for("default"))


# Define a route for the home page
@app.route("/home")
# @login_required
def home():
    logging.info(f"Session cookie: {str(session)}")
    current_date = datetime.now().date()
    username = session.get("username")
    # if username not 'None', log username
    if username is not None:
        app.logger.info(f"{username} accessed the home page route...")

        # Get user db from the session
        user_db = "fuse-test"
        mode = "debug"
        if "mode" in session:
            mode = session.get("mode")
            if session["mode"] == "debug":
                user_db = "fuse-test"
            else:
                # Set mode to debug in the session
                logging.info("Setting mode to debug in the session")
                session["mode"] = "debug"
                user_db = session.get("user_db")

        # Get user info from MongoDB in the "fuse-db" database
        Mongo_URI = f"mongodb+srv://{pref.MONGOUSERLOOKUP}:{pref.MONGOUSERBEARER}@{pref.MONGOHOST}/fuse-db"

        Mongo_Connection_URI = MongoClient(
            f"{Mongo_URI}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )

        # Check if the connection to MongoDB is successful
        try:
            Mongo_Connection_URI.admin.command("ping")
        except Exception as e:
            app.logger.error(f"Error connecting to MongoDB: {e}")
            return None
        app.logger.info("Connected to MongoDB fuse-db for user info")

        try:
            user_info = Mongo_Connection_URI["fuse-db"]["admins"].find_one(
                {"username": username}, {"_id": 0}
            )
            if user_info is not None:
                app.logger.info(f"User info found: {user_info}")
            else:
                app.logger.info(f"User info not found for {username}")
        except Exception as e:
            app.logger.error(f"Error getting user info from MongoDB: {e}")
            user_info = None

        if user_info is not None:

            # Get the Fuse date
            user_db = user_info.get("mongo_db")
            user_area = user_info.get("area")
            # add user_db and user_area to the session
            session["user_db"] = user_db
            session["user_area"] = user_area
            if "mode" not in session:
                session["mode"] = "debug"
            app.logger.info(f"User database: {user_db}")

            # MongoDB connection setup for the fuse date user
            Mongo_Uri = f"mongodb+srv://{pref.CWA_SE_USER}:{pref.CWA_SE_BEARER}@{pref.MONGOHOST}/{user_db}"
            Mongo_Connection_URI = MongoClient(
                f"{Mongo_Uri}?retryWrites=true&w=majority",
                tlsCAFile=certifi.where(),
                serverSelectionTimeoutMS=500,
            )

            try:
                Mongo_Connection_URI.admin.command("ping")
            except Exception as e:
                app.logger.error(
                    f"Error connecting to MongoDB ({user_db}) for set fuse date route: {e}"
                )
                return None
            app.logger.info(
                f"Connected to MongoDB ({user_db}) for set fuse date route."
            )

            fuse_date = FuseDate().get_fuse_date(
                Mongo_Connection_URI,
                user_db,
                user_area,
                mode,
            )
            if fuse_date is None:
                app.logger.info("Fuse date not found")
                if "X-FuseDate" in session:
                    del session["X-FuseDate"]
                return redirect(url_for("set_fuse_date"))
            session["X-FuseDate"] = fuse_date
            fuse_date_obj = datetime.strptime(fuse_date, "%Y-%m-%d").date()
            if fuse_date is None:
                fuse_date = "Not set"
            elif fuse_date_obj < current_date:
                fuse_date = "Expired"
                app.logger.info("Fuse date expired")
                flash("Fuse date needs to be set.")
                return redirect(url_for("set_fuse_date"))
            else:
                app.logger.info(f"Fuse date: {fuse_date}")
                app.logger.info(f"Current date: {current_date}")
    else:
        app.logger.info("No username found in session")
        fuse_date_obj = None
    return render_template(
        "home.html",
        fuse_date=fuse_date_obj,
        current_date=current_date,
        username=username,
        admin_users=admin_users,
    )


@app.route("/get_session")
@login_required
def get_session():
    app.logger.info("Get session route...")
    username = session.get("username")
    return make_response(f"<h1>Username: {username}</h1>")


@app.route("/set_fuse_date", methods=["GET", "POST"])
@login_required
def set_fuse_date():

    # Get user db and area from the session
    user_db = "fuse-test"
    mode = "debug"
    if "mode" in session:
        mode = session.get("mode")
        if session["mode"] == "debug":
            user_db = "fuse-test"
        else:
            user_db = session.get("user_db")
    area = session.get("user_area")

    if request.method == "POST":
        app.logger.info("Set fuse date route...")
        # Get the new fuse date from the form
        new_fuse_date = request.form["new_fuse_date"]
        app.logger.info(f"New fuse date: {new_fuse_date}")
        session["X-FuseDate"] = new_fuse_date

        # MongoDB connection setup for the fuse date user

        Mongo_Uri = f"mongodb+srv://{pref.MONGOUN}:{pref.MONGO_BEARER}@{pref.MONGOHOST}/{user_db}"
        Mongo_Connection_URI = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )

        try:
            Mongo_Connection_URI.admin.command("ping")
        except Exception as e:
            app.logger.error(
                f"Error connecting to MongoDB ({user_db}) for set fuse date route: {e}"
            )
            return None
        app.logger.info(f"Connected to MongoDB ({user_db}) for set fuse date route.")

        try:
            # Update the Fuse date in MongoDB
            FuseDate().set_fuse_date(
                Mongo_Connection_URI, user_db, area, new_fuse_date, mode
            )

            # Redirect to the home page after updating
            return redirect(url_for("home"))
        except OperationFailure as e:
            app.logger.error("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
            app.logger.error(f"Error setting the fuse date: {e}")
            app.logger.error(f"User Name: {pref.CWA_SE_USER}")
            app.logger.error(f"User DB: {user_db}")
            app.logger.error(f"Area: {area}")
            app.logger.error(f"New Fuse Date: {new_fuse_date}")
            app.logger.error("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
            flash("Error setting the fuse date.")
            return redirect(url_for("set_fuse_date"))
        except ValueError:
            # Handle invalid date format
            error_message = (
                "Invalid date format. Please enter the date in YYYY-MM-DD format."
            )
            return render_template("set_fuse_date.html", error=error_message)

    app.logger.info("Get fuse date route...")

    Mongo_Connection_URI = mongodb_setup_un()

    # Get the Fuse date
    app.logger.info("Getting the Fuse date...")
    fuse_date = FuseDate().get_fuse_date(Mongo_Connection_URI, user_db, area, mode)
    current_date = date.today()

    if fuse_date is None:
        fuse_date_obj = "Not set"
        flash("Fuse date needs to be set.")
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
                session["X-FuseDate"] = fuse_date

    return render_template(
        "set_fuse_date.html",
        fuse_date=fuse_date_obj,
        current_date=current_date,
        admin_users=admin_users,
    )


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload_file():
    """
    Handle file uploads via the /upload route.

    This function supports both GET and POST methods. For GET requests, it renders the upload form.
    For POST requests, it processes the uploaded file, checks for errors, saves the file, and
    returns a response with the file details.

    Returns:
        Response: Rendered HTML template with appropriate messages and file details.
    """

    app.logger.info(f"File upload route with method: {request.method}")
    if request.method == "POST":
        app.logger.info("File upload post route...")

        # Log the form data
        app.logger.info(f"Form data: {request.form}")

        # Log the files data
        app.logger.info(f"Files data: {request.files}")

        # Check if a file was uploaded
        if not request.files:
            app.logger.error("No files found in /upload request")
            return render_template("upload.html", error="No file uploaded")

        # Check if any file has been uploaded
        file_uploaded = False
        for file_key in request.files:
            file = request.files[file_key]
            if file.filename != "":
                file_uploaded = True

        if file_uploaded:
            if file:
                app.logger.info("File uploaded successfully")

            # Secure the filename
            filename = secure_filename(file.filename)
            app.logger.info(f"Uploaded file: {filename}")

            # Check if the uploads folder exists
            if not os.path.exists(app.config["UPLOAD_FOLDER"]):
                os.makedirs(app.config["UPLOAD_FOLDER"])

            # Record the start time
            start_time = time.time()

            # If the file already exists, delete it and upload the new file
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            if os.path.exists(file_path):
                os.remove(file_path)

            # Save the file to the uploads folder
            file.save(file_path)

            # Check file size
            file_size = os.path.getsize(file_path)
            if file_size > app.config.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024):
                app.logger.error(f"File size exceeds the limit: {file_size}")
                return render_template(
                    "upload.html", error="File size exceeds the limit"
                )

            # Read the file into a Pandas DataFrame
            df = pd.read_csv(file_path)

            # Calculate the upload time with a maximum of 4 decimal places
            upload_time = round(time.time() - start_time, 4)

            # Set filename session cookie
            session["X-Filename"] = filename
            app.logger.info(f"Session cookie: {session}")

            # Render the upload template with the file details
            app.logger.info("Rendering upload template...")

            return render_template(
                "upload.html",
                message="File uploaded successfully",
                filename=filename,
                data=df.to_html(index=False, classes="table table-striped"),
                file_size=file_size,
                upload_time=upload_time,
            )

        if not file_uploaded:
            app.logger.error("No file found in /upload request")
            return render_template("upload.html", error="No file uploaded")

    # If the request method is GET, render the upload form
    return render_template("upload.html")


@app.route("/result", methods=["GET", "POST"])
def result():
    app.logger.info("Result route...")
    return render_template(
        "result.html", error="No error", message="File uploaded successfully"
    )


# Define a route to process the uploaded CSV file
@app.route("/process_csv", methods=["GET", "POST"])
@login_required
def process_csv():
    """
    Handles the /process_csv route.

    This route processes the uploaded CSV file. It supports both GET and POST methods.
    - On GET request: Renders the process_csv.html template with the filename set to
                      "None" if no file is found in the session.
    - On POST request: Processes the CSV file by executing the ProcessAttachment module
                       which updates Mongo with the status of each person. Then, it renders
                       the process_csv.html template with the results of the processing.
                       No Webex messages are sent in this route.

    Returns:
        Response: A Flask Response object that renders the process_csv.html template with
                  the following context variables:
            - filename (str): The name of the uploaded file.
            - accept (int): The number of accepted entries.
            - decline (int): The number of declined entries.
            - tentative (int): The number of tentative entries.
            - no_response (int): The number of entries with no response.
            - admin_users (list): A list of admin users.
    """
    app.logger.info("Process CSV file route...")
    filename = session.get("X-Filename")
    mode = session.get("mode")

    if mode == "debug":
        user_db = "fuse-test"
    else:
        user_db = session.get("user_db")

    area = session.get("user_area")

    # MongoDB connection setup for processing the CSV file
    if mode == "debug":
        Mongo_Uri = f"mongodb+srv://{pref.MONGOUN}:{pref.MONGO_BEARER}@{pref.MONGOHOST}/{user_db}"
        Mongo_Connection_URI = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )
    else:
        Mongo_Uri = f"mongodb+srv://{pref.CWA_SE_USER}:{pref.CWA_SE_BEARER}@{pref.MONGOHOST}/{user_db}"
        Mongo_Connection_URI = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )

    try:
        Mongo_Connection_URI.admin.command("ping")
    except Exception as e:
        app.logger.error(
            f"Error connecting to MongoDB ({user_db}) for set fuse date route: {e}"
        )
        return None
    app.logger.info(f"Connected to MongoDB ({user_db}) for set fuse date route.")

    # Get the Fuse date
    app.logger.info("Getting the Fuse date...")
    fuse_date = FuseDate().get_fuse_date(Mongo_Connection_URI, user_db, area, mode)

    app.logger.info(f"File name: {filename}")
    if filename is None:
        return render_template("process_csv.html", filename="None")

    accept, decline, tentative, no_response = ProcessAttachment(
        fuse_date, filename, Mongo_Connection_URI, user_db, area
    ).process()
    return render_template(
        "process_csv.html",
        filename=filename,
        accept=accept,
        decline=decline,
        tentative=tentative,
        no_response=no_response,
        admin_users=admin_users,
        user_db=user_db,
    )


# Define a route to send reminders
@app.route("/send_reminders", methods=["GET", "POST"])
@login_required
def send_reminders():
    """
    Route to send reminders based on the Fuse date.
    """
    app.logger.info("Send reminders route...")

    # Check for valid Fuse date
    app.logger.info("Checking for valid Fuse date...")
    fuse_date = session.get("X-FuseDate")
    if not is_valid_fuse_date(fuse_date):
        return redirect(url_for("set_fuse_date"))

    # Send reminders
    app.logger.info("Sending reminders...")

    # Get user db and area from the session
    user_db = session.get("user_db")
    area = session.get("user_area")

    Mongo_Connection_URI = mongodb_setup_un()

    reminders_result = Reminders(
        fuse_date, Mongo_Connection_URI, user_db, area
    ).send_reminders()
    if reminders_result is None:
        app.logger.error("Failed to send reminders")
        return render_template("error.html", message="Failed to send reminders.")

    (
        record_found,
        remind_accepted,
        remind_declined,
        remind_tentative,
        remind_no_response,
    ) = reminders_result
    if record_found:
        app.logger.info("Record found")
        total_count = sum(
            len(remind)
            for remind in [
                remind_accepted,
                remind_declined,
                remind_tentative,
                remind_no_response,
            ]
        )
        return render_template(
            "send_reminders.html",
            found=record_found,
            accept=len(remind_accepted),
            decline=len(remind_declined),
            tentative=len(remind_tentative),
            no_response=len(remind_no_response),
            total=total_count,
            admin_users=admin_users,
        )
    app.logger.info("No records found")
    return render_template(
        "error.html",
        message="No records found.",
        admin_users=admin_users,
    )


# Define a route to special guest
@app.route("/guest", methods=["GET", "POST"])
@login_required
def special_guest():
    fuse_date = session.get("X-FuseDate")
    accepted_message = sample_accepted_message(fuse_date)
    messages = {
        "accepted": accepted_message,
    }
    if request.method == "POST":
        app.logger.info("Set reminders message...")
        try:
            data = request.get_json()
            for key in messages.keys():  # pylint: disable=consider-using-dict-items
                if key in data:
                    messages[key] = data[key]
                    app.logger.info(f"New {key} received: {data[key]}")
            return render_template("special_guest.html", messages=messages)
        except Exception as e:
            app.logger.error(f"Error: {e}")
            return "Internal Server Error", 500
    app.logger.info("Get reminders message...")
    return render_template(
        "special_guest.html",
        messages=messages,
        admin_users=admin_users,
    )


# Define a route to SE attendance
@app.route("/se_attendance", methods=["GET", "POST"])
@login_required
def se_attendance():
    app.logger.info("SE attendance route...")
    fuse_date = session.get("X-FuseDate")
    filename = session.get("X-Filename")
    mode = session.get("mode")

    if mode == "debug":
        user_db = "fuse-test"
    else:
        user_db = session.get("user_db")

    area = session.get("user_area")

    # MongoDB connection setup for selecting SEs
    if mode == "debug":
        Mongo_Uri = f"mongodb+srv://{pref.MONGOUN}:{pref.MONGO_BEARER}@{pref.MONGOHOST}/{user_db}"
        Mongo_Connection_URI = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )
    else:
        Mongo_Uri = f"mongodb+srv://{pref.CWA_SE_USER}:{pref.CWA_SE_BEARER}@{pref.MONGOHOST}/{user_db}"
        Mongo_Connection_URI = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )

    try:
        Mongo_Connection_URI.admin.command("ping")
    except Exception as e:
        app.logger.error(
            f"Error connecting to MongoDB ({user_db}) for set fuse date route: {e}"
        )
        return None
    app.logger.info(f"Connected to MongoDB ({user_db}) for set fuse date route.")

    # Get the list of names from the database
    se_set = se_present(Mongo_Connection_URI, fuse_date, user_db, area)
    attendees = attendee_dict(se_set)
    se_dict = letter_list(attendees)

    # Sort se_dict by keys in alphabetical order
    sorted_dict = OrderedDict()
    for key in sorted(se_dict):
        sorted_dict[key] = sorted(se_dict[key])

    return render_template(
        "se_attendance.html",
        sorted_names=sorted_dict,
        admin_users=admin_users,
        file_name=filename,
        user_db=user_db,
    )


@app.route("/submit_names", methods=["POST"])
def submit_names():
    fuse_date = session.get("X-FuseDate")
    selected_names = request.form.getlist("names")
    filename = session.get("X-Filename")
    logging.info(f"Selected names: {selected_names}")

    mode = session.get("mode")

    # Get user db and area from the session
    if mode == "debug":
        user_db = "fuse-test"
    else:
        user_db = session.get("user_db")

    area = session.get("user_area")

    # MongoDB connection setup for submitting attending SEs
    if mode == "debug":
        Mongo_Uri = f"mongodb+srv://{pref.MONGOUN}:{pref.MONGO_BEARER}@{pref.MONGOHOST}/{user_db}"
        Mongo_Connection_URI = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )
    else:
        Mongo_Uri = f"mongodb+srv://{pref.CWA_SE_USER}:{pref.CWA_SE_BEARER}@{pref.MONGOHOST}/{user_db}"
        Mongo_Connection_URI = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )

    try:
        Mongo_Connection_URI.admin.command("ping")
    except Exception as e:
        app.logger.error(
            f"Error connecting to MongoDB ({user_db}) for set fuse date route: {e}"
        )
        return None
    app.logger.info(f"Connected to MongoDB ({user_db}) for set fuse date route.")

    # Update the database with the selected names in cwa_attendance
    attendance = mongo_attendance(
        Mongo_Connection_URI, fuse_date, selected_names, user_db, area
    )
    if attendance > 0:
        flash("Attendance updated successfully")
        logging.info("Attendance updated successfully")
    else:
        flash("No names selected")
        logging.info("No names selected")
    return render_template(
        "selected_names.html",
        selected_names=selected_names,
        admin_users=admin_users,
        user_db=user_db,
    )


@app.route("/match", methods=["GET", "POST"])
@login_required
def match():
    app.logger.info("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
    app.logger.info(f"SE match route with method: {request.method}")
    app.logger.info("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
    fuse_date = session.get("X-FuseDate")
    mode = session.get("mode")

    # Get user db and area from the session
    if mode == "debug":
        app.logger.info("Debug mode database connection...")
        user_db = "fuse-test"
    else:
        user_db = session.get("user_db")

    # Get user db and area from the session
    area = session.get("user_area")
    mongo_db = session.get("mongo_db")

    # MongoDB connection setup for processing the CSV file
    if mode == "debug":
        Mongo_Uri = f"mongodb+srv://{pref.MONGOUN}:{pref.MONGO_BEARER}@{pref.MONGOHOST}/{user_db}"
        Mongo_Connection_URI = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )
    else:
        Mongo_Uri = f"mongodb+srv://{pref.CWA_SE_USER}:{pref.CWA_SE_BEARER}@{pref.MONGOHOST}/{user_db}"
        Mongo_Connection_URI = MongoClient(
            f"{Mongo_Uri}?retryWrites=true&w=majority",
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=500,
        )

    try:
        Mongo_Connection_URI.admin.command("ping")
    except Exception as e:
        app.logger.error(
            f"Error connecting to MongoDB ({user_db}) for set fuse date route: {e}"
        )
        return None
    app.logger.info(f"Connected to MongoDB ({user_db}) for set fuse date route.")

    if fuse_date is None:
        app.logger.error("Fuse date not found in session")
    if request.method == "POST":
        match_file = "NA"
        app.logger.info("SE match post route...")
        # Match attending SEs
        se_set = get_attendance(Mongo_Connection_URI, fuse_date, user_db, area)
        # Does "mode" exist in the session?
        if "mode" not in session:
            mode = "production"
            session["mode"] = mode
        # if "mode" exists in the session, get the value of "mode"
        else:
            mode = session.get("mode")
        # SE matching process. Returns the file name of the match file
        status = se_select(fuse_date, Mongo_Connection_URI, se_set)  # , mode)
        if status == "NA":
            app.logger.warning("No SEs match file created.")
            match_file = "NA"
            df = None
        # check if status is a 3 digit http error code
        elif status == "500":
            # return errorhandler
            app.logger.error(f"Internal Server Error: {status}")
            return render_template("500.html", error=status), int(status)
        else:
            app.logger.info(f"SE match file ({status}) created.")
            match_file = status
            csv_file = f"match_files/{status}"
            # Read the match file into a Pandas DataFrame
            df = pd.read_csv(csv_file)
        #
        #
        #
        mode = session.get("mode")
        if mode == "debug":
            flash(f"Mode: {mode}")

        return render_template(
            "post_match.html",
            admin_users=admin_users,
            fuse_date=fuse_date,
            test_mode=mode,
            match_file=match_file,
            user_db=user_db,
            data=df.to_html(index=False, classes="table table-striped"),
            csv_file=csv_file,
        )

    app.logger.info("SE match get route...")
    # Get the list of names from the database
    se_set = get_attendance(Mongo_Connection_URI, fuse_date, user_db, area)
    attendees = attendee_dict(se_set)
    se_dict = letter_list(attendees)

    # Sort se_dict by keys in alphabetical order
    sorted_dict = OrderedDict()
    for key in sorted(se_dict):
        sorted_dict[key] = sorted(se_dict[key])

    return render_template(
        "match.html",
        fuse_date=fuse_date,
        sorted_names=sorted_dict,
        admin_users=admin_users,
        total_names=len(se_set),
        test_mode=mode,
        user_db=user_db,
    )


@app.route("/update-mode", methods=["POST"])
def update_mode():
    data = request.get_json()
    if "mode" in data:
        session["mode"] = data["mode"]
        return jsonify({"success": True}), 200
    return jsonify({"error": "Invalid request"}), 400


# Define a route for the about page
@app.route("/about")
def about():
    app.logger.info("About page route...")
    return render_template(
        "about.html",
        admin_users=admin_users,
    )


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


@app.route("/robots.txt")
def robots():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "robots.txt",
        mimetype="text/plain",
    )


@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "sitemap.xml",
        mimetype="application/xml",
    )


@app.errorhandler(404)
def page_not_found(e):
    app.logger.error(f"{request.path} was requested and not found: {e}")
    return render_template("404.html", error=e), 404


@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f"Internal server error: {e}")
    # Log requested path
    app.logger.error(f"Requested path: {request.path}")
    return render_template("500.html", error=e), 500


@app.route("/match_progress", methods=["GET"])
def match_progress():
    return render_template("match_progress.html", admin_users=admin_users)


if __name__ == "__main__":
    app.run(debug=True)

# flask --app app run --debug
# app.py
