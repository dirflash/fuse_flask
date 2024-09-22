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
from werkzeug.utils import secure_filename

import modules.preferences.preferences as pref
from flask_session import Session
from modules.fuse_date import FuseDate
from modules.process_attachment import ProcessAttachment
from modules.reminders import Reminders

# pylint: disable=logging-fstring-interpolation


app = Flask(__name__)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config['SESSION_FILE_DIR'] = 'flask_session'
app.config["SESSION_FILE_THRESHOLD"] = 500
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

# Setup the MongoDB connection
Mongo_Connection_URI: MongoClient = MongoClient(
    f"{pref.MONGO_URI}?retryWrites=true&w=majority",
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=500,
)

# List of admin users
admin_users = ["admin"]


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


def se_present(Mongo_Connect_URI, fuse_date):
    attendees = Mongo_Connect_URI[pref.MONGODB]["cwa_prematch"].find_one(
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


def mongo_attendance(Mongo_Connect_URI, fuse_date, names_list):
    attendance_collection = Mongo_Connect_URI[pref.MONGODB]["cwa_attendance"]
    attendance = attendance_collection.find_one(
        {"date": fuse_date}, {"_id": 0}
    )  # type: ignore
    if attendance:
        logging.info("Found existing attendance record")
        # Delete existing documents in names_list
        attendance_collection.delete_many({"date": fuse_date})

        # Update with the new names_list
        names_list = sorted(set(names_list))
        attendance_collection.insert_one({"date": fuse_date, "attended": names_list})
    else:
        logging.info("No existing attendance record found")
        # Add date record
        attendance_collection.insert_one({"date": fuse_date, "attended": names_list})
    # Count the number of records in the collection for the specific fuse_date
    total_records = attendance_collection.count_documents({"date": fuse_date})
    logging.info(f"Total records for {fuse_date}: {total_records}")
    return total_records


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

        # Get the Fuse date
        fuse_date = FuseDate().get_fuse_date(Mongo_Connection_URI)
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
    if request.method == "POST":
        app.logger.info("Set fuse date route...")
        # Get the new fuse date from the form
        new_fuse_date = request.form["new_fuse_date"]
        app.logger.info(f"New fuse date: {new_fuse_date}")
        session["X-FuseDate"] = new_fuse_date

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

    return render_template(
        "set_fuse_date.html",
        fuse_date=fuse_date_obj,
        current_date=current_date,
        admin_users=admin_users,
    )


@app.route("/upload", methods=["GET", "POST"])
@login_required
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

        # Set filename session cookie
        session["X-Filename"] = filename

        response = make_response(render_template(
            "upload.html",
            message="File uploaded successfully",
            filename=filename,
            data=df.to_html(index=False, classes="table table-striped"),
            file_size=file_size,
            upload_time=upload_time,))
        return make_response(response)
    return render_template(
        "upload.html",
        admin_users=admin_users,
    )


# Define a route to process the uploaded CSV file
@app.route("/process_csv", methods=["GET", "POST"])
@login_required
def process_csv():
    app.logger.info("Process CSV file route...")
    filename = session.get("X-Filename")
    fuse_date = FuseDate().get_fuse_date(Mongo_Connection_URI)
    app.logger.info(f"File name: {filename}")
    if filename is None:
        return render_template("process_csv.html", filename="None")
    accept, decline, tentative, no_response = ProcessAttachment(
        fuse_date, filename, Mongo_Connection_URI
    ).process()
    return render_template(
        "process_csv.html",
        filename=filename,
        accept=accept,
        decline=decline,
        tentative=tentative,
        no_response=no_response,
        admin_users=admin_users,
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
    reminders_result = Reminders(fuse_date, Mongo_Connection_URI).send_reminders()
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
    fuse_date = session.get("X-FuseDate")
    # Get the list of names from the database
    se_set = se_present(Mongo_Connection_URI, fuse_date)
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
    )


@app.route("/submit_names", methods=["POST"])
def submit_names():
    fuse_date = session.get("X-FuseDate")
    selected_names = request.form.getlist("names")
    logging.info(f"Selected names: {selected_names}")
    # Update the database with the selected names in cwa_attendance
    attendance = mongo_attendance(Mongo_Connection_URI, fuse_date, selected_names)
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
    )


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


if __name__ == "__main__":
    app.run(debug=True)

# flask --app app run --debug
# app.py
