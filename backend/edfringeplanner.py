import datetime
import uuid
from urllib.parse import urlparse, urljoin

import flask

import flask_login
import psycopg2
import requests
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask import Flask, request
from flask_cachebuster import CacheBuster
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from sortedcontainers import SortedSet

import db
from config import Config
from events import load_events, mark_booked, set_interest, Filter
from importer import import_from_url

config = Config.from_env()

app = Flask("edfringeplanner")
app.secret_key = config.session_key

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

cache_buster = CacheBuster(config={"extensions": [".css"], "hash_size": 8})
cache_buster.init_app(app)


def render_template(template, **kwargs):
    current_user = flask_login.current_user
    if not current_user.is_anonymous:
        kwargs = {**kwargs, "user": flask_login.current_user}
    return flask.render_template(template, **kwargs)


class User(UserMixin):
    def __init__(self, id):
        self.id = id

        with db.cursor(config) as cur:
            cur.execute(
                "SELECT start_datetime_utc, end_datetime_utc FROM users WHERE id = %s",
                (id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("Unknown user: {}".format(id))
        self.visit_days = [
            date for date in self.dates_between(row[0].date(), row[1].date())
        ]

    @staticmethod
    def dates_between(start_date, end_date):
        for i in range((end_date - start_date).days):
            yield start_date + datetime.timedelta(days=i)


@login_manager.user_loader
def load_user(user_id):
    return User(user_id)


def user_id():
    return int(flask_login.current_user.id)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/day/<date_str>")
@login_required
def one_day(date_str):
    try:
        date = datetime.datetime.strptime(
            "{} +0100".format(date_str), "%Y-%m-%d %z"
        ).date()
    except ValueError:
        return "Invalid date in URL"

    show_likes = True
    show_must = True
    show_booked = True
    hidden_categories = set()
    for hidden in request.args.getlist("hidden"):
        if hidden == "like":
            show_likes = False
        elif hidden == "love":
            show_must = False
        elif hidden == "booked":
            show_booked = False
        else:
            hidden_categories.add(hidden)

    display_filter = Filter(
        show_like=show_likes,
        show_must=show_must,
        show_booked=show_booked,
        hidden_categories=SortedSet(hidden_categories),
    )

    event_columns, first_hour, number_of_hours = load_events(
        config, user_id(), date, display_filter
    )
    return render_template(
        "one_day.html",
        date=date,
        date_yyyymmdd=date.strftime("%Y-%m-%d"),
        event_columns=event_columns,
        first_hour=first_hour,
        number_of_hours=number_of_hours,
        hour_height_px=200,
        url_hiding=lambda s: day_url(hiding=s),
        url_showing=lambda s: day_url(showing=s),
        display_filter=display_filter,
    )


@app.route("/booked/<performance_id>")
@login_required
def booked(performance_id):
    mark_booked(config, user_id(), performance_id)
    if is_safe_url(request.referrer):
        return flask.redirect(request.referrer)
    return "Done"


@app.route("/love/<show_id>")
@login_required
def love(show_id):
    set_interest(config, user_id(), show_id, "Must")
    if is_safe_url(request.referrer):
        return flask.redirect(request.referrer)
    return "Done"


@app.route("/like/<show_id>")
@login_required
def like(show_id):
    set_interest(config, user_id(), show_id, "Like")
    if is_safe_url(request.referrer):
        return flask.redirect(request.referrer)
    return "Done"


@app.route("/login")
def login():
    kwargs = {}
    if flask.request.args.get("error") == "true":
        kwargs["error"] = True
    email = flask.request.args.get("email")
    if email is not None:
        kwargs["email"] = email
    return render_template("login.html", **kwargs)


@app.route("/login", methods=("POST",))
def handle_login():
    email = request.form.get("email", None)
    password = request.form.get("password", None)
    if email is None or password is None:
        return flask.redirect(flask.url_for("login", error="true", email=email))
    with db.cursor(config) as cur:
        cur.execute(
            "SELECT id, password_hash FROM users WHERE email = %s AND confirm_email_token is NULL",
            (email,),
        )
        row = cur.fetchone()
        if row is None:
            return flask.redirect(flask.url_for("login", error="true", email=email))
    id, password_hash = row
    try:
        PasswordHasher().verify(password_hash, password)
    except VerifyMismatchError:
        return flask.redirect(flask.url_for("login", error="true", email=email))
    login_user(User("{}".format(id)), remember=True)
    index_url = flask.url_for("index")
    target = flask.request.args.get("next", index_url)
    safe_target = target if is_safe_url(target) else index_url
    return flask.redirect(safe_target)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return flask.redirect(flask.url_for("index"))


@app.route("/signup")
def signup():
    kwargs = {}
    for key in ["error", "needs_verification", "email", "start_date", "end_date"]:
        value = flask.request.args.get(key)
        if value is not None:
            kwargs[key] = value
    return render_template("signup.html", **kwargs)


@app.route("/signup", methods=("POST",))
def handle_signup():
    email = flask.request.form.get("email")
    password = flask.request.form.get("password")

    try:
        start_date = datetime.datetime.strptime(flask.request.form.get("start_date"), "%Y-%m-%d")
        end_date = datetime.datetime.strptime(flask.request.form.get("end_date"), "%Y-%m-%d") + datetime.timedelta(days=1)
    except ValueError:
        return flask.redirect(
            flask.url_for(
                "signup",
                error="date",
                email=email,
            )
        )


    if not email or not password or not start_date or not end_date:
        return flask.redirect(
            flask.url_for(
                "signup",
                error="true",
                email=email,
                start_date=start_date,
                end_date=end_date,
            )
        )

    password_hash = PasswordHasher().hash(password)

    confirm_email_token = uuid.uuid4().hex
    import_token = uuid.uuid4().hex

    with db.cursor(config) as cur:
        try:
            cur.execute(
                "INSERT INTO users "
                + "(email, password_hash, start_datetime_utc, end_datetime_utc, confirm_email_token, import_token) "
                + "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    email,
                    password_hash,
                    start_date,
                    end_date,
                    confirm_email_token,
                    import_token,
                ),
            )
        except psycopg2.errors.UniqueViolation:
            return flask.redirect(
                flask.url_for(
                    "signup",
                    error="true",
                    email=email,
                    start_date=start_date,
                    end_date=end_date,
                )
            )

    requests.post(
        "https://api.mailgun.net/v3/{}/messages".format(config.mailgun_domain),
        auth=("api", config.mailgun_key),
        data={
            "from": "edfringe planner <signup@edfringeplanner.co.uk>",
            "to": [email],
            "subject": "Please verify your email for edfringeplanner",
            "text": "Please follow this link to verify your account on edfringeplanner.co.uk - {}{} - if you didn't request this, just ignore the email and you'll never hear from us again.".format(
                config.domain_prefix,
                flask.url_for("verify", email=email, token=confirm_email_token),
            ),
        },
    )

    return flask.redirect(flask.url_for("signup", needs_verification="true"))


@app.route("/verify/<email>/<token>")
def verify(email, token):
    with db.cursor(config) as cur:
        cur.execute(
            "UPDATE users SET confirm_email_token = NULL WHERE email = %s AND confirm_email_token = %s RETURNING id",
            (email, token),
        )
        row = cur.fetchone()
        if row is None:
            return flask.redirect(flask.url_for("login", email=email, error="true"))
        login_user(User("{}".format(row[0])), remember=True)
        return flask.redirect(flask.url_for("index"))


@app.route("/import")
@login_required
def import_form():
    with db.cursor(config) as cur:
        cur.execute("SELECT import_token FROM users WHERE id = %s", (user_id(),))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Internal error: couldn't find import token")
        import_token = row[0]
        import_email = "import-{}@{}".format(import_token, config.mailgun_domain)
    return render_template("import.html", import_email=import_email)


@app.route("/import", methods=("POST",))
def import_csv():
    recipient = request.form.get("recipient")
    if recipient is None:
        raise ValueError("Can't find recipient")
    prefix = "import-"
    suffix = "@{}".format(config.mailgun_domain)
    if not recipient.startswith(prefix) or not recipient.endswith(suffix):
        raise ValueError("Unexpected recipient: {}".format(recipient))
    import_token = recipient[len(prefix) : -len(suffix)]

    body = request.form.get("body-plain")
    if body is None:
        raise ValueError("Can't find body")
    words = body.split()
    url = next(
        (
            word
            for word in words
            if word.startswith("https://tickets.edfringe.com/")
            and word.endswith(".csv")
        ),
        None,
    )
    if url is None:
        raise ValueError("Can't find csv link in body")
    with db.cursor(config) as cur:
        cur.execute("SELECT id FROM users WHERE import_token = %s", (import_token,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Unknown import token: {}".format(import_token))
        uid = row[0]
        import_from_url(cur, uid, url)

    return "OK"


def is_safe_url(target):
    if target is None:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def day_url(showing=None, hiding=None):
    hidden = set(request.args.getlist("hidden"))
    if showing is not None:
        hidden.remove(showing)
    if hiding is not None:
        hidden.add(hiding)
    parts = "&".join("hidden={}".format(h) for h in sorted(hidden))
    query = "?{}".format(parts) if parts else ""
    return "{}{}".format(request.path, query)


def main():
    # Check db is configured properly.
    with db.cursor(config) as cur:
        cur.execute("SELECT id FROM venues LIMIT 1")
    app.run(debug=True, host="0.0.0.0")


if __name__ == "__main__":
    main()
