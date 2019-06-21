import datetime
from urllib.parse import urlparse, urljoin

import flask
import os

import flask_login
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask import Flask, render_template, request
from flask_login import LoginManager, UserMixin, login_user, login_required

import db
from events import load_events, mark_booked, set_interest

app = Flask("edfringeplanner")
app.secret_key = os.environ["EDFRINGEPLANNER_SECRET_KEY"].encode("utf-8")

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


class User(UserMixin):
    def __init__(self, id):
        self.id = id


@login_manager.user_loader
def load_user(user_id):
    return User(user_id)


def user_id():
    return int(flask_login.current_user.id)


@app.route("/")
def index():
    return "Hello"


@app.route("/day/<date_str>")
@login_required
def one_day(date_str):
    try:
        date = datetime.datetime.strptime(
            "{} +0100".format(date_str), "%Y-%m-%d %z"
        ).date()
    except ValueError:
        return "Invalid date in URL"

    event_columns, first_hour, number_of_hours = load_events(user_id(), date)
    return render_template(
        "one_day.html",
        date=date,
        event_columns=event_columns,
        one_day=datetime.timedelta(days=1),
        first_hour=first_hour,
        number_of_hours=number_of_hours,
    )


@app.route("/booked/<performance_id>")
@login_required
def booked(performance_id):
    mark_booked(user_id(), performance_id)
    return "Done"


@app.route("/love/<show_id>")
@login_required
def love(show_id):
    set_interest(user_id(), show_id, "Must")
    return "Done"


@app.route("/like/<show_id>")
@login_required
def like(show_id):
    set_interest(user_id(), show_id, "Like")
    return "Done"


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/login", methods=("POST",))
def handle_login():
    email = request.form.get("email", None)
    password = request.form.get("password", None)
    if email is None or password is None:
        return flask.redirect(flask.url_for("login"))
    with db.cursor() as cur:
        cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        if row is None:
            return flask.redirect(flask.url_for("login"))
    id, password_hash = row
    try:
        PasswordHasher().verify(password_hash, password)
    except VerifyMismatchError:
        return flask.redirect(flask.url_for("login"))
    login_user(User("{}".format(id)), remember=True)
    index_url = flask.url_for("index")
    target = flask.request.args.get("next", index_url)
    safe_target = target if is_safe_url(target) else index_url
    return flask.redirect(safe_target)


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def main():
    # Check db is configured properly.
    with db.cursor() as cur:
        cur.execute("SELECT id FROM venues LIMIT 1")
    app.run(debug=True, host="0.0.0.0")


if __name__ == "__main__":
    main()
