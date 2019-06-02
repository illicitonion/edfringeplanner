import datetime
from flask import Flask, render_template

import db
from events import load_events, mark_booked, set_interest

app = Flask("edfringeplanner")


@app.route("/")
def index():
    return "Hello"


@app.route("/day/<date_str>")
def one_day(date_str):
    try:
        date = datetime.datetime.strptime(
            "{} +0100".format(date_str), "%Y-%m-%d %z"
        ).date()
    except ValueError:
        return "Invalid date in URL"

    event_columns = load_events(date)
    return render_template(
        "one_day.html",
        date=date,
        event_columns=event_columns,
        one_day=datetime.timedelta(days=1),
    )


@app.route("/booked/<performance_id>")
def booked(performance_id):
    mark_booked(performance_id)
    return "Done"


@app.route("/love/<show_id>")
def love(show_id):
    set_interest(show_id, "Must")
    return "Done"


@app.route("/like/<show_id>")
def like(show_id):
    set_interest(show_id, "Like")
    return "Done"


def main():
    # Check db is configured properly.
    with db.cursor() as cur:
        cur.execute("SELECT id FROM venues LIMIT 1")
    app.run(debug=True, host="0.0.0.0")


if __name__ == "__main__":
    main()
